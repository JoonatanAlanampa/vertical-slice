# Bring-up — the day the chips arrive

`vslice_bringup.py` runs on the TinyTapeout demo board's RP2040 (MicroPython).
Copy it to the board's filesystem and:

```python
>>> import vslice_bringup as bu
>>> bu.main()            # instrument self-check, then THE measurement
>>> bu.measure_rings()   # just the ring frequencies, as a table
>>> bu.sweep_supply()    # ring frequency vs core voltage, if adjustable
```

## What it prints

```
1. is it alive, and can we talk to it
  [PASS] ui_in drive                all 8 control pins follow
  [PASS] heartbeat                  1.490 Hz -> clock 25.000 MHz

2. is the instrument trustworthy
  [PASS] dark ring reports idle     status 0x00 with no ring selected
  [PASS] valid after a window       count 283, status 0x02
  [PASS] window agreement           INV: short 442.2 MHz vs long 442.7 MHz (0.11%)

3. the measurement

  ring        measured    predicted      ratio  stage delay
  INV         442.7 MHz     442.7 MHz      1.000      36.4 ps
  NAND2       359.2 MHz     359.2 MHz      1.000      44.9 ps
  NOR2        252.1 MHz     252.1 MHz      1.000      64.0 ps
```

(That run is against the *virtual* die in `test_bringup_host.py`, which is why
every ratio is exactly 1.000. Real silicon is the interesting case.)

## Two things it is careful about

**The clock is measured, never assumed.** `clock_project_PWM()` retunes the
RP2040's system clock and quietly settles for a nearby frequency, so a ring
frequency computed from the *requested* clock would be wrong by however much
the PWM missed. Everything here is computed from the heartbeat on `uo[0]`,
which is `clk / 2**24` by construction.

**A mismatch is not a failure.** The script fails on an instrument it cannot
trust — a ring that never oscillates, a counter that reports the same number
for both window lengths, a control pin a DIP switch is holding down. It does
*not* fail on measured-vs-predicted, because that comparison is the entire
point of the chip: the prediction came from our own device physics, our own
characterizer and our own STA, and silicon is the first thing in that chain
that was not produced by the same tools. A ratio away from 1.000 is the
result. Ratios that differ *between* flavors point at cell-level modelling; a
common offset across all three points at the process corner or the supply.

## Testing it without hardware

```
python -m pytest bringup/ -v
```

`test_bringup_host.py` stands up a fake RP2040 and a fake die and runs the
**unmodified** script against them. A healthy die must pass and recover the
frequencies to within the counter's quantisation; a broken one must be
*caught* — dead ring, frozen counter, instrument that never validates, vetoed
control pin, and a clock that is not the one we asked for. A bring-up script
that passes everything is worth nothing.

Two bugs this found before hardware ever will:

- `read_byte()` was clearing the window-select bit while walking the byte mux,
  so a re-armed FSM could have latched a short-window count while the script
  believed it had asked for a long one.
- the fake's own heartbeat divider was off by 2×, which is exactly the mistake
  that would make every ring frequency wrong by 2× in the lab, and look
  entirely plausible while doing it.

## Provenance

The demo-board API shim is lifted from `tt-cordic/bringup/cordic1_bringup.py`,
where it was verified against **tt-micropython-firmware v2.0.0** (commit
`f34d9f0`, microcotb `81f2498`). Firmware facts it depends on:

- `DemoBoard.get()` is the singleton accessor; a second `DemoBoard()` raises.
- `tt.ui_in` / `tt.uo_out` are microcotb IO ports, not ints — read with
  `int()`, write with `.value`. `port[i]` is a sampled Logic **bit**, not a
  `machine.Pin`; raw pins live at `tt.pins.uo_out<N>.raw_pin`.
- entering `ASIC_RP_CONTROL` leaves any `ui_in` pin already reading HIGH as an
  *input* (contention guard, logs an error and continues) — so a DIP switch
  left on silently vetoes that bit. `check_ui_drive()` turns that into a
  message instead of a mystery.

Constants mirror `src/ro_meas.sv` and `src/project.sv`; the predictions come
from `flow/ring_prediction.py`. Keep them in sync.
