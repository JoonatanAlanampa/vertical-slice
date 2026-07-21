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
# once real cells carry real delays — gate-level simulation against the
# characterized library, and then silicon.

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# Gate-level runs replace every stage delay with the flow's UNIT_DELAY,
# so the modelled ring frequency below does not apply — there we only
# check that each ring runs and is counted.
GL = os.environ.get("GATES") == "yes"

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


@cocotb.test()
async def test_ro_counts(dut):
    """Every flavor's ring is counted, and the count means what we claim."""
    await start(dut)

    counts = {}
    for sel in (SEL_INV, SEL_NAND2, SEL_NOR2):
        n = await measure(dut, sel)
        f_mhz = n * (2 ** PRE) / (WINDOW_NS * 1e-9) / 1e6
        dut._log.info("%-5s ring: count=%d  -> %.1f MHz (model %.1f MHz)",
                      FLAVOR[sel], n, f_mhz, 1e3 / RING_PERIOD_NS)
        assert abs(n - EXPECTED) / EXPECTED < 0.05, \
            f"{FLAVOR[sel]}: count {n}, expected ~{EXPECTED:.0f}"
        counts[sel] = n

    # same modelled stage delay -> the three must agree to a quantisation
    # step; a real difference here would be an instrument bug, not physics
    if not GL:
        assert max(counts.values()) - min(counts.values()) <= 1, counts


@cocotb.test()
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


@cocotb.test()
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
