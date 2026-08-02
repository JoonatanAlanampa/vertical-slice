"""Acceptance test for the corner-aware re-pin (lib-v1.1): the timing corners
must actually differ.

vertical-slice hardens out of the pinned stdcells release. Under lib-v1.0 the
single nominal own_hardening.lib went in via EXTRA_LIBS, which LibreLane loads
for every timing corner -- so all STA corners and all SDF files were
byte-identical, and run_gl_own.py's [corner] argument produced the same
ring-oscillator prediction at tt/ss/ff. lib-v1.1 fetches per-corner hardening
libs and feeds them through the corner-keyed LIB dict in harden/config.json.

This asserts the property rather than trusting the config, in two steps:
  1. the per-corner hardening libs fetched into lib/ really carry different
     numbers (cheap, runs anywhere), and
  2. given a hardening run dir, the SDF written per corner differs too -- the
     only proof the corner-keyed LIB actually reached OpenROAD rather than
     being silently overridden by the nominal EXTRA_LIBS.

Usage:  python flow/check_corner_spread.py [<harden/runs/*/ dir>]
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib"
NUM = re.compile(r"-?\d+\.\d+")


def lib_fingerprint(path):
    """All NLDM table values in a liberty file, as a tuple."""
    vals = []
    for m in re.finditer(r"values\(([^;]*)\)", path.read_text(), re.S):
        vals.extend(float(x) for x in NUM.findall(m.group(1)))
    return tuple(vals)


def main():
    libs = sorted(LIB.glob("own_hardening_*C_*v*.lib"))
    if len(libs) < 2:
        sys.exit("FAIL: fewer than two per-corner hardening libs in lib/ — run "
                 "`python tools/fetch_lib.py` against a lib-v1.1+ pin first")

    print(f"per-corner hardening libs ({len(libs)}):")
    fps = {}
    for p in libs:
        fp = lib_fingerprint(p)
        fps[p.name] = fp
        print(f"  {p.name:<40s} {len(fp):5d} table values")
    if not any(fps.values()):
        sys.exit("FAIL: no table values parsed")

    names = list(fps)
    sizes = {len(v) for v in fps.values()}
    if len(sizes) != 1:
        sys.exit(f"FAIL: corner libs have different shapes {sizes} — they must "
                 "describe the same cells and tables")

    identical = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                 if fps[a] == fps[b]]
    if identical:
        sys.exit(f"FAIL: byte-identical timing in {identical} — this is exactly "
                 "the single-PVT bug the lib-v1.1 re-pin exists to fix")

    base = names[0]
    worst = 0.0
    for n in names[1:]:
        rel = max(abs(y / x - 1) for x, y in zip(fps[base], fps[n]) if x)
        worst = max(worst, rel)
        print(f"  max |{n} / {base} - 1| = {100 * rel:.1f}%")
    if worst < 0.05:
        sys.exit(f"FAIL: corner spread is only {100 * worst:.2f}% — suspiciously "
                 "small for tt/ss/ff; are all three really different models?")
    print(f"PASS: liberty corners differ, worst-case spread {100 * worst:.0f}%")

    # ---------------------------------------------------------------- SDF
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if run_dir is None:
        print("\n(no run directory given — skipping the SDF check)")
        return
    sdfs = sorted(run_dir.rglob("*.sdf"))
    if not sdfs:
        sys.exit(f"FAIL: no SDF files under {run_dir}")
    digests = {}
    for s in sdfs:
        digests.setdefault(s.read_bytes(), []).append(s.name)
    print(f"\nSDF: {len(sdfs)} files, {len(digests)} distinct")
    for names_ in digests.values():
        print(f"  {len(names_)}x  {names_[0]}")
    if len(digests) < 2:
        sys.exit("FAIL: every SDF corner is byte-identical — the corner-keyed "
                 "LIB did not reach OpenROAD (a nominal EXTRA_LIBS overriding "
                 "it would look exactly like this)")

    # ---- byte-difference is NOT enough (found 2026-08-02) -----------------
    # The submitted build's per-corner SDFs are not byte-identical and this
    # check passed for eleven days — but they differ in only 28 of 34110
    # lines, and those are the (VOLTAGE)/(TEMPERATURE) header plus a handful
    # of INTERCONNECT arcs on the clk/rst_n input ports. Every own-CELL delay
    # was identical at ff(-40C,1.95V) and ss(100C,1.60V), which is impossible
    # for real corner-aware STA. A header is not a timing model, so compare
    # the delays themselves.
    by_corner = {}
    for s in sdfs:
        txt = s.read_text(errors="replace")
        key = s.parent.name
        vals = [float(v) for v in
                re.findall(r"\(IOPATH \w+ \w+ \(([\d.]+):", txt)]
        if vals:
            by_corner.setdefault(key, vals)
    pvt = {}
    for corner, vals in by_corner.items():
        m = re.search(r"(ff_n40C_1v95|tt_025C_1v80|ss_100C_1v60)", corner)
        if m:
            pvt.setdefault(m.group(1), []).append((corner, vals))
    if len(pvt) < 2:
        print("  (fewer than two PVT views found — skipping the delay check)")
        return
    # The metric is the FRACTION of arcs that move, not the largest single
    # move. Between ff(-40C,1.95V) and ss(100C,1.60V) essentially every cell
    # delay must change; a handful of outliers passing a max-delta test is
    # what let this through (measured: 11 of 4884 arcs differ, max 12.4%, and
    # a max-based threshold called that a pass).
    print("\nIOPATH delay content per PVT view:")
    ref_name, ref = sorted(pvt.items())[0][0], sorted(pvt.items())[0][1][0][1]
    worst_frac = 1.0
    for name, entries in sorted(pvt.items()):
        if name == ref_name:
            continue
        vals = entries[0][1]
        n = min(len(vals), len(ref))
        diff = sum(1 for a, b in zip(ref[:n], vals[:n]) if a != b)
        rel = max((abs(b / a - 1) for a, b in zip(ref[:n], vals[:n]) if a), default=0.0)
        frac = diff / max(n, 1)
        worst_frac = min(worst_frac, frac)
        print(f"  {name:<16} {n:5d} arcs, {diff:5d} differ from {ref_name} "
              f"({100 * frac:5.1f}%), max delta {100 * rel:6.1f}%")
    if worst_frac < 0.50:
        sys.exit(
            f"FAIL: only {100 * worst_frac:.1f}% of cell delay arcs change between "
            "PVT views. Real corner-aware STA moves essentially all of them, so "
            "this build is effectively SINGLE-CORNER — the per-corner SDFs differ "
            "little more than their VOLTAGE/TEMPERATURE header. The nominal "
            "own_hardening.lib supplied via EXTRA_LIBS is the timing that reached "
            "every corner, not the corner-keyed LIB. See READINESS.md M10.")
    print(f"PASS: real corner spread ({100 * worst_frac:.0f}% of arcs move "
          f"between PVT views)")


if __name__ == "__main__":
    main()
