# SPDX-FileCopyrightText: Â© 2026 Joonatan Alanampa
# SPDX-License-Identifier: Apache-2.0
"""Run the UNMODIFIED bring-up script against a virtual demo board.

The chips land ~2027. A bring-up script that has never been executed is a
script that will fail on the day it matters, in a lab, with no debugger â€” so
this stands up a fake RP2040 + fake die and runs the real
`vslice_bringup.main()` against it.

Two classes of test, and the second is the important one:

  * a HEALTHY die must pass every check and recover the ring frequencies to
    within the counter's quantisation;
  * a BROKEN die must be CAUGHT â€” a dead ring, a stuck counter, an instrument
    that never asserts valid, a DIP switch vetoing a control pin, and a clock
    that is not the one we asked for. A bring-up script that passes everything
    is worth nothing.

The fake die models the parts of ro_meas.sv that the script actually depends
on: the windowed count (including its truncation), the busy/valid status bits,
the byte mux, and the heartbeat divider. It is not a substitute for the RTL
tests â€” it is a test of the SCRIPT.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

STAGES, PRE, WIN_SHORT, WIN_LONG, BEAT_BIT = 31, 8, 12, 20, 23
# what the die is pretending to be: the phase-4 prediction
TRUE_HZ = {1: 442.7e6, 2: 359.2e6, 3: 252.1e6}


# ----------------------------------------------------------------- fake MCU


class FakeTime:
    """MicroPython's time API over a virtual clock.

    Reading a port COSTS time here, as it does on the real board (~50 us per
    output-byte read through the firmware). Without that, a polling loop like
    measure_byte_hz never terminates — which is not a modelling detail but the
    first thing the fake got wrong, and it hung the test run for 5 minutes.
    """

    POLL_US = 50

    def __init__(self):
        self.us = 0

    def sleep_ms(self, ms):
        self.us += int(ms) * 1000

    def tick(self):
        self.us += self.POLL_US

    def ticks_us(self):
        return self.us

    def ticks_diff(self, a, b):
        return a - b


class FakeDie:
    """Enough of tt_um_joonatanalanampa_vslice to exercise the script."""

    def __init__(self, clk_hz=25e6, rings=None, faults=()):
        self.clk_hz = clk_hz
        self.rings = dict(TRUE_HZ if rings is None else rings)
        self.faults = set(faults)
        self.ui = 0
        self.count = 0
        self.valid = False
        self.busy = False
        self._pending = (0, WIN_SHORT)
        self.time = None            # set by FakeBoard

    # -- the instrument --------------------------------------------------
    def _window_bits(self):
        return WIN_LONG if self.ui & (1 << 5) else WIN_SHORT

    def _complete(self, sel, win_bits):
        """The window closes: latch a count, drop busy, raise valid."""
        if "instrument_dead" in self.faults:
            return
        if "counter_stuck" in self.faults:
            self.count, self.valid, self.busy = 42, True, False
            return
        f = self.rings.get(sel, 0.0)
        if "ring%d_dead" % sel in self.faults:
            f = 0.0
        window_s = (1 << win_bits) / self.clk_hz
        self.count = int(f / (1 << PRE) * window_s)     # truncates, as in RTL
        self.valid = True
        self.busy = False

    def write_ui(self, value):
        if "dip_veto" in self.faults:
            value &= ~(1 << 4)          # a DIP switch holding RUN's pin high
        self.ui = value
        sel = value & 0x03
        if not value & (1 << 7):
            return self.ui
        if (value & (1 << 4)) and sel:
            # RUN raised: a window opens, and its length is captured HERE —
            # changing ui[5] later must not retroactively change it
            if not self.busy:
                self.busy = True
                self._pending = (sel, self._window_bits())
        elif self.busy:
            # RUN dropped after the script waited out the window
            self._complete(*self._pending)
        return self.ui

    def read_uo(self):
        if not self.ui & (1 << 7):      # sine mode: heartbeat on uo[0]
            # uo[0] is BIT 23 of the free counter: it toggles every 2**23
            # clocks, so a full period is 2**24 and f = clk / 2**24
            counter = int(self.time.us * 1e-6 * self.clk_hz)
            return (counter >> BEAT_BIT) & 1
        byte_sel = (self.ui >> 2) & 0x03
        if byte_sel == 3:
            return (0x02 if self.valid else 0) | (0x01 if self.busy else 0)
        return (self.count >> (8 * byte_sel)) & 0xFF


class FakeBoard:
    """The ttboard.demoboard.DemoBoard surface the shim uses."""

    def __init__(self, die, ftime):
        self.die = die
        self.time = ftime
        die.time = ftime
        self.shuttle = self
        self.mode = None
        self.pins = None
        self._ui = 0

    # shuttle
    def has(self, name):
        return name == "tt_um_joonatanalanampa_vslice"

    def get(self, name):
        return self

    def enable(self):
        pass

    # clock / reset
    def clock_project_PWM(self, hz):
        pass                            # the die keeps its OWN clock, on purpose

    def reset_project(self, asserted):
        if not asserted:
            self.die.valid = self.die.busy = False
            self.die.count = 0

    # ports
    class _Port:
        def __init__(self, board, write):
            self._board, self._write = board, write

        def __int__(self):
            b = self._board
            if self._write:
                return b._ui
            b.time.tick()               # a port read is not free
            return b.die.read_uo()

        @property
        def value(self):
            return int(self)

        @value.setter
        def value(self, v):
            b = self._board
            b._ui = b.die.write_ui(v)

    @property
    def ui_in(self):
        return self._Port(self, True)

    @property
    def uo_out(self):
        return self._Port(self, False)


# The board the stubbed firmware hands out. `Board.open()` imports ttboard at
# CALL time, not import time, so the stub has to still be there when main()
# runs — hence a mutable slot rather than a closure over one test's board.
_CURRENT = {}


def _install_ttboard_stub():
    if "ttboard" in sys.modules:
        return
    demoboard = types.ModuleType("ttboard.demoboard")
    demoboard.DemoBoard = types.SimpleNamespace(get=lambda: _CURRENT["board"])
    ttboard = types.ModuleType("ttboard")
    ttboard.demoboard = demoboard
    mode = types.ModuleType("ttboard.mode")
    mode.RPMode = types.SimpleNamespace(ASIC_RP_CONTROL="asic_rp")
    sys.modules.update({"ttboard": ttboard, "ttboard.demoboard": demoboard,
                       "ttboard.mode": mode})


def load_script(die, clk_hz=25e6):
    """Import vslice_bringup with the MicroPython world stubbed out.

    `ttboard` is stubbed for good — nothing else on a host claims that name.
    `time` is NOT: swapping the real module out of sys.modules for the whole
    session would break pytest itself, so it is installed just long enough for
    the import to bind it, then handed to the module directly.
    """
    ftime = FakeTime()
    board = FakeBoard(die, ftime)
    _CURRENT["board"] = board

    time_mod = types.ModuleType("time")
    time_mod.sleep_ms = ftime.sleep_ms
    time_mod.ticks_us = ftime.ticks_us
    time_mod.ticks_diff = ftime.ticks_diff

    _install_ttboard_stub()
    sys.path.insert(0, str(HERE))

    real_time = sys.modules.get("time")
    sys.modules["time"] = time_mod
    try:
        sys.modules.pop("vslice_bringup", None)
        bu = importlib.import_module("vslice_bringup")
    finally:
        if real_time is not None:
            sys.modules["time"] = real_time
    bu.time = time_mod          # keep the virtual clock after the swap back
    return bu, board, ftime


# --------------------------------------------------------------------- tests


def test_healthy_die_recovers_the_ring_frequencies():
    die = FakeDie()
    bu, board, _ = load_script(die)
    got = bu.measure_rings(bu.Board(board), clk_hz=die.clk_hz)

    for name, sel in bu.SEL.items():
        want = TRUE_HZ[sel]
        assert got[name], "%s reported nothing" % name
        # the counter truncates, so tolerance is one count at the long window
        quant = (1 << bu.PRE) * die.clk_hz / (1 << bu.WIN_LONG)
        assert abs(got[name] - want) <= 2 * quant, (name, got[name], want)


def test_flavor_ordering_is_recovered():
    die = FakeDie()
    bu, board, _ = load_script(die)
    got = bu.measure_rings(bu.Board(board), clk_hz=die.clk_hz)
    assert sorted(got, key=lambda r: -got[r]) == ["INV", "NAND2", "NOR2"]


def test_a_dead_ring_is_caught():
    die = FakeDie(faults=["ring2_dead"])
    bu, board, _ = load_script(die)
    got = bu.measure_rings(bu.Board(board), clk_hz=die.clk_hz)
    assert got["NAND2"] == 0.0, "a dead ring must read as dead, not as slow"
    assert got["INV"], "the other rings must still measure"


def test_an_instrument_that_never_validates_is_caught():
    die = FakeDie(faults=["instrument_dead"])
    bu, raw, _ = load_script(die)
    board = bu.Board(raw)
    assert not bu.check_instrument(board, die.clk_hz), \
        "an instrument that never asserts valid must not pass"


def test_a_stuck_counter_is_caught_by_window_disagreement():
    """The two windows share only the ring: a counter that always reports the
    same number cannot agree with both."""
    die = FakeDie(faults=["counter_stuck"])
    bu, raw, _ = load_script(die)
    board = bu.Board(raw)
    assert not bu.check_window_agreement(board, die.clk_hz), \
        "a frozen count must fail the short-vs-long comparison"


def test_a_vetoed_control_pin_is_caught():
    die = FakeDie(faults=["dip_veto"])
    bu, raw, _ = load_script(die)
    board = bu.Board(raw)
    assert not bu.check_ui_drive(board), \
        "a DIP switch holding a control pin must be reported, not ignored"


def test_main_passes_on_a_healthy_die(capsys):
    """The whole script, start to finish, exactly as it runs in the lab."""
    die = FakeDie()
    bu, _, _ = load_script(die)
    assert bu.main() is True
    out = capsys.readouterr().out
    assert "heartbeat" in out and "the measurement" in out
    for ring in ("INV", "NAND2", "NOR2"):
        assert ring in out
    assert "FAILED" not in out


def test_main_fails_on_a_dead_ring():
    """A die with one dead ring must not report success."""
    die = FakeDie(faults=["ring3_dead"])
    bu, _, _ = load_script(die)
    assert bu.main() is False


def test_frequencies_are_computed_from_the_measured_clock():
    """The RP2040 PWM settles for a nearby clock; the die's real clock is the
    one the heartbeat reports, and every frequency must follow THAT."""
    die = FakeDie(clk_hz=20e6)          # not the 25 MHz we will ask for
    bu, raw, _ = load_script(die)
    board = bu.Board(raw)

    clk = bu.check_heartbeat(board)
    assert clk is not None and abs(clk - 20e6) / 20e6 < 0.02, clk

    got = bu.measure_rings(board, clk_hz=clk)
    quant = (1 << bu.PRE) * die.clk_hz / (1 << bu.WIN_LONG)
    assert abs(got["INV"] - TRUE_HZ[1]) <= 2 * quant, got["INV"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
