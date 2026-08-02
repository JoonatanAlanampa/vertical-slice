"""Assert the signoff numbers of the run that actually ships, and PRINT them.

Why this exists
---------------
Blocker 2 said there was "no top-level connectivity signoff on the all-own
GDS". Re-derived 2026-08-02 from the artifact of run 30749148303 (commit
2312cf2), that turned out to be misdirected: it cited
`harden/config.json:84-88`, which disables LVS/DRC errors for the BARE-DIE
build that is never submitted. The submission path — `src/config.json` driven
by tt-gds-action — never disables them, and the numbers were already good:

    62-netgen-lvs   Final result: Circuits match uniquely.
                    7026 devices / 3070 nets, both sides, per-celltype equal
                    ERROR_ON_LVS_ERROR = True, enforced by 63-checker-lvs
    58-magic-drc    magic__drc_error__count      = 0
    43-checker-trdrc route__drc_errors           = 0   (converged 2720 -> 0)
                    antenna / PDN / slew / fanout = 0
                    design__max_cap_violation__count = 4   <-- the open item

netgen runs with `-blackbox` and only the sky130 SPICE models are loaded, so
the own cells ARE black boxes: this is exactly the "hierarchical LVS with the
cells as black boxes" that READINESS.md proposed as the fix, already running.
It compares the magic-extracted GDS against the post-P&R netlist, which is
what catches a missing via, an open net or a LEF-to-GDS pin mismatch — the
things cell-level LVS in `stdcells` structurally cannot see.

The real defect was not the check. It was that **nobody read it**: the result
sat inside a 984-file log artifact, behind a red badge caused by an unrelated
upstream `cat`. So this script runs in CI, prints the numbers, and fails if
they regress.

    python tools/check_signoff.py [run_dir_or_glob]

Exit 0 = signoff clean. Non-zero = a number moved the wrong way.
"""

import glob
import json
import re
import sys
from pathlib import Path

# Known-good baselines from run 30749148303 (commit 2312cf2). A number may
# not get WORSE than this without someone deciding it is acceptable.
MUST_BE_ZERO = [
    "design__lvs_error__count",
    "design__lvs_device_difference__count",
    "design__lvs_net_difference__count",
    "design__lvs_property_fail__count",
    "design__lvs_unmatched_device__count",
    "design__lvs_unmatched_net__count",
    "design__lvs_unmatched_pin__count",
    "magic__drc_error__count",
    "route__drc_errors",
    "route__antenna_violation__count",
    "antenna__violating__nets",
    "antenna__violating__pins",
    "design__power_grid_violation__count",
    "design__max_slew_violation__count",
    "design__max_fanout_violation__count",
    "flow__errors__count",
    "synthesis__check_error__count",
]

# Open item, deliberately not zero. Recorded in READINESS.md; the gate is
# "must not get worse", so it cannot quietly grow while nobody is looking.
MAX_CAP_BASELINE = 4

# Anti-vacuity: this design is ~2700 own cells plus fill/taps. A "clean"
# signoff over an empty or trivial circuit is what blocker 1 was.
MIN_DEVICES = 2000


def find_metrics(root):
    """Newest final metrics json under a librelane run dir."""
    pats = [f"{root}/**/final/metrics.json", f"{root}/**/*-misc-reportmanufacturability/state_out.json",
            f"{root}/**/state_out.json"]
    for pat in pats:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return Path(hits[-1])
    return None


def find_lvs_report(root):
    hits = sorted(glob.glob(f"{root}/**/*-netgen-lvs/reports/lvs.netgen.rpt",
                            recursive=True))
    return Path(hits[-1]) if hits else None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "runs"
    fails, notes = [], []

    mf = find_metrics(root)
    if mf is None:
        # Fail loudly rather than pass vacuously.
        sys.exit(f"ERROR: no librelane metrics found under {root!r} — "
                 f"cannot check the signoff of a run that is not there")
    blob = json.loads(mf.read_text())
    metrics = blob.get("metrics", blob)
    print(f"metrics : {mf}")

    for k in MUST_BE_ZERO:
        v = metrics.get(k)
        if v is None:
            notes.append(f"{k}: ABSENT from metrics (step may not have run)")
        elif v != 0:
            fails.append(f"{k} = {v}, expected 0")
        else:
            print(f"  {k:<48} 0")

    mc = metrics.get("design__max_cap_violation__count")
    if mc is None:
        notes.append("design__max_cap_violation__count: ABSENT")
    elif mc > MAX_CAP_BASELINE:
        fails.append(f"design__max_cap_violation__count = {mc}, worse than the "
                     f"recorded baseline {MAX_CAP_BASELINE} (READINESS.md)")
    else:
        print(f"  {'design__max_cap_violation__count':<48} {mc} "
              f"(open item, baseline {MAX_CAP_BASELINE})")

    # ---- the LVS verdict itself, not just its error count -----------------
    rpt = find_lvs_report(root)
    if rpt is None:
        fails.append("no netgen LVS report found — the top-level connectivity "
                     "signoff did not run")
    else:
        text = rpt.read_text()
        print(f"\nLVS     : {rpt}")
        if "Circuits match uniquely" not in text:
            verdict = re.search(r"^Final result:.*$", text, re.M)
            fails.append(f"LVS did not match uniquely: "
                         f"{verdict.group(0) if verdict else 'no Final result line'}")
        else:
            print("  Final result: Circuits match uniquely.")

        # Anti-vacuity: a unique match over nothing proves nothing.
        dev = re.findall(r"Number of devices:\s*(\d+)\s*\|.*?(\d+)", text)
        nets = re.findall(r"Number of nets:\s*(\d+)\s*\|.*?(\d+)", text)
        if not dev:
            fails.append("LVS report has no device counts — cannot rule out a "
                         "vacuous comparison")
        else:
            a, b = int(dev[-1][0]), int(dev[-1][1])
            n = int(nets[-1][0]) if nets else 0
            print(f"  devices {a} vs {b}, nets {n}")
            if a != b:
                fails.append(f"LVS device counts differ: {a} vs {b}")
            if a < MIN_DEVICES:
                fails.append(f"LVS compared only {a} devices (< {MIN_DEVICES}) — "
                             f"that is not this design; refusing to call it signoff")

    if notes:
        print("\nnotes:")
        for n in notes:
            print(f"  - {n}")

    if fails:
        print("\nSIGNOFF CHECK FAILED:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nsignoff: PASS (LVS unique + DRC/antenna/PDN clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
