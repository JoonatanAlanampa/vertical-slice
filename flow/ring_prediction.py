"""What our own timing model says the rings will do in silicon.

This is the last prediction that exists before the die does. It reads the
post-P&R SDF — delays OpenSTA computed from our own Liberty arcs, across
our own extracted parasitics — and turns each ring into the two numbers
bring-up will actually compare against: an oscillation frequency, and the
count the on-chip instrument should report.

A ring's period is one full loop for the rising edge plus one for the
falling edge, so it is the sum of BOTH transition delays over every stage:

    T = sum_stages(t_plh + t_phl)          f = 1 / T

    python flow/ring_prediction.py <sdf-dir-or-file> [...]

Point it at harden/runs/*/final/sdf (all-own) or at the reference build's
SDF to compare the two libraries on the same structure.
"""

import re
import statistics as st
import sys
from pathlib import Path

STAGES = 31
PRE = 8                      # ro_meas PRE_BITS
WIN = {"short": 12, "long": 20}
CLK_HZ = 25e6                # the ship clock

# stage composition per ring: the INV ring is 30 inverters + the NAND2 that
# gates it; the other two are homogeneous
COMPOSITION = {
    "INV":   {"INV_X1": STAGES - 1, "NAND2_X1": 1},
    "NAND2": {"NAND2_X1": STAGES},
    "NOR2":  {"NOR2_X1": STAGES},
}


def ring_of(inst):
    for key, name in (("u_ro_inv", "INV"), ("u_ro_nand2", "NAND2"),
                      ("u_ro_nor2", "NOR2")):
        if key in inst:
            return name
    return None


def parse(sdf_path):
    """-> {(ring, celltype): [delays...]} using every IOPATH transition."""
    text = sdf_path.read_text()
    out = {}
    # SDF writes "(CELL\n (CELLTYPE ...", so the split must not expect a space
    for block in re.split(r"\n\s*\(CELL\b", text)[1:]:
        m = re.search(r'\(CELLTYPE "(\w+)"\)\s*\(INSTANCE ([^\n]*?)\)', block)
        if not m:
            continue
        celltype, inst = m.group(1), m.group(2)
        if "u_stage" not in inst:
            continue
        ring = ring_of(inst)
        if ring is None:
            continue
        # ONLY the arc the oscillation actually travels. Every stage takes
        # the previous stage on A; B is the enable leg, tied to its inactive
        # constant inside the chain, so B->Y is never in the loop. Averaging
        # both arcs (the first version of this script did) skews a NAND2
        # ring's predicted frequency by tens of percent.
        for io in re.finditer(r"\(IOPATH (\w+) (\w+) (.*)", block):
            if io.group(1) != "A":
                continue
            ds = [float(d) for d in re.findall(r"\(([\d.]+):", io.group(3))]
            if not ds:
                continue
            # one triple means rise and fall are the same number
            rise, fall = (ds + ds)[:2]
            r_list, f_list = out.setdefault((ring, celltype), ([], []))
            r_list.append(rise)
            f_list.append(fall)
    return out


def report(sdf_path):
    per = parse(sdf_path)
    if not per:
        print(f"  {sdf_path.name}: no ring cells found")
        return

    print(f"\n{sdf_path.parent.name}")
    print(f"  {'ring':<7}{'stage cell':<11}{'t_plh':>8}{'t_phl':>8}"
          f"{'period':>10}{'f_ring':>11}{'count/short':>13}")

    for ring, comp in COMPOSITION.items():
        period_ns = 0.0
        rows = []
        for celltype, n in comp.items():
            arcs = per.get((ring, celltype))
            if not arcs:
                continue
            rise, fall = arcs
            period_ns += n * (st.mean(rise) + st.mean(fall))
            rows.append((celltype, n, st.mean(rise) * 1000, st.mean(fall) * 1000))
        if not rows:
            continue
        f_hz = 1e9 / period_ns
        # what the on-chip counter reports: prescaled edges in the window
        count = f_hz / 2 ** PRE * (2 ** WIN["short"] / CLK_HZ)
        first = True
        for celltype, n, tr, tf in rows:
            if first:
                print(f"  {ring:<7}{celltype+f' x{n}':<11}{tr:>7.1f}p{tf:>7.1f}p"
                      f"{period_ns:>9.3f}n{f_hz/1e6:>9.1f}M{count:>13.0f}")
                first = False
            else:
                print(f"  {'':<7}{celltype+f' x{n}':<11}{tr:>7.1f}p{tf:>7.1f}p")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    files = []
    for a in args:
        p = Path(a)
        files.extend(sorted(p.rglob("*.sdf")) if p.is_dir() else [p])
    if not files:
        sys.exit("no .sdf found")

    for f in files:
        report(f)

    print("\nNote: a count is per SHORT window (2**12 clocks at 25 MHz); the "
          "long window is 2**20, i.e. 256x these numbers.")


if __name__ == "__main__":
    main()
