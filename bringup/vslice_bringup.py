# SPDX-FileCopyrightText: © 2026 Joonatan Alanampa
# SPDX-License-Identifier: Apache-2.0
"""
Vertical-slice silicon bring-up — MicroPython for the TinyTapeout demo board.

This is the script the whole project has been aiming at. Every number below
was predicted by our own device physics, our own characterizer and our own
signoff STA; none of them has ever been checked against a thing that exists.
Copy this to the demo board's filesystem and:

    >>> import vslice_bringup as bu
    >>> bu.main()            # instrument self-check, then THE measurement
    >>> bu.measure_rings()   # just the ring frequencies, as a table
    >>> bu.sweep_supply()    # ring frequency vs core voltage, if adjustable

What is being proven, in order:

  1. heartbeat   uo[0] = bit 23 of a free counter -> f = clk / 2**24. Measuring
                 it recovers the clock the die really sees, and EVERY ring
                 frequency below is computed from that, never from the clock we
                 asked the RP2040 PWM for.
  2. instrument  the read-out path itself: a dark ring reports zero, a running
                 one sets busy then valid, and the short and long windows agree.
                 A broken instrument must not be mistaken for surprising physics.
  3. THE RINGS   one frequency per cell flavor, which is one propagation delay
                 per cell, measured on silicon at the real supply and
                 temperature:

                     f_ring = count * 2**PRE * f_clk / 2**WINDOW
                     tp     = 1 / (2 * STAGES * f_ring)

A measured value that disagrees with the prediction is NOT a failure — it is
the result. The script says so explicitly, and reports the ratio rather than a
verdict. What it does fail on is an instrument that cannot be trusted to have
measured anything.

The demo-board API shim is lifted from tt-cordic/bringup/cordic1_bringup.py,
where it was verified against tt-micropython-firmware v2.0.0 (commit f34d9f0,
microcotb 81f2498). Constants come from src/ro_meas.sv and src/project.sv;
predictions come from flow/ring_prediction.py.

PREDICTED_HZ and PREDICTED_BAND_HZ below are ASSERTED against a fresh
computation by flow/check_ring_doc.py on every gds run. This used to say
"Keep them in sync" -- a human instruction, which is exactly the mechanism
defect M21 was: the numbers went stale by two library generations and
nothing noticed, because nothing looked.
"""

import time

try:
    from machine import Pin
except ImportError:  # pragma: no cover - lets the file be imported on a host
    Pin = None

# ---------------------------------------------------------------- design facts
DESIGN = "tt_um_joonatanalanampa_vslice"
CLK_HZ = 25_000_000        # info.yaml clock_hz
BEAT_BIT = 23              # heartbeat = beat[23] -> period 2**24 clocks

STAGES = 31                # ro_ring
PRE = 8                    # ro_meas PRE_BITS
WIN_SHORT = 12             # ro_meas WIN_SHORT
WIN_LONG = 20              # ro_meas WIN_LONG
WARM = 256                 # ro_meas WARM

MODE_TEST = 1 << 7         # ui[7]
UI_RUN = 1 << 4            # ui[4]
UI_WIN_LONG = 1 << 5       # ui[5]

SEL = {"INV": 1, "NAND2": 2, "NOR2": 3}
ORDER = ("INV", "NAND2", "NOR2")

BYTE_LO, BYTE_MID, BYTE_HI, BYTE_STATUS = 0, 1, 2, 3
ST_BUSY, ST_VALID = 0x01, 0x02

# What our own timing model says (flow/ring_prediction.py --run, all-own
# netlist, run 32564385882 on lib-v2.1). Nominal is tt/25C/1.80V; the
# corner band is what a room-temperature part is allowed to land in.
#
# Updated 2026-08-03 (M7 closed). The previous values (914.1 / 658.3 /
# 411.7 MHz) were the raw SDF sums and were 32-46% OPTIMISTIC, for three
# reasons that are all properties of the SDF rather than of the chip:
#   1. OpenSTA breaks the ring's combinational loop, so one stage per ring
#      reports zero. For the INV ring that stage is its lone NAND2 — the
#      most expensive one — so it was 4.5% short, not 3%.
#   2. The ring nets carry NO interconnect in the SDF (0.000 everywhere,
#      while ordinary nets in the same file carry 1-2 ps). The parasitics
#      exist in final/spef and are worth 0.10-1.57 fF (mean 0.53) of extra
#      load on a 2.62-2.70 fF pin cap, i.e. 4-58 %.
#   3. Every inverting cell's delay was computed at an input slew of ZERO,
#      because the library's transition tables are negative for inverting
#      cells and OpenSTA clamps them (M11). These numbers instead solve the
#      ring's own fixed point, where input slew = previous stage's output
#      slew, landing at 16.8-118.6 ps -- all INTERIOR to the NLDM grid,
#      which starts at 10 ps as of lib-v2.0 (stdcells M27).
# Before 2026-08-02 the table said 442.7 / 359.2 / 252.1 MHz, which was a
# prediction of a DIFFERENT circuit: a stray BUF_X2 then hung off every ring
# node (H3, fixed).
PREDICTED_HZ = {"INV": 455.4e6, "NAND2": 323.6e6, "NOR2": 225.3e6}

# ff(-40C,1.95V) .. ss(100C,1.60V), same model. A part measured at room
# temperature landing outside this is the interesting result, not an error.
PREDICTED_BAND_HZ = {"INV": (319.2e6, 560.4e6),
                     "NAND2": (215.9e6, 416.8e6),
                     "NOR2": (155.7e6, 284.5e6)}


def ring_hz(count, clk_hz, win_bits):
    """Ring frequency from a counter reading. The clock cancels no further:
    every term here is either an on-chip constant or the measured clock."""
    return count * (1 << PRE) * clk_hz / (1 << win_bits)


def stage_delay_s(f_ring, ring="NAND2", f_nand2=None):
    """One cell's propagation delay from a ring frequency.

    Exact for the NAND2 and NOR2 rings, which are homogeneous 31-stage
    chains. NOT exact for the INV ring: an odd-stage ring needs its enable
    gate somewhere, and here it is stage 0, so that ring is 30 INV_X1 + 1
    NAND2_X1 (src/ro_ring.sv). Dividing its period by 2*STAGES returns a
    30:1 BLEND of the two cells, biased +1.16 % (ff) / +1.38 % (tt) /
    +1.62 % (ss) -- one-signed, and larger than the RC band the datasheet
    publishes. De-blend it with the NAND2 ring, which measures that stage
    directly:  tp_INV = (1/f_INV - 1/(31*f_NAND2)) / 60.

    Returns None for INV when no NAND2 reading is available, rather than
    silently handing back the blend: this number is the chip's output.
    """
    if not f_ring:
        return None
    if ring == "INV":
        if not f_nand2:
            return None
        return (1.0 / f_ring - 1.0 / (STAGES * f_nand2)) / (2.0 * (STAGES - 1))
    return 1.0 / (2.0 * STAGES * f_ring)


# ------------------------------------------------------- demo-board API shim
# Verified against tt-micropython-firmware v2.0.0; see the module docstring.
# Firmware facts this depends on:
#   * DemoBoard.get() is the singleton accessor; a second DemoBoard() raises.
#   * tt.ui_in / tt.uo_out are microcotb IO ports, not ints: read with int(),
#     write with .value. port[i] is a Logic BIT, LSB-indexed — NOT a pin.
#   * entering ASIC_RP_CONTROL leaves any ui_in pin already reading HIGH as an
#     INPUT (contention guard): a DIP switch left on silently vetoes that bit.
#   * clock_project_PWM() retunes the RP2040 system clock and settles for a
#     nearby frequency — which is why the heartbeat is the clock reference.


class Board:
    def __init__(self, tt):
        self.tt = tt

    @classmethod
    def open(cls):
        from ttboard.demoboard import DemoBoard

        try:
            tt = DemoBoard.get()
        except AttributeError:
            tt = DemoBoard()
        self = cls(tt)
        self._take_control()
        return self

    def _take_control(self):
        try:
            from ttboard.mode import RPMode

            self.tt.mode = RPMode.ASIC_RP_CONTROL
        except Exception as e:  # noqa: BLE001 - firmware variance is expected
            log("note: could not set ASIC_RP_CONTROL (%s);" % e)
            log("      set the input DIP switches by hand if writes do not take")

    def select(self, name=DESIGN):
        shuttle = self.tt.shuttle
        proj = None
        try:
            if shuttle.has(name):
                proj = shuttle.get(name)
        except AttributeError:
            pass
        if proj is None:
            proj = getattr(shuttle, name, None)
        if proj is None and hasattr(shuttle, "find"):
            hits = shuttle.find(name)
            proj = hits[0] if hits else None
        if proj is None:
            raise RuntimeError(
                "%s not found on this shuttle — is the firmware's shuttle "
                "index up to date?" % name
            )
        proj.enable()
        return proj

    def clock(self, hz):
        self.tt.clock_project_PWM(hz)

    def reset_pulse(self, settle_ms=5):
        self.tt.reset_project(True)
        time.sleep_ms(settle_ms)
        self.tt.reset_project(False)
        time.sleep_ms(settle_ms)

    def set_ui(self, value):
        """Write ui_in and return what the pins actually read back."""
        try:
            self.tt.ui_in.value = value
        except AttributeError:
            self.tt.input_byte = value
        return self.get_ui()

    def get_ui(self):
        try:
            return int(self.tt.ui_in)
        except (TypeError, AttributeError):
            try:
                return int(self.tt.ui_in.value)
            except AttributeError:
                return int(self.tt.input_byte)

    def get_uo(self):
        try:
            return int(self.tt.uo_out)
        except (TypeError, AttributeError):
            try:
                return int(self.tt.uo_out.value)
            except AttributeError:
                return int(self.tt.output_byte)


# ---------------------------------------------------------------- measurement


def measure_byte_hz(board, bit, window_ms, settle_ms=0):
    """Frequency of one output bit by polling the whole output byte."""
    if settle_ms:
        time.sleep_ms(settle_ms)
    mask = 1 << bit
    t0 = time.ticks_us()
    prev = board.get_uo() & mask
    edges = 0
    first = last = None
    while time.ticks_diff(time.ticks_us(), t0) < window_ms * 1000:
        cur = board.get_uo() & mask
        if cur != prev:
            last = time.ticks_us()
            if first is None:
                first = last
            edges += 1
            prev = cur
    # first-to-last edge, not the whole window: the window ends mid-period and
    # at ~1.5 Hz that truncation alone is a 10% error
    if edges < 2 or first is None or last == first:
        return None
    span = time.ticks_diff(last, first) / 1e6
    return (edges - 1) / 2.0 / span


def ctrl(sel=0, byte_sel=0, run=False, long_window=False):
    return (MODE_TEST | sel | (byte_sel << 2)
            | (UI_RUN if run else 0) | (UI_WIN_LONG if long_window else 0))


def read_byte(board, sel, byte_sel, run=False, long_window=False):
    board.set_ui(ctrl(sel, byte_sel, run, long_window))
    return board.get_uo()


def run_measurement(board, ring, long_window=False, clk_hz=CLK_HZ):
    """One windowed measurement. Returns (count, status) or (None, status).

    Mirrors the sequence the cocotb tests use: raise RUN, wait out warm-up plus
    the window, drop RUN before reading — `run` is a level, so leaving it high
    re-arms the FSM the instant it goes idle and the count could change under
    the read.
    """
    sel = SEL[ring]
    win_bits = WIN_LONG if long_window else WIN_SHORT
    # generous: the window is (2**win + WARM) clocks, plus firmware latency
    wait_ms = int(1000.0 * (2 ** win_bits + WARM) / clk_hz) + 5

    board.set_ui(ctrl(sel, BYTE_STATUS, run=True, long_window=long_window))
    time.sleep_ms(wait_ms)
    status = board.get_uo()

    board.set_ui(ctrl(sel, BYTE_STATUS, run=False, long_window=long_window))
    time.sleep_ms(wait_ms)          # let any in-flight window finish
    status = board.get_uo()
    if not status & ST_VALID:
        return None, status

    # keep ui[5] as it was: the byte mux must not disturb the window
    # selection, or a re-armed FSM would measure with the other window
    lo = read_byte(board, sel, BYTE_LO, long_window=long_window)
    mid = read_byte(board, sel, BYTE_MID, long_window=long_window)
    hi = read_byte(board, sel, BYTE_HI, long_window=long_window)
    return lo | (mid << 8) | (hi << 16), status


# ------------------------------------------------------------------- checks

_results = []
_skipped = []


def log(msg):
    print(msg)


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    log("  [%s] %-26s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def skip(name, why):
    _skipped.append((name, why))
    log("  [SKIP] %-26s %s" % (name, why))


def check_ui_drive(board):
    """Can the RP2040 drive the control pins at all?

    The firmware refuses to take over a ui_in pin already reading HIGH — a DIP
    switch left on silently vetoes that bit, and every measurement below would
    then be wrong for a reason that has nothing to do with the die.
    """
    stuck = 0
    for bit in range(8):
        want = 1 << bit
        got = board.set_ui(want)
        if got is not None and got != want:
            stuck |= got ^ want
    board.set_ui(0)
    return check(
        "ui_in drive", stuck == 0,
        "all 8 control pins follow" if not stuck else
        "pins %s will not follow — DIP switch left on? (mask 0x%02X)"
        % ([b for b in range(8) if stuck >> b & 1], stuck),
    )


def check_heartbeat(board):
    """Proof of life, and the clock reference everything else uses."""
    board.set_ui(0)                       # sine mode: rings dark, beat visible
    f = measure_byte_hz(board, 0, window_ms=3000, settle_ms=50)
    if f is None:
        check("heartbeat", False, "uo[0] never toggles — is the design selected?")
        return None
    clk = f * (1 << (BEAT_BIT + 1))
    check("heartbeat", True, "%.3f Hz -> clock %.3f MHz" % (f, clk / 1e6))
    return clk


def check_instrument(board, clk_hz):
    """The read-out path, before believing anything it reports."""
    board.set_ui(ctrl(0, BYTE_STATUS, run=True))    # sel = 0: nothing selected
    time.sleep_ms(20)
    status = board.get_uo()
    ok_idle = not status & (ST_BUSY | ST_VALID)
    check("dark ring reports idle", ok_idle,
          "status 0x%02X with no ring selected" % status)

    count, status = run_measurement(board, "INV", clk_hz=clk_hz)
    check("valid after a window", count is not None,
          "status 0x%02X" % status if count is None else
          "count %d, status 0x%02X" % (count, status))
    return count is not None


def measure_ring(board, ring, clk_hz, long_window=True):
    win_bits = WIN_LONG if long_window else WIN_SHORT
    count, status = run_measurement(board, ring, long_window, clk_hz)
    if count is None:
        return None
    if count == 0:
        return 0.0
    return ring_hz(count, clk_hz, win_bits)


def check_window_agreement(board, clk_hz, ring="INV", tol=0.02):
    """Short and long windows must agree — they share only the ring.

    A prescaler that miscounts, a synchronizer that misses edges or a window
    timer that is off by a factor shows up here as a discrepancy, and would
    otherwise masquerade as a surprising cell delay.
    """
    f_short = measure_ring(board, ring, clk_hz, long_window=False)
    f_long = measure_ring(board, ring, clk_hz, long_window=True)
    if not f_short or not f_long:
        return check("window agreement", False, "a window produced nothing")
    err = abs(f_short - f_long) / f_long
    return check("window agreement", err < tol,
                 "%s: short %.1f MHz vs long %.1f MHz (%.2f%%)"
                 % (ring, f_short / 1e6, f_long / 1e6, err * 100))


def measure_rings(board=None, clk_hz=None):
    """THE measurement. Returns {ring: f_hz} and prints the comparison."""
    own = board is None
    if own:
        board = Board.open()
        board.select()
        board.clock(CLK_HZ)
        board.reset_pulse()
    if clk_hz is None:
        clk_hz = check_heartbeat(board) or CLK_HZ

    # MEASURE EVERYTHING BEFORE REPORTING ANYTHING. The INV ring's cell delay
    # cannot be computed from the INV ring alone -- its enable stage is a
    # NAND2, so de-blending needs the NAND2 reading (see stage_delay_s).
    out = {}
    for ring in ORDER:
        out[ring] = measure_ring(board, ring, clk_hz, long_window=True)

    log("\n  %-7s %12s %12s %10s %12s  %s" %
        ("ring", "measured", "predicted", "ratio", "stage delay", "band"))
    for ring in ORDER:
        f = out[ring]
        if not f:
            log("  %-7s %12s   %10.1f MHz" %
                (ring, "DEAD" if f == 0.0 else "no reading",
                 PREDICTED_HZ[ring] / 1e6))
            continue
        pred = PREDICTED_HZ[ring]
        tp = stage_delay_s(f, ring, out.get("NAND2"))
        lo, hi = PREDICTED_BAND_HZ[ring]
        # THE VERDICT THAT WAS MISSING. PREDICTED_BAND_HZ was DEAD CODE -- its
        # only mention anywhere in the repo was its own definition. The script
        # printed a ratio against the tt point and never said whether the
        # reading sits inside the ff..ss corner spread, which is the only
        # judgement separating "the model is wrong" from "this part is cold".
        band = "in band" if lo <= f <= hi else "OUTSIDE ff..ss  <-- the result"
        log("  %-7s %9.1f MHz %9.1f MHz %10.3f %9s ps  %s"
            % (ring, f / 1e6, pred / 1e6, f / pred,
               "n/a" if tp is None else "%.1f" % (tp * 1e12), band))
    if out.get("INV") and not out.get("NAND2"):
        log("\n  NOTE: INV stage delay is 'n/a' because the NAND2 ring did not")
        log("  read. The INV ring is 30 INV_X1 + 1 NAND2_X1, so its cell delay")
        log("  needs the NAND2 ring to de-blend the enable stage. The blended")
        log("  value would be ~1.2 %% high; it is withheld rather than shown.")

    live = [r for r in ORDER if out.get(r)]
    if len(live) == len(ORDER):
        got = sorted(live, key=lambda r: -out[r])
        want = sorted(ORDER, key=lambda r: -PREDICTED_HZ[r])
        log("\n  flavor ordering: measured %s, predicted %s%s"
            % (" > ".join(got), " > ".join(want),
               "" if got == want else "   <-- DIFFERENT, and interesting"))
    log("\n  A ratio away from 1.000 is the RESULT, not a fault: it is the")
    log("  first number in this stack not produced by the same tools that")
    log("  produced the prediction. Ratios that differ BETWEEN flavors point")
    log("  at cell-level modelling; a common offset points at the process")
    log("  corner or the supply. The library is characterized at THREE PVT")
    log("  corners (lib-v1.1 onward), so PREDICTED_BAND_HZ above is the")
    log("  model's own ff..ss spread rather than a guess.")
    return out


# ------------------------------------------------------------------- entry


def main(clk_hz=CLK_HZ):
    del _results[:]
    del _skipped[:]

    log("vertical slice — silicon bring-up")
    log("design: %s" % DESIGN)

    board = Board.open()
    board.select()
    board.clock(clk_hz)
    board.reset_pulse()

    log("\n1. is it alive, and can we talk to it")
    check_ui_drive(board)
    clk = check_heartbeat(board) or clk_hz

    log("\n2. is the instrument trustworthy")
    if check_instrument(board, clk):
        check_window_agreement(board, clk)
    else:
        skip("window agreement", "no valid measurement to compare")

    log("\n3. the measurement")
    rings = measure_rings(board, clk)
    for ring in ORDER:
        check("%s ring oscillates" % ring, bool(rings.get(ring)),
              "%.1f MHz" % (rings[ring] / 1e6) if rings.get(ring) else "no reading")

    failed = [n for n, ok, _ in _results if not ok]
    log("\n%d/%d checks passed" % (len(_results) - len(failed), len(_results)))
    if _skipped:
        log("NOT VERIFIED (%d skipped): %s"
            % (len(_skipped), ", ".join(n.strip() for n, _ in _skipped)))
    if failed:
        log("FAILED: %s" % ", ".join(failed))
    else:
        log("instrument healthy — the numbers above are the experiment.")
    board.set_ui(0)
    return not failed


def sweep_supply(voltages=(1.6, 1.7, 1.8, 1.9), ring="INV", clk_hz=CLK_HZ):
    """Ring frequency vs core supply, if the board can adjust it.

    The library is characterized at three process/temperature corners
    (lib-v1.1 onward), but voltage is not swept within a corner, so a supply
    sweep is still the cheapest way to get a dV slope out of real silicon.
    Skips itself cleanly if the firmware cannot set the voltage.
    """
    board = Board.open()
    board.select()
    board.clock(clk_hz)
    board.reset_pulse()

    setter = None
    for attr in ("set_core_voltage", "core_voltage", "vdd"):
        if hasattr(board.tt, attr):
            setter = attr
            break
    if setter is None:
        log("this firmware exposes no core-voltage control — skipping")
        return None

    out = {}
    for v in voltages:
        try:
            target = getattr(board.tt, setter)
            if callable(target):
                target(v)
            else:
                setattr(board.tt, setter, v)
        except Exception as e:  # noqa: BLE001
            log("could not set %.2f V (%s) — stopping" % (v, e))
            break
        time.sleep_ms(100)
        board.reset_pulse()
        clk = check_heartbeat(board) or clk_hz
        f = measure_ring(board, ring, clk, long_window=True)
        out[v] = f
        log("  %.2f V -> %s" % (v, "%.1f MHz" % (f / 1e6) if f else "no reading"))
    return out


if __name__ == "__main__":
    main()
