# Windows-friendly alternative to the Makefile (no `make` required):
#   python run.py            # both suites
#   python run.py ro         # ring-oscillator test structures only
#   python run.py sine       # sine (CORDIC-1) smoke tests only
# Runs the same RTL simulation via cocotb's Python runner.

import sys
from pathlib import Path

from cocotb_tools.runner import get_runner

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"

SOURCES = [
    SRC_DIR / "project.sv",
    SRC_DIR / "cordic.sv",
    SRC_DIR / "ro_meas.sv",
    SRC_DIR / "ro_ring.sv",
    TEST_DIR / "tb.v",
]

SUITES = {"ro": "test_ro", "sine": "test_sine"}


def main():
    which = sys.argv[1:] or list(SUITES)
    modules = [SUITES[w] for w in which]

    runner = get_runner("icarus")
    runner.build(
        sources=SOURCES,
        hdl_toplevel="tb",
        build_dir=TEST_DIR / "sim_build" / "rtl",
        build_args=["-g2012", f"-I{SRC_DIR}"],
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="tb",
        test_module=",".join(modules),
        test_dir=TEST_DIR,
    )


if __name__ == "__main__":
    main()
