#!/usr/bin/env python3
"""Check the SHIPPED clock waveforms against the library's min_pulse_width.

Defect M19, the vertical-slice half. `stdcells` lib-v1.7 measures the
constraint; this asserts the die actually satisfies it, because a constraint
nothing checks is the defect this repo keeps finding, not the fix for it.

WHY THIS NEEDED A NEW SCRIPT INSTEAD OF A METRIC. librelane emits no
min-pulse-width metric at all -- verified by listing every key in a real
`final/metrics.json`: there is `max_slew`, `max_cap`, `max_fanout`, setup and
hold, and nothing whatever for pulse width. So there was no number to add to
check_signoff.py's MUST_BE_ZERO list; the check has to be RUN.

WHY IT MATTERS ON THIS DIE SPECIFICALLY. The ring-oscillator prescaler is
clocked DIRECTLY by the ring through a 3-way mux, so `ro_clk`'s half period is
a real clock pulse presented to a real flop -- and it is the fastest clock on
the chip by two orders of magnitude. If the flop cannot capture on a pulse that
narrow, the counter does not count, and the number this whole chip exists to
measure is wrong in a way no other check would notice: not zero, not obviously
broken, just wrong.

ⓘ TWO OpenSTA BEHAVIOURS THIS RELIES ON, both probed against 2.7.0 rather than
assumed, because guessing either one wrong makes the check quietly wrong:
  * `report_check_types -min_pulse_width` WITHOUT `-violators` prints exactly
    one row — the worst check — and prints it whether it reads (MET) or
    (VIOLATED). With `-violators` it prints every violating pin, so it can be
    the LONGER of the two.
  * It EXTRAPOLATES below index_1[0] rather than clamping. A table with fall
    entries 0.09450 / 0.10060 at slews 0.020 / 0.050 returned 0.09043 under an
    ideal clock — the linear extrapolation to slew 0, to five digits.
  * The same probe confirmed the CONVENTION the characterizer asserts:
    rise_constraint is the HIGH phase, fall_constraint the LOW one. A narrow
    high phase was checked against the rise table's extrapolation (0.07970) and
    a wide one reported the low phase against the fall table's (0.09043).

⚠️ TWO WAYS THIS CHECK WAS SILENTLY OPTIMISTIC, both fixed 2026-08-21 and both
the same shape as the defects this repo keeps finding — a check that runs, says
nothing, and is believed:

  * IT RAN NINE CORNERS AGAINST ONE RING. `harden/signoff.sdc` keys ro_clk's
    period on $::env(_CURRENT_CORNER_NAME), which a standalone `sta` does not
    have, so all nine fell back to the globally fastest ring (ff, 1.358 ns).
    That checks the ss library's requirement against an ff-speed ring — slow
    silicon clocked by a fast ring, which cannot happen on a die, since the
    ring is built from the very cells whose requirement is under test. M14's
    phantom-violation shape. The corner name is now exported.
  * IT READ THE TABLE AT ZERO SLEW. min_pulse_width is indexed by the clock's
    own transition, and an ideal clock has none. Without `set_propagated_clock`
    OpenSTA took the extrapolation to slew 0 — the most optimistic entry in the
    table, and the one number no pin on this die sees. Measured on tt: 90.6 ps
    at zero slew against 150.9 ps at the 195.3 ps slew really present at the
    prescaler's CLK pin. Emitting a slew-indexed table (the whole point of M19
    over a scalar) and then reading it at slew 0 gives back the scalar.

Both are now asserted, not assumed: the run dies if the SDC logs its fallback,
and dies if the largest requirement applied is no bigger than the zero-slew
value the table itself predicts.

⚠️ THE SIGNOFF SDC, NOT THE PNR SDC. `ro_clk` is deliberately absent from the
PNR SDC (CTS would build a clock tree on a ring oscillator), so the run's
`final/sdc` declares only `clk` and would report a clean bill of health while
never looking at the ring at all. This reads `harden/signoff.sdc`, which is
where `ro_clk` is constrained per corner.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/librelane/librelane:3.0.5"

PVTS = ["tt_025C_1v80", "ss_100C_1v60", "ff_n40C_1v95"]
RCS = ["min", "nom", "max"]

# "cap/CLK (high)   0.11333   0.05000   -0.06333 (VIOLATED)"
ROW = re.compile(
    r"^\s*(\S+)\s+\((high|low)\)\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)", re.M)

# Every values() row inside a min_pulse_width constraint, so the control
# run can inflate them without touching any other table.
MPW_VALUES = re.compile(r'((?:rise|fall)_constraint \(mpw\d+\) \{[^}]*?values\()"([\d., ]+)"')

# `set_propagated_clock` IS LOAD-BEARING, and leaving it out was a defect.
# min_pulse_width is indexed by the CLOCK's own transition -- that is the whole
# reason lib-v1.7 emits a slew-indexed TABLE instead of the scalar setup and
# hold beside it. An IDEAL clock has no transition, so without this line
# OpenSTA reads the table extrapolated to ZERO SLEW, which is its most
# optimistic entry, and the check quietly enforces the one number in the table
# that no pin on the die actually sees. Measured on the tt library: the low
# phase asks 90.6 ps at zero slew and 150.9 ps at the 195.3 ps slew really
# present at the prescaler's CLK pin -- 1.67x thrown away. Propagating also
# makes the ACTUAL width the routed one rather than the SDC's nominal, which is
# why the control used to report every pin at exactly 679.0 ps.
TCL = """read_liberty {lib}
read_verilog {netlist}
link_design {top}
read_spef {spef}
read_sdc {sdc}
set_propagated_clock [all_clocks]
puts "@@@ALL"
report_check_types -min_pulse_width -digits 5
puts "@@@VIOLATORS"
report_check_types -min_pulse_width -violators -digits 5
puts "@@@DONE"
"""


# The DFF's min_pulse_width table, so the script can compute what a ZERO-slew
# read would have returned and refuse to accept one.
MPW_TABLE = re.compile(
    r'timing_type\s*:\s*min_pulse_width;.*?'
    r'rise_constraint\s*\([^)]*\)\s*\{\s*index_1\("([^"]*)"\);\s*values\("([^"]*)"\)'
    r'.*?fall_constraint\s*\([^)]*\)\s*\{\s*index_1\("[^"]*"\);\s*values\("([^"]*)"\)',
    re.S)


def zero_slew_floor(lib_text: str):
    """What the requirement would read at slew 0, i.e. with an ideal clock.

    Returned as (high, low) in ns. Linear extrapolation below index_1[0] is
    what a table lookup does there; if the tool clamps instead it returns
    index_1[0]'s value, which is larger -- so using the extrapolation as the
    floor is the conservative choice for the assertion below.
    """
    m = MPW_TABLE.search(lib_text)
    if not m:
        sys.exit("ERROR: could not parse the DFF min_pulse_width table out of "
                 "the liberty, so the ideal-clock guard cannot run. Refusing "
                 "to check without it.")
    idx = [float(x) for x in m.group(1).split(",")]
    out = []
    for grp in (2, 3):
        v = [float(x) for x in m.group(grp).split(",")]
        slope = (v[1] - v[0]) / (idx[1] - idx[0])
        out.append(v[0] - slope * idx[0])
    return out[0], out[1]


def newest_run(runs_dir: Path) -> Path:
    cands = [p for p in runs_dir.iterdir()
             if p.is_dir() and (p / "final" / "nl").is_dir()]
    if not cands:
        sys.exit(f"ERROR: no run with final/nl under '{runs_dir}' — nothing to "
                 f"check. This script asserts a property of a BUILT design; it "
                 f"must not pass when there is no design.")
    return max(cands, key=lambda p: p.stat().st_mtime)


# harden/signoff.sdc picks ro_clk's period out of a PER-CORNER table keyed on
# $::env(_CURRENT_CORNER_NAME) -- the variable LibreLane exports around its own
# STA steps. A standalone `sta` does not have it, and the SDC then falls back
# to the globally fastest ring (ff, 1.358 ns) for EVERY corner. That fallback
# is deliberately pessimistic and is right for a lost corner, but it is wrong
# as a steady state here: it checks the ss library's requirement against an
# ff-speed ring, i.e. slow silicon clocked by a fast ring -- a combination that
# cannot occur on a die, because the ring is built from the very cells whose
# requirement is being checked. It is M14's phantom-violation shape (there, a
# tt-period constraint on an ss counter produced 5 setup violations that were
# not real) and M10's shape (nine views wearing three labels). The corner name
# is exported so the nine corners are nine corners.
def sta_cmd(work: Path, script: str, corner: str):
    env = dict(os.environ, _CURRENT_CORNER_NAME=corner)
    if shutil.which("sta"):
        return ["sta", "-no_init", "-exit", script], env
    if shutil.which("docker"):
        return (["docker", "run", "--rm", "-e", f"_CURRENT_CORNER_NAME={corner}",
                 "-v", f"{work}:/w", "-w", "/w",
                 IMAGE, "sta", "-no_init", "-exit", script], env)
    sys.exit("ERROR: neither `sta` nor `docker` on PATH — cannot run the "
             "min-pulse-width check. Refusing to report a pass without having "
             "run it.")


# "signoff.sdc: corner 'max_ss_100C_1v60' -> ro_clk period 2.166 ns"
SDC_CORNER = re.compile(r"signoff\.sdc: corner '([^']*)' -> ro_clk period "
                        r"([\d.]+) ns")


def ring_period(log: str, corner: str) -> float:
    """The ro_clk period the SDC actually applied, or die trying.

    Without this the check would still RUN on a mis-resolved corner and report
    a confident number about the wrong ring. Every failure this repo has found
    was a check that ran and said nothing; a silent fallback here would be the
    next one.
    """
    m = SDC_CORNER.search(log)
    if not m:
        sys.exit(f"ERROR: {corner}: harden/signoff.sdc did not resolve the "
                 f"corner — it logged its fallback instead, so ro_clk was "
                 f"constrained at the globally fastest ring rather than this "
                 f"corner's. Refusing to report a min-pulse-width result "
                 f"against the wrong ring.")
    if m.group(1) != corner:
        sys.exit(f"ERROR: {corner}: signoff.sdc resolved '{m.group(1)}' "
                 f"instead. The corner name is not reaching the SDC.")
    return float(m.group(2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="?", default="runs")
    ap.add_argument("--lib-dir", default=str(ROOT / "lib"))
    ap.add_argument("--sdc", default=str(ROOT / "harden" / "signoff.sdc"))
    args = ap.parse_args()

    run = newest_run(Path(args.runs))
    final = run / "final"
    libdir = Path(args.lib_dir)
    netlist = next((final / "nl").glob("*.nl.v"))
    top = netlist.name.replace(".nl.v", "")

    work = ROOT / "out" / "mpw_check"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(netlist, work / netlist.name)
    shutil.copyfile(args.sdc, work / "signoff.sdc")

    # A liberty with no min_pulse_width makes this check silent rather than
    # failing, which is exactly defect M19. Refuse to run in that state.
    missing = []
    for pvt in PVTS:
        lib = libdir / f"own_hardening_{pvt}.lib"
        if not lib.exists():
            sys.exit(f"ERROR: {lib} not found — is lib/ populated?")
        if "min_pulse_width" not in lib.read_text():
            missing.append(lib.name)
        shutil.copyfile(lib, work / lib.name)
    if missing:
        print("MIN-PULSE-WIDTH CHECK CANNOT RUN — defect M19:")
        for n in missing:
            print(f"  - {n} declares no min_pulse_width on any cell")
        print("  OpenSTA would report an empty violator list however narrow "
              "the clock pulse got. Re-pin to a stdcells release that measures "
              "it (lib-v1.7 or later).")
        return 1

    violations, margins, checked = [], [], 0
    for pvt in PVTS:
        for rc in RCS:
            spefs = list((final / "spef" / rc).glob("*.spef"))
            if not spefs:
                sys.exit(f"ERROR: no SPEF under final/spef/{rc} — the check "
                         f"needs real parasitics, since the requirement is "
                         f"indexed by the clock's transition.")
            corner = f"{rc}_{pvt}"
            shutil.copyfile(spefs[0], work / f"{corner}.spef")
            (work / f"{corner}.tcl").write_text(TCL.format(
                lib=f"own_hardening_{pvt}.lib", netlist=netlist.name,
                top=top, spef=f"{corner}.spef", sdc="signoff.sdc"))
            cmd, env = sta_cmd(work, f"{corner}.tcl", corner)
            cp = subprocess.run(cmd, cwd=work, env=env,
                                capture_output=True, text=True)
            log = cp.stdout + cp.stderr
            (work / f"{corner}.log").write_text(log)
            if "@@@DONE" not in log:
                print(log[-3000:])
                sys.exit(f"ERROR: OpenSTA did not finish for {corner} — a "
                         f"crashed run is not a clean run.")
            period = ring_period(log, corner)
            checked += 1

            # ⓘ MEASURED against OpenSTA 2.7.0, not assumed. The UNFILTERED
            # report prints exactly ONE row -- the worst min-pulse-width check
            # on the design -- and prints it whether it reads (MET) or
            # (VIOLATED). The `-violators` report prints every violating pin,
            # so it can be LONGER than the unfiltered one. That is the opposite
            # of the obvious guess, and it is load-bearing twice over: the
            # single unfiltered row is exactly the binding margin we want to
            # report, and because it is present even when nothing violates, the
            # "no rows at all" branch below is a real error rather than the
            # normal passing case.
            all_sec = log[log.find("@@@ALL"):log.find("@@@VIOLATORS")]
            vio_sec = log[log.find("@@@VIOLATORS"):]
            all_rows = ROW.findall(all_sec)
            rows = ROW.findall(vio_sec)
            for pin, phase, req, act, slack in rows:
                violations.append((corner, pin, phase, float(req),
                                   float(act), float(slack)))

            # THE IDEAL-CLOCK GUARD. If `set_propagated_clock` silently stops
            # taking effect, every requirement collapses to the table's
            # zero-slew extrapolation and this check goes on printing zeros
            # while enforcing a number no pin on the die sees. That is the
            # exact failure shape of M13/M15/M16/M19, so assert against it
            # rather than trust the line is still there.
            if not all_rows:
                sys.exit(f"ERROR: {corner}: the unfiltered min-pulse-width "
                         f"report listed NO checks at all. It prints the worst "
                         f"check even when that check passes, so with ro_clk "
                         f"constrained and flops in that domain, empty means "
                         f"the check is not running.")
            # ⓘ ALSO MEASURED: OpenSTA EXTRAPOLATES below index_1[0] rather
            # than clamping there. Probed with a spliced-in table whose first
            # two fall entries are 0.09450 / 0.10060 at 0.020 / 0.050 ns; an
            # ideal clock produced a required width of 0.09043, which is the
            # linear extrapolation to slew 0 to five digits, not the 0.09450 a
            # clamp would give. So zero_slew_floor's extrapolation is the right
            # model of the value to refuse, not a conservative stand-in.
            floor_hi, floor_lo = zero_slew_floor(
                (work / f"own_hardening_{pvt}.lib").read_text())
            worst_req = max(float(r[2]) for r in all_rows)
            # The worst row may be either phase, so compare against the LARGER
            # of the two floors: an ideal clock cannot produce a requirement
            # above it, whichever phase happens to bind.
            floor = max(floor_hi, floor_lo)
            if worst_req <= floor * 1.02:
                sys.exit(
                    f"ERROR: {corner}: the largest min_pulse_width requirement "
                    f"OpenSTA applied is {worst_req*1000:.1f} ps, no more than "
                    f"the table's ZERO-SLEW value ({floor*1000:.1f} ps). The "
                    f"clock is being treated as ideal, so the requirement is "
                    f"read at the most optimistic end of the very axis this "
                    f"table exists to express. Check `set_propagated_clock`.")
            slacks = [(float(a) - float(rq), pin, ph)
                      for pin, ph, rq, a, _ in all_rows]
            m_slack, m_pin, m_phase = min(slacks)
            margins.append((corner, m_slack, m_pin, m_phase, worst_req))
            print(f"  {corner}: ro_clk {period:.3f} ns "
                  f"({period/2*1000:.1f} ps per phase), worst check {m_pin} "
                  f"({m_phase}) needs {worst_req*1000:.1f} ps and has "
                  f"{m_slack*1000:+.1f} ps of margin, {len(rows)} violation(s)")

    # ------------------------------------------------------------------
    # POSITIVE CONTROL. "0 violations" is the exact shape of a check that is
    # not looking, and this repo has now shipped four of those (M13, M15, M16
    # and M19 itself). So before believing the zeros, prove this run CAN fail:
    # inflate the requirement past the ring's half period and require that it
    # flags the ring-domain flops. Run at ff, the binding corner -- that is
    # where the ring is fastest and therefore its pulses narrowest.
    control_pvt, control_rc = "ff_n40C_1v95", "max"
    body = (work / f"own_hardening_{control_pvt}.lib").read_text()
    inflated = MPW_VALUES.sub(
        lambda m: m.group(1) + '"' + ", ".join(
            ["9.00000"] * len(m.group(2).split(","))) + '"', body)
    if inflated == body:
        print("\nCONTROL FAILED: could not inflate the min_pulse_width table "
              "-- the emitted shape changed and this control would silently "
              "be doing nothing. Fix MPW_VALUES to match characterize.py.")
        return 1
    (work / "control.lib").write_text(inflated)
    shutil.copyfile(work / f"{control_rc}_{control_pvt}.spef",
                    work / "control.spef")
    (work / "control.tcl").write_text(TCL.format(
        lib="control.lib", netlist=netlist.name, top=top,
        spef="control.spef", sdc="signoff.sdc"))
    control_corner = f"{control_rc}_{control_pvt}"
    cmd, env = sta_cmd(work, "control.tcl", control_corner)
    cp = subprocess.run(cmd, cwd=work, env=env,
                        capture_output=True, text=True)
    clog = cp.stdout + cp.stderr
    (work / "control.log").write_text(clog)
    # Only the VIOLATORS section: the TCL now emits an unfiltered report too,
    # and counting both would double every number this control prints.
    control_rows = ROW.findall(clog[clog.find("@@@VIOLATORS"):])
    if "@@@DONE" not in clog or not control_rows:
        print(clog[-2000:])
        print("\nCONTROL FAILED: inflating min_pulse_width to 9 ns produced no "
              "violation anywhere on this design. The check is INERT and the "
              "zeros above mean nothing. Do not read them as a pass.")
        return 1
    widths = sorted({float(a) for _, _, _, a, _ in control_rows})
    print(f"\ncontrol: a 9 ns requirement flags {len(control_rows)} pin(s) at "
          f"{control_rc}_{control_pvt}, actual width(s) "
          f"{', '.join(f'{w*1000:.1f} ps' for w in widths)} -- so the check "
          f"reaches the ring domain and is capable of failing")

    print(f"\nchecked {checked} corners against "
          f"{Path(args.sdc).name} (the SIGNOFF sdc, which is where ro_clk is)")
    if violations:
        print("\nMIN-PULSE-WIDTH VIOLATIONS — defect M19's failure mode:")
        for corner, pin, phase, req, act, slack in violations:
            print(f"  {corner:22s} {pin} ({phase}) needs {req*1000:.1f} ps, "
                  f"gets {act*1000:.1f} ps, slack {slack*1000:+.1f} ps")
        print("\n⛔ Do NOT fix this by widening the SDC period or dropping the "
              "constraint. A clock pulse the flop cannot capture on is a "
              "counter that does not count.")
        return 1
    # Quote a RATIO, not a picosecond count -- M6's lesson in this repo: the
    # ring and the flop are built from the same cells, so what survives a
    # process shift is the ratio between them, not a slack figure.
    corner, m_slack, m_pin, m_phase, _ = min(margins, key=lambda r: r[1])
    print()
    print(f"binding margin: {m_slack*1000:+.1f} ps at {m_pin} "
          f"({m_phase}) in {corner}")
    print("PASS: every clock pulse on this die is wider than the library's "
          "measured min_pulse_width, at all nine corners.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
