# SPDX-FileCopyrightText: © 2026 Joonatan Alanampa
# SPDX-License-Identifier: Apache-2.0
#
# Smoke test for the sine half of the chip: this RTL is the fabricated
# CORDIC-1 (TTSKY26c, commit b646d057), vendored unchanged, so the full
# verification lives in that repo (exhaustive 65,536-angle engine check,
# FFT harmonic check, SymbiYosys control-path proof). What has to be
# re-proven HERE is only that the mode strap and the read-out mux did not
# disturb it.

import math
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


# Samples per period of the wake-up tone, from the RTL constant rather than
# from the measurement: project.sv sets dds_inc = 6625 for code 0 and phase is
# 20 bits, so one period is 2**20 / 6625 conversions. Fitting the period too
# would let a frequency error hide inside the shape fit; frequency already has
# its own test above.
SAMPLES_PER_PERIOD = 2 ** 20 / 6625          # 158.2757
CONV_CLOCKS = 359                            # one bit-serial conversion


@cocotb.test()
async def test_sine_waveform_shape(dut):
    """The engine's output SHAPE -- on whatever netlist is under test.

    WHY THIS EXISTS, and why it has no skip guard. The two tests above measure
    the DDS rate and the sigma-delta's one-density. Neither constrains the
    WAVEFORM: a triangle, a square, or a CORDIC with one mis-mapped iteration
    all produce the same tone frequency and the same ~0.5 density. So on the
    netlist that actually ships, the ~2,700 cells of engine -- which is the
    stated function of the chip and all but a hundred of its cells -- were
    asserted only to be "periodic and zero-mean". `test_rings_are_dark_in_sine
    _mode` is skipped under GATES because it needs a hierarchical probe; this
    one must NOT be, and does not need one.

    `uo[5:1]` is `sin_s[15:11] ^ 5'b10000` (project.sv) -- the top five bits of
    the engine result in offset binary, already routed to a pin. So the shape
    is observable at gate level directly.

    THE THRESHOLDS ARE MEASURED, NOT CHOSEN. Least-squares fit of
    A*sin(2*pi*k/N + phi) + c over 170 samples, with N fixed by the RTL:

        this RTL          max |residual| = 0.795 LSB  (rms 0.32)
        a TRIANGLE of identical amplitude and phase   3.36 LSB
        a SQUARE   of identical amplitude and phase  15.92 LSB

    1.5 LSB passes the real waveform with ~2x margin and rejects a triangle
    with ~2x margin the other way. The residual floor is quantization: a 5-bit
    sample of a full-scale sine cannot do better than +/-0.5.

    Amplitude and offset are fitted as nuisance parameters -- the assertion is
    about SHAPE -- so they are pinned separately below, or a half-amplitude
    engine would fit a half-amplitude sine perfectly and pass.
    """
    import numpy as np

    await reset(dut, ui=0)
    await ClockCycles(dut.clk, 4000)         # let the pipeline fill

    n = 170                                  # ~1.07 periods; 61k clocks total
    s = []
    for _ in range(n):
        await ClockCycles(dut.clk, CONV_CLOCKS)
        s.append(((int(dut.uo_out.value) >> 1) & 0x1F) - 16)

    w = 2 * math.pi * np.arange(n) / SAMPLES_PER_PERIOD
    basis = np.stack([np.sin(w), np.cos(w), np.ones(n)], axis=1)
    (a, b, c), *_ = np.linalg.lstsq(basis, np.array(s, dtype=float), rcond=None)
    amp = math.hypot(a, b)
    resid = np.array(s, dtype=float) - basis @ np.array([a, b, c])
    worst = float(np.max(np.abs(resid)))

    dut._log.info("sine fit: amplitude %.2f codes, offset %+.2f, "
                  "max residual %.2f LSB (rms %.2f), p2p %d",
                  amp, c, worst, float(np.std(resid)), max(s) - min(s))

    assert worst <= 1.5, (
        f"output deviates from a sine by {worst:.2f} LSB -- a triangle would "
        f"give ~3.4, a square ~15.9. Fit: amp {amp:.2f}, offset {c:+.2f}")
    assert amp >= 15.0, f"amplitude collapsed to {amp:.2f} codes (expect ~16)"
    assert max(s) - min(s) == 31, (
        f"peak-to-peak {max(s) - min(s)} of 31 -- the engine is not reaching "
        f"full scale, or a top bit is stuck")
    assert abs(c + 0.5) <= 1.0, (
        f"DC offset {c:+.2f}; two's-complement truncation of a symmetric sine "
        f"should sit at -0.5")
