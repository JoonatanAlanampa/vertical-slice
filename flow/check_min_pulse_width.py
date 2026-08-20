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

⚠️ THE SIGNOFF SDC, NOT THE PNR SDC. `ro_clk` is deliberately absent from the
PNR SDC (CTS would build a clock tree on a ring oscillator), so the run's
`final/sdc` declares only `clk` and would report a clean bill of health while
never looking at the ring at all. This reads `harden/signoff.sdc`, which is
where `ro_clk` is constrained per corner.
"""

import argparse
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

TCL = """read_liberty {lib}
read_verilog {netlist}
link_design {top}
read_spef {spef}
read_sdc {sdc}
report_check_types -min_pulse_width -violators -digits 5
puts "@@@DONE"
"""


def newest_run(runs_dir: Path) -> Path:
    cands = [p for p in runs_dir.iterdir()
             if p.is_dir() and (p / "final" / "nl").is_dir()]
    if not cands:
        sys.exit(f"ERROR: no run with final/nl under '{runs_dir}' — nothing to "
                 f"check. This script asserts a property of a BUILT design; it "
                 f"must not pass when there is no design.")
    return max(cands, key=lambda p: p.stat().st_mtime)


def sta_cmd(work: Path, script: str):
    if shutil.which("sta"):
        return ["sta", "-no_init", "-exit", script]
    if shutil.which("docker"):
        return ["docker", "run", "--rm", "-v", f"{work}:/w", "-w", "/w",
                IMAGE, "sta", "-no_init", "-exit", script]
    sys.exit("ERROR: neither `sta` nor `docker` on PATH — cannot run the "
             "min-pulse-width check. Refusing to report a pass without having "
             "run it.")


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

    violations, checked = [], 0
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
            cp = subprocess.run(sta_cmd(work, f"{corner}.tcl"), cwd=work,
                                capture_output=True, text=True)
            log = cp.stdout + cp.stderr
            (work / f"{corner}.log").write_text(log)
            if "@@@DONE" not in log:
                print(log[-3000:])
                sys.exit(f"ERROR: OpenSTA did not finish for {corner} — a "
                         f"crashed run is not a clean run.")
            checked += 1
            rows = ROW.findall(log)
            for pin, phase, req, act, slack in rows:
                violations.append((corner, pin, phase, float(req),
                                   float(act), float(slack)))
            print(f"  {corner}: {len(rows)} min-pulse-width violation(s)")

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
    cp = subprocess.run(sta_cmd(work, "control.tcl"), cwd=work,
                        capture_output=True, text=True)
    clog = cp.stdout + cp.stderr
    (work / "control.log").write_text(clog)
    control_rows = ROW.findall(clog)
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
    print("PASS: every clock pulse on this die is wider than the library's "
          "measured min_pulse_width, at all nine corners.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
