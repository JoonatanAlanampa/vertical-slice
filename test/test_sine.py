# SPDX-FileCopyrightText: © 2026 Joonatan Alanampa
# SPDX-License-Identifier: Apache-2.0
#
# Smoke test for the sine half of the chip: this RTL is the fabricated
# CORDIC-1 (TTSKY26c, commit b646d057), vendored unchanged, so the full
# verification lives in that repo (exhaustive 65,536-angle engine check,
# FFT harmonic check, SymbiYosys control-path proof). What has to be
# re-proven HERE is only that the mode strap and the read-out mux did not
# disturb it.

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLK_NS = 40
FS = 25e6 / 359                  # constant-time bit-serial conversion rate


async def reset(dut, ui):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = ui
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1


async def measure_hz(dut, cycles):
    """Frequency via sign flips of the LED bar MSB (uo[5])."""
    flips = 0
    prev = (int(dut.uo_out.value) >> 5) & 1
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        cur = (int(dut.uo_out.value) >> 5) & 1
        if cur != prev:
            flips += 1
        prev = cur
    return flips / 2 / (cycles * CLK_NS * 1e-9)


@cocotb.test()
async def test_wakeup_440(dut):
    """Untouched pins = the 440 Hz wake-up tone, exactly as fabricated."""
    await reset(dut, ui=0)
    await ClockCycles(dut.clk, 4000)

    f = await measure_hz(dut, 300_000)      # ~5 periods of 440 Hz
    assert abs(f - 440) / 440 < 0.12, f
    dut._log.info("wake-up tone: measured %.1f Hz (target 440)", f)


@cocotb.test()
async def test_code64_and_sigma_delta(dut):
    """A mid-range code, and the sigma-delta density it rides on."""
    await reset(dut, ui=64)
    await ClockCycles(dut.clk, 4000)

    f = await measure_hz(dut, 60_000)
    f_exp = 64 * 1024 / 2**20 * FS          # ~4.48 kHz
    assert abs(f - f_exp) / f_exp < 0.1, (f, f_exp)

    ones = 0
    m = 46_000                              # ~8 full periods at code 64
    for _ in range(m):
        await RisingEdge(dut.clk)
        ones += (int(dut.uo_out.value) >> 7) & 1
    assert 0.45 < ones / m < 0.55, ones / m
    dut._log.info("code 64: %.1f Hz (expected %.1f), sigma-delta density %.3f",
                  f, f_exp, ones / m)


@cocotb.test(skip=os.environ.get("GATES") == "yes")   # hierarchical probe
async def test_rings_are_dark_in_sine_mode(dut):
    """ui[7]=0 must keep the test structures switched off.

    The rings would otherwise burn power and inject supply noise straight
    into the analog output — the whole point of gating them on the strap.
    """
    await reset(dut, ui=(1 << 4) | 1)       # RO run + INV select, but ui[7]=0
    await ClockCycles(dut.clk, 2000)

    assert dut.user_project.u_ro_meas.st.value == 0, "RO FSM ran in sine mode"
    assert dut.user_project.u_ro_meas.ring_en.value == 0, "a ring was enabled in sine mode"
