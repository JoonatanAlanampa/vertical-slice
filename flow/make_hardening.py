"""Build the ALL-OWN gate-level netlist: this chip, zero foundry content.

Synthesis happens here (locally, reproducibly) and the netlist is committed,
so the CI hardening job does place-and-route only — the same split the
stdcells repo used, for the same reason: P&R is the slow, flaky half, and
it should never be re-deciding what the logic is.

Ported from stdcells flow/make_hardening.py at tag lib-v1.0, with three
differences that matter here:

  * `-DUSE_OWN_CELLS` — the ring-oscillator stages become INV_X1 / NAND2_X1
    / NOR2_X1 INSTANCES rather than logic to be mapped. read_liberty must
    therefore come first, so those cells exist before elaboration.
  * the rings are audited afterwards: 93 stage cells must survive, in the
    exact flavor mix the test structures claim to measure. This is the
    check that caught two silent collapses already.
  * the netlist is audited for `sky130_` content. TIE_X1 in lib-v1.0 means
    even the tie cells are ours, so the correct number is zero.

    python flow/make_hardening.py

Outputs harden/vslice_gates.v. Requires lib/ (see tools/fetch_lib.py).
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LIB = ROOT / "lib"
HARDEN = ROOT / "harden"
TOP = "tt_um_joonatanalanampa_vslice"

STAGES = 31          # keep in step with ro_ring.sv / ro_meas.sv
RINGS = 3

# What the three rings must look like in the netlist afterwards. The INV
# ring is 30 inverters plus the NAND2 that gates it, so the NAND2 total is
# one more than a homogeneous ring's.
EXPECT_RING = {
    "INV_X1":   STAGES - 1,
    "NAND2_X1": STAGES + 1,
    "NOR2_X1":  STAGES,
}


def yosys(script: str, name: str) -> str:
    HARDEN.mkdir(exist_ok=True)
    sf = HARDEN / f"{name}.ys"
    sf.write_text(script)
    p = subprocess.run(["yosys", "-s", str(sf)], capture_output=True, text=True)
    log = p.stdout + p.stderr
    (HARDEN / f"{name}.log").write_text(log)
    if p.returncode != 0:
        print(log[-4000:])
        sys.exit(f"ERROR: yosys failed ({name}); see harden/{name}.log")
    return log


def main():
    for f in ("own_hardening.lib", "own_abc.lib"):
        if not (LIB / f).exists():
            sys.exit(f"ERROR: lib/{f} missing — run tools/fetch_lib.py first")

    netlist = HARDEN / "vslice_gates.v"
    script = f"""
read_liberty -lib "{LIB / 'own_hardening.lib'}"
read_verilog -sv -DUSE_OWN_CELLS "{SRC / 'cordic.sv'}" "{SRC / 'ro_ring.sv'}" \
             "{SRC / 'ro_meas.sv'}" "{SRC / 'project.sv'}"
hierarchy -top {TOP}
flatten
synth -top {TOP}
dfflegalize -cell $_DFF_P_ x
dfflibmap -liberty "{LIB / 'own_hardening.lib'}"
abc -liberty "{LIB / 'own_abc.lib'}"
opt_clean -purge
hilomap -hicell TIE_X1 HI -locell TIE_X1 LO
insbuf -buf BUF_X2 A Y
stat
write_verilog -noattr -nohex -nodec "{netlist}"
"""
    log = yosys(script, "synth_own")

    # Parse only the LAST stat block: `synth` prints an intermediate one full
    # of $_XOR_/$_SDFF* gates that have not met ABC yet. Mistaking that
    # phantom for the result cost the stdcells session a whole debugging pass.
    last = log[log.rfind("Printing statistics"):]
    counts = {}
    for m in re.finditer(r"^\s+(\d+)\s+(\S+)\s*$", last, re.M):
        name = m.group(2)
        # yosys' stat block also carries pseudo-rows (wires, ports, memories);
        # only real cell names get through
        if not name.startswith("$") and ("_X" in name or name.startswith("sky130")):
            counts[name] = counts.get(name, 0) + int(m.group(1))

    own = {k: v for k, v in counts.items() if not k.startswith("sky130")}
    foundry = {k: v for k, v in counts.items() if k.startswith("sky130")}

    # cell areas straight out of the pinned liberty — the same numbers the
    # placer will use, so this estimate and the flow cannot drift apart
    lib_txt = (LIB / "own_hardening.lib").read_text()
    areas = {m.group(1): float(m.group(2)) for m in re.finditer(
        r"cell \((\w+)\)\s*\{[^}]*?area\s*:\s*([\d.]+)", lib_txt, re.S)}

    print(f"\n{'cell':<14}{'count':>8}{'area um2':>12}")
    total_area = 0.0
    for k in sorted(own, key=lambda k: -own[k]):
        a = areas.get(k, 0.0) * own[k]
        total_area += a
        print(f"{k:<14}{own[k]:>8}{a:>12.1f}")
    print(f"{'TOTAL':<14}{sum(own.values()):>8}{total_area:>12.1f}")

    # TT core areas at the margin settings that won the stdcells 1x1
    # experiment (TOP/BOTTOM 1, LEFT/RIGHT 2); utilization here is
    # pre-P&R, so it excludes the clock tree, hold buffers and fill
    for tile, core in (("1x1", 16900.0), ("1x2", 34255.4)):
        print(f"  {tile}: {total_area / core:6.1%} of a {core:,.0f} um2 core "
              f"(logic only, before CTS/hold/fill)")

    # ---- audit 1: zero foundry content ------------------------------------
    if foundry:
        sys.exit(f"\nERROR: foundry cells in an all-own netlist: {foundry}")
    print("\nzero-foundry: OK (no sky130_ cells)")

    # ---- audit 2: the rings survived, in the right flavors -----------------
    # Counting instances in the netlist rather than trusting the stat block:
    # the stat totals include every other use of INV_X1/NAND2_X1 in the
    # design, so only the ring instance paths can answer this.
    text = netlist.read_text()
    ring_cells = {}
    for m in re.finditer(r"^\s*(\w+)\s+(\\?\S*u_ro_\w+[^ ]*)\s*\(", text, re.M):
        cell, inst = m.group(1), m.group(2)
        if "u_stage" in inst:
            ring_cells[cell] = ring_cells.get(cell, 0) + 1

    if ring_cells != EXPECT_RING:
        sys.exit(f"\nERROR: ring stages wrong.\n  expected {EXPECT_RING}"
                 f"\n  found    {ring_cells}\n"
                 "  (a collapsed ring measures nothing — see PLAN.md phase 0)")
    total = sum(ring_cells.values())
    print(f"rings: OK ({total} stage cells = {RINGS} x {STAGES}) {ring_cells}")
    print(f"\nnetlist -> {netlist.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
