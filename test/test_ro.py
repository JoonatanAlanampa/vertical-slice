# SPDX-FileCopyrightText: © 2026 Joonatan Alanampa
# SPDX-License-Identifier: Apache-2.0
#
# Ring-oscillator test structures: the read-out path end to end.
#
# In RTL simulation the rings are behavioural chains with a lumped
# STAGE_DLY per stage, so all three flavors oscillate at the SAME
# modelled period (2 * STAGES * STAGE_DLY). That is deliberate: these
# tests prove the instrument (select -> warm-up -> window -> latch ->
# byte mux) reports the frequency it is shown. The flavors only diverge
# once real cells carry real delays, which happens in silicon — see the
# GL note below for why gate-level simulation is not a middle step.

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# A RING OSCILLATOR CANNOT BE GATE-LEVEL SIMULATED HERE, and running one
# does not fail — it HANGS. sky130's FUNCTIONAL cell models are plain
# `not`/`buf` primitives with no delay (UNIT_DELAY is only applied to the
# sequential cells), so the ring becomes a zero-delay combinational loop
# and the simulator spins forever at a single timestamp. Measured: a
# gl_test job burned 2 h before it was killed.
#
# So under GATES the tests that enable a ring are skipped, and only the
# paths that keep every ring dark run. Timing a ring needs delays that
# exist in exactly two places: an SDF-annotated run, and silicon. Silicon
# is the point of the chip.
GL = os.environ.get("GATES") == "yes"

# ...unless the delays are REAL. run_gl_own.py annotates post-P&R SDF onto
# the all-own netlist, which is the one configuration where a ring both
# oscillates and means something: the frequency is then our own timing
# model's prediction for silicon. There the counts are checked against that
# prediction instead of against the RTL stand-in.
GL_OWN = os.environ.get("GL_OWN") == "yes"
NO_RINGS = cocotb.test(skip=GL and not GL_OWN)

CLK_NS = 40                    # 25 MHz, the ship clock
STAGES = 31                    # ro_ring default
STAGE_DLY_NS = 0.1             # ro_ring default
PRE = 8                        # ro_meas PRE_BITS
WIN_SHORT = 12                 # ro_meas WIN_SHORT (2**12 system clocks)
WARM = 256                     # ro_meas WARM

RING_PERIOD_NS = 2 * STAGES * STAGE_DLY_NS          # 6.2 ns -> 161 MHz
WINDOW_NS = (2 ** WIN_SHORT) * CLK_NS               # 163.84 us
EXPECTED = WINDOW_NS / RING_PERIOD_NS / (2 ** PRE)  # ~103 prescaled edges

TEST_MODE = 1 << 7
RUN = 1 << 4

SEL_OFF, SEL_INV, SEL_NAND2, SEL_NOR2 = 0, 1, 2, 3
FLAVOR = {SEL_INV: "INV", SEL_NAND2: "NAND2", SEL_NOR2: "NOR2"}


def sdf_prediction():
    """Counts our own timing model expects, per ring, for a short window."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flow"))
    import statistics as st

    from ring_prediction import COMPOSITION, parse

    per = parse(Path(os.environ["SDF_PATH"]))
    out = {}
    for ring, comp in COMPOSITION.items():
        period_ns = 0.0
        for celltype, n in comp.items():
            arcs = per.get((ring, celltype))
            if not arcs:
                break
            period_ns += n * (st.mean(arcs[0]) + st.mean(arcs[1]))
        else:
            f_hz = 1e9 / period_ns
            out[ring] = f_hz / 2 ** PRE * (2 ** WIN_SHORT / (1e9 / CLK_NS))
    return out


def ctrl(sel, byte_sel=0, run=False, win_long=False):
    return (TEST_MODE | sel | (byte_sel << 2)
            | (RUN if run else 0) | ((1 << 5) if win_long else 0))


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = ctrl(SEL_OFF)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def read_byte(dut, sel, byte_sel, run=False):
    """Point the read-out mux at one byte and sample it."""
    dut.ui_in.value = ctrl(sel, byte_sel, run=run)
    await ClockCycles(dut.clk, 2)      # combinational, but settle the wave
    return int(dut.uo_out.value)


async def measure(dut, sel):
    """Run one short-window measurement and return the 24-bit count."""
    dut.ui_in.value = ctrl(sel, byte_sel=3, run=True)

    # busy goes high within a couple of cycles, then the window runs
    await ClockCycles(dut.clk, 4)
    assert int(dut.uo_out.value) & 0b01, "busy never asserted"

    # drop run just before the window closes: `run` is a level, so leaving
    # it high would re-arm the FSM the instant it returns to idle
    await ClockCycles(dut.clk, WARM + 2 ** WIN_SHORT - 16)
    dut.ui_in.value = ctrl(sel, byte_sel=3, run=False)
    await ClockCycles(dut.clk, 32)

    status = int(dut.uo_out.value)
    assert status & 0b10, "valid never asserted"
    assert (status & 0b01) == 0, "still busy after the window closed"

    lo = await read_byte(dut, sel, 0)
    mid = await read_byte(dut, sel, 1)
    hi = await read_byte(dut, sel, 2)
    return lo | (mid << 8) | (hi << 16)


@cocotb.test()
async def test_ro_off(dut):
    """sel = 0 keeps every ring dark: no run, no count."""
    await start(dut)
    dut.ui_in.value = ctrl(SEL_OFF, byte_sel=3, run=True)
    await ClockCycles(dut.clk, WARM + 64)

    status = int(dut.uo_out.value)
    assert (status & 0b11) == 0, f"FSM started with no ring selected: {status:#04x}"

    for byte_sel in (0, 1, 2):
        assert await read_byte(dut, SEL_OFF, byte_sel, run=True) == 0


@NO_RINGS
async def test_ro_counts(dut):
    """Every flavor's ring is counted, and the count means what we claim."""
    await start(dut)

    predicted = sdf_prediction() if GL_OWN else None
    if predicted:
        dut._log.info("own-library prediction (counts/short window): %s",
                      {k: round(v) for k, v in predicted.items()})

    counts = {}
    for sel in (SEL_INV, SEL_NAND2, SEL_NOR2):
        n = await measure(dut, sel)
        f_mhz = n * (2 ** PRE) / (WINDOW_NS * 1e-9) / 1e6
        dut._log.info("%-5s ring: count=%d  -> %.1f MHz (model %.1f MHz)",
                      FLAVOR[sel], n, f_mhz, 1e3 / RING_PERIOD_NS)
        # With SDF annotated, the yardstick is our own timing model's
        # prediction for this flavor; in RTL it is the uniform stand-in.
        exp = predicted[FLAVOR[sel]] if predicted else EXPECTED
        tol = 0.10 if predicted else 0.05
        assert abs(n - exp) / exp < tol, \
            f"{FLAVOR[sel]}: count {n}, expected ~{exp:.0f} " \
            f"({'own.lib prediction' if predicted else 'RTL model'})"
        counts[sel] = n

    if predicted:
        # REAL delays: the flavors must separate, and in the order our own
        # characterization says they do. This is the differential signal the
        # three-ring design exists to produce.
        order = sorted(counts, key=lambda s: -counts[s])
        want = sorted(FLAVOR, key=lambda s: -predicted[FLAVOR[s]])
        assert order == want, (
            f"flavor ordering disagrees with own.lib: measured "
            f"{[FLAVOR[s] for s in order]}, predicted {[FLAVOR[s] for s in want]}")
        dut._log.info("flavor ordering matches own.lib: %s",
                      " > ".join(FLAVOR[s] for s in order))
    else:
        # same modelled stage delay -> the three must agree to a quantisation
        # step; a difference here would be an instrument bug, not physics
        assert max(counts.values()) - min(counts.values()) <= 1, counts


@NO_RINGS
async def test_readout_mux(dut):
    """The byte mux addresses the latched count, and status reports state."""
    await start(dut)
    n = await measure(dut, SEL_INV)

    assert await read_byte(dut, SEL_INV, 0) == n & 0xFF
    assert await read_byte(dut, SEL_INV, 1) == (n >> 8) & 0xFF
    assert await read_byte(dut, SEL_INV, 2) == (n >> 16) & 0xFF

    status = await read_byte(dut, SEL_INV, 3)
    assert (status & 0b01) == 0, "still busy after the window closed"
    assert status & 0b10, "valid dropped"
    assert (status & 0b0011_1100) == 0, f"status reserved bits set: {status:#04x}"


@NO_RINGS
async def test_repeat_and_mode_mux(dut):
    """run held high repeats the measurement; ui[7]=0 returns the sine."""
    await start(dut)
    first = await measure(dut, SEL_NAND2)

    # hold run high across two full windows: the second overwrites the first
    dut.ui_in.value = ctrl(SEL_NAND2, byte_sel=3, run=True)
    await ClockCycles(dut.clk, 2 * (WARM + 2 ** WIN_SHORT) + 16)
    dut.ui_in.value = ctrl(SEL_NAND2, byte_sel=3, run=False)
    await ClockCycles(dut.clk, 4)
    second = ((await read_byte(dut, SEL_NAND2, 2)) << 16 |
              (await read_byte(dut, SEL_NAND2, 1)) << 8 |
              (await read_byte(dut, SEL_NAND2, 0)))
    assert abs(second - first) <= 1, (first, second)

    # leaving test mode must hand the pins straight back to the sine engine
    dut.ui_in.value = 0                       # sine mode, code 0 (440 Hz)
    await ClockCycles(dut.clk, 4)

    # the sigma-delta bit must actually move once the engine is fed
    seen = set()
    for _ in range(2000):
        await RisingEdge(dut.clk)
        seen.add((int(dut.uo_out.value) >> 7) & 1)
    assert seen == {0, 1}, "sine mode did not restore the sigma-delta output"
    dut._log.info("mode mux: RO count %d in test mode, sine live in sine mode", first)
