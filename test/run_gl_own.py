"""Simulate the ALL-OWN netlist with post-P&R SDF back-annotated.

The last prediction before silicon: the real placed-and-routed netlist,
delays from our own Liberty arcs through our own parasitics, running the
real read-out protocol. It answers the question the RTL tests cannot —
what the on-chip counter will actually report — and it is the only way to
simulate a ring oscillator at all (zero delay = a loop that spins forever
at one timestamp).

    python test/run_gl_own.py <run-dir> [corner]

<run-dir> is a hardening run directory (harden/runs/RUN_...) or anything
containing final/nl/*.nl.v and final/sdf/<corner>/*.sdf — e.g. an
unpacked `hardening-run` CI artifact. Corner defaults to nom_tt_025C_1v80.
"""

import os
import subprocess
import sys
from pathlib import Path

from cocotb_tools.runner import get_runner

TEST_DIR = Path(__file__).parent
ROOT = TEST_DIR.parent

CORNER = "nom_tt_025C_1v80"


def find(run_dir: Path, corner: str):
    nl = sorted(run_dir.rglob("final/nl/*.nl.v"))
    sdf = sorted(run_dir.rglob(f"final/sdf/{corner}/*.sdf"))
    if not nl:
        sys.exit(f"no final/nl/*.nl.v under {run_dir}")
    if not sdf:
        sys.exit(f"no final/sdf/{corner}/*.sdf under {run_dir}")
    return nl[-1], sdf[-1]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run_dir = Path(sys.argv[1])
    corner = sys.argv[2] if len(sys.argv) > 2 else CORNER
    netlist, sdf = find(run_dir, corner)
    print(f"netlist : {netlist}")
    print(f"sdf     : {sdf}")

    # Icarus cannot annotate a flat netlist's escaped instance names — it
    # splits them on the divider and finds no such scope, leaving every ring
    # cell on its model default. Rewrite both files so no name has a dot.
    sys.path.insert(0, str(ROOT / "flow"))
    from sdf_sanitize import sanitize_netlist, sanitize_sdf
    sane = TEST_DIR / "sim_build" / "gl_own" / "sane"
    sane.mkdir(parents=True, exist_ok=True)
    (sane / netlist.name).write_text(sanitize_netlist(netlist.read_text()))
    (sane / sdf.name).write_text(sanitize_sdf(sdf.read_text()))
    netlist, sdf = sane / netlist.name, sane / sdf.name

    # forward-slashed absolute path: the string is pasted into Verilog source
    sdf_arg = str(sdf.resolve()).replace("\\", "/")

    build_dir = TEST_DIR / "sim_build" / "gl_own"
    build_dir.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "sim" / "own_cells.v", netlist, TEST_DIR / "tb_gl.v"]

    # -gspecify is NOT optional: without it icarus discards every specify
    # block, silently skips $sdf_annotate, and the netlist runs at zero
    # delay — at which point the rings are a combinational loop that spins
    # forever at a single timestamp, eating memory until something dies
    # (measured: 22 GB). The runner does not surface icarus' warnings, so a
    # throwaway compile runs first purely to read them.
    probe = subprocess.run(
        ["iverilog", "-o", str(build_dir / "probe.vvp"), "-s", "tb",
         "-g2012", "-gspecify", "-Ttyp", f'-DSDF_FILE="{sdf_arg}"',
         *[str(s) for s in sources]],
        capture_output=True, text=True)
    if probe.returncode != 0:
        print(probe.stdout + probe.stderr)
        sys.exit("iverilog failed")
    if "Omitting $sdf_annotate" in probe.stdout + probe.stderr:
        sys.exit("REFUSING TO RUN: specify blocks were dropped, so the SDF "
                 "would not be annotated and the rings would hang. This is "
                 "the -gspecify failure mode; see PLAN.md phase 4.")
    (build_dir / "probe.vvp").unlink(missing_ok=True)
    print("specify blocks kept; SDF will be annotated")

    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="tb",
        build_dir=build_dir,
        build_args=["-g2012", "-gspecify", "-Ttyp", f'-DSDF_FILE="{sdf_arg}"'],
        timescale=("1ns", "1ps"),
    )
    runner.test(hdl_toplevel="tb", test_module="test_ro", test_dir=TEST_DIR,
                extra_env={"GL_OWN": "yes", "CORNER": corner,
                           "SDF_PATH": str(sdf.resolve())})


if __name__ == "__main__":
    main()
