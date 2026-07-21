## How it works

This chip is **CORDIC-1 built out of a self-designed standard-cell
library**, carrying the test structures that measure that library in
silicon.

The logic is deliberately unchanged from the version fabricated on
TTSKY26c: a bit-serial CORDIC engine swept by a 20-bit DDS, streaming
sigma-delta sine on the Audio Pmod pin, with a phase-locked square sync,
an LED level bar and a heartbeat. Same RTL, same behaviour, same
verification. What changed is everything underneath it — every
transistor width, cell layout, timing arc and LEF abstract comes from
our own library, sized from our own device physics rather than from the
foundry's cells.

`ui[7]` picks which half of the chip owns the pins.

### Sine mode (`ui[7] = 0`) — the chip's function

Identical to CORDIC-1. `ui[6:0]` is the frequency code:

| code | output |
|---|---|
| 0 (power-on default) | **440 Hz — concert A wake-up tone** |
| 1..126 | code x ~68 Hz (~68 Hz .. ~8.6 kHz) |
| 127 | ~2 Hz breathe mode: the LED bar visibly waves |

`uo[7]` is the sine sigma-delta (RC low-pass or the TT Audio Pmod turns
it analog), `uo[6]` a phase-locked square sync, `uo[5:1]` the live sine
level as an offset-binary bar, `uo[0]` a ~1.5 Hz heartbeat.

The ring oscillators are held off in this mode — they would otherwise
burn power and inject supply noise straight into the audio output.

### Test-structure mode (`ui[7] = 1`) — the measurement

Three ring oscillators, one per cell flavor, 31 stages each:

| `ui[1:0]` | ring |
|---|---|
| 0 | all off |
| 1 | INV_X1 (30 inverters + the enabling NAND2) |
| 2 | NAND2_X1 |
| 3 | NOR2_X1 |

Raise `ui[4]` (RUN) and the selected ring is enabled, given 256 clocks to
warm up, then its output — divided by 256 on-chip — is counted for a
fixed window of system clocks. `ui[5]` picks the window: 2^12 clocks
(164 us at 25 MHz) or 2^20 (41.9 ms). The result latches into a 24-bit
counter, read out a byte at a time on `uo[7:0]` with `ui[3:2]`:

| `ui[3:2]` | `uo[7:0]` |
|---|---|
| 0 | count[7:0] |
| 1 | count[15:8] |
| 2 | count[23:16] |
| 3 | status: `{heartbeat, ring_alive, 0,0,0,0, valid, busy}` |

Hold RUN high and measurements repeat back to back; drop it and the last
result stays latched. The ring frequency, and from it the propagation
delay of one cell, is:

```
f_ring = count * 256 / (2**window / f_clk)
tp     = 1 / (2 * 31 * f_ring)
```

Everything needed is on the die — no analog pins, no calibration, no
instrument beyond a clock of known frequency.

## How to test

**Sine mode.** Power on, select the design, release reset: the heartbeat
blinks, the level bar waves, and `uo[7]` plays 440 Hz through an RC
low-pass (1 kOhm + 100 nF) or the TT Audio Pmod. Sweep `ui[6:0]` to walk
the frequency table; `uo[6]` gives the scope a trigger.

**Test-structure mode.** Set `ui[7]` and `ui[1:0] = 01`, raise `ui[4]`,
wait past the window (164 us on the short setting), then read the three
count bytes through `ui[3:2]`. Repeat for `ui[1:0] = 10` and `11`. Three
counts, three cell delays. Compare them against `own.lib`, against the
DEVSIM device model, and against the OpenSTA signoff numbers — that
comparison is the reason the chip exists.

`ui[3:2] = 11` also puts the prescaled ring on `uo[6]` (`ring_alive`)
while a measurement is running, so a scope or a frequency counter can
read the ring directly, independent of the digital read-out path. Hold
RUN high and it toggles continuously. Outside a measurement it reads 0 —
the prescaler has no reset (the cell library has no flop with one), so
its bits are only meaningful after the warm-up that clears them.

## External hardware

None required. Optional: the **TT Audio Pmod** (or a 1 kOhm + 100 nF RC
low-pass) on `uo[7]` for the sine output; DIP switches on `ui`; LEDs on
`uo`.
