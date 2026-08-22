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
tp     = 1 / (2 * 31 * f_ring)      <- NAND2 and NOR2 rings ONLY
```

`f_ring` is exact for all three rings. **`tp` is not.** It assumes 31
identical stages, which is true of the NAND2 and NOR2 rings and **false of
the INV ring**, which is 30 `INV_X1` + the enabling `NAND2_X1` (see the
table above, and `src/ro_ring.sv` — an odd-stage ring needs its enable gate
somewhere). Dividing that ring's period by 62 returns a 30:1 blend of the
two cells, not `INV_X1`'s delay. De-blend it with the NAND2 ring, which
measures that stage directly:

```
tp_INV = ( 1/f_INV - 1/(31 * f_NAND2) ) / 60
```

**Use it.** The blend is a one-signed bias of **+0.84 % (ff) / +1.21 % (tt) /
+1.68 % (ss)** — larger than the ±0.8 % RC band this page publishes below,
larger than the 1.0-1.2 % loop-closure correction that was thought worth a
paragraph, and it lands on the simplest cell, the one the device model
predicts most directly. Everything needed to correct it was already on this
page; the correction was not, until 2026-08-21.

⚠️ The de-blend charges the INV ring's NAND2 stage at the delay it shows in
the *NAND2* ring, where it drives a NAND2 rather than an inverter. The two
input pins differ by 0.001 fF and the driving slew differs, worth ~0.3 % on
that one stage — i.e. ~0.01 % on `tp_INV`, against the 1.2 % the de-blend
removes. Exact enough; not exact.

**What the cell delays should be** (same model and run as the count table
below — this is the answer key for the three numbers the die returns):

| corner | `tp_INV` | `tp_NAND2` | `tp_NOR2` |
|---|---|---|---|
| ff (-40 C, 1.95 V) | 28.45 ps | 38.70 ps | 56.69 ps |
| tt (25 C, 1.80 V) | **34.94 ps** | **49.84 ps** | **71.59 ps** |
| ss (100 C, 1.60 V) | 49.72 ps | 74.71 ps | 103.59 ps |

Everything needed is on the die — no analog pins, no calibration, no
instrument beyond a clock of known frequency.

## How to test

**Sine mode.** Power on, select the design, release reset: the heartbeat
blinks, the level bar waves, and `uo[7]` plays 440 Hz through an RC
low-pass (1 kOhm + 100 nF) or the TT Audio Pmod. Sweep `ui[6:0]` to walk
the frequency table; `uo[6]` gives the scope a trigger.

**What the counts should be.** Our own timing model predicts, per PVT
corner (short window, 25 MHz clock, run `32562513694`, `lib-v2.1`;
regenerate with `python flow/ring_prediction.py --run <run-dir>`, and
`flow/check_ring_doc.py` asserts on every CI run that this table still
matches the design being built):

| ring | ff (-40 C, 1.95 V) | tt (25 C, 1.80 V) | ss (100 C, 1.60 V) |
|---|---|---|---|
| INV | 560.4 MHz / 359 | **455.4 MHz / 291** | 319.2 MHz / 204 |
| NAND2 | 416.8 MHz / 267 | **323.6 MHz / 207** | 215.9 MHz / 138 |
| NOR2 | 284.5 MHz / 182 | **225.3 MHz / 144** | 155.7 MHz / 100 |

Multiply by 256 for the long window. A silicon reading that disagrees is
not a bug to be fixed — it is the result this chip exists to produce, and
the differences *between* flavors say which modelling stage to look at.

**The RC corner is worth about 1.5%, so it is a band, not a column.** The
table above is the `nom` parasitic extraction. Per PVT corner, `min`..`max`
RC brackets it (counts per short window):

| ring | ff min..max | tt min..max | ss min..max |
|---|---|---|---|
| INV | 361 .. 356 | 293 .. 290 | 205 .. 203 |
| NAND2 | 269 .. 264 | 209 .. 205 | 139 .. 137 |
| NOR2 | 184 .. 180 | 145 .. 143 | 101 .. 99 |

So a reading anywhere inside its PVT column's band is consistent with the
model; only a miss outside all three bands is a real disagreement.

**One stage per ring is charged double.** The loop-closure node — `fb`, which
is the same net as `n[30]` and `osc` — drives stage 0 *and* the tap into
`ro_meas`, so it carries two pin loads where every other node carries one.
Measured on the routed netlist (29 nets at fanout 1, `fb` at 2, and **no
buffer on it**, which is H3 staying fixed). Charging it costs **1.0-1.2%**,
and the table above already includes it; predictions published before
2026-08-04 do not.

**These replace the numbers this page carried until 2026-08-03** (914.1 /
658.3 / 411.7 MHz), which were the raw SDF sums and were **32-46%
optimistic**. What changed is the model, not the chip:

- The SDF **drops one stage per ring** — OpenSTA has to break the
  combinational loop to get an acyclic timing graph. For NAND2 and NOR2
  that is one of 31 identical stages; for the INV ring the broken arc is
  the single NAND2 gate, its most expensive stage, so that ring was short
  by 4.5% rather than 3%.
- The SDF carries **no interconnect on the ring nets at all** (every entry
  exactly 0.000, while ordinary nets in the same file carry 1-2 ps). The
  parasitics do exist in `final/spef/`, and the wire is worth 0.33-0.75 fF
  against a ~2.1 fF pin capacitance — 15-35% more load than the delay was
  computed for. Its own RC propagation is nothing (14.3 ohm on 0.83 fF is
  ~0.012 ps); it matters purely as load.
- **STA computed every inverting cell's delay at an input slew of zero**,
  because this library's transition tables were negative for inverting
  cells and OpenSTA clamps them (`READINESS.md` M11). ✅ **Fixed at the
  source in `stdcells` lib-v1.4**, pinned here since 2026-08-04. The table
  above solves the ring's own fixed point — each stage's input slew is the
  previous stage's output slew — which lands at 12-87 ps depending on cell
  and corner, below the NLDM's first characterized row (20 ps), which is
  why the fixed point is used rather than a lookup.

**The numbers barely moved when M11 was fixed, and that is not evidence
the defect was harmless.** tt went 625.0 → 628.4 / 459.1 → 460.1 / 294.5 →
294.8 MHz, all under 1%. A ring's period is the SUM of both edge delays
around the loop, and M11 exchanged which slew drove which edge, so the
total was preserved almost exactly. Where the two edges are *not* summed
the same defect was worth **766 ps** of setup slack on stdcells' own
CORDIC-1 harden, and it hid **58 max-slew violations** here (`M12`).

The corner spread is now genuine (`READINESS.md` M10): ff and ss differ on
98.5% of cell delay arcs, so -40 C and 100 C really are different columns.

⚠️ **Set the selectors BEFORE raising `ui[4]`, as two separate motions.**
`ui[1:0]` (ring) and `ui[5]` (window) are latched on the clock edge that arms
the measurement, and `ui[]` is not synchronized. Move a selector in the same
clock as `run` rises and the design can latch a ring you did not choose — the
count will be perfectly good and `valid` will be true, but it will be labelled
with the wrong ring. Nothing downstream can detect that, so it is procedure,
not paranoia.

**Test-structure mode.** Set `ui[7]` and `ui[1:0] = 01`, raise `ui[4]`,
wait past the window (164 us on the short setting), **then LOWER `ui[4]`
and wait one more window before reading** the three count bytes through
`ui[3:2]`. Repeat for `ui[1:0] = 10` and `11`. Three counts, three cell
delays — and remember the INV ring needs the de-blend above before its
count becomes an `INV_X1` delay. Compare them against `own.lib`, against
the DEVSIM device model, and against the OpenSTA signoff numbers — that
comparison is the reason the chip exists.

> **Drop RUN before you read — this is not optional.** `ui[4]` is a level,
> so while it is high the FSM re-arms the moment it goes idle and a new
> result overwrites `count` every 164 us (short window). Reading the three
> bytes one at a time across that boundary gives you the low byte of one
> measurement and the high byte of the next. Usually harmless, because
> consecutive counts differ by at most one — but exactly when the count
> crosses a byte boundary (`0x00FF` -> `0x0100`) the torn value is off by
> 256, and on the long window, where counts are ~256x larger and span two
> bytes, that is the normal case rather than the unlucky one. With RUN low
> the last result stays latched and the read is atomic.
> `bringup/vslice_bringup.py` already does this; earlier revisions of this
> page did not say so.

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
