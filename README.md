![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# Vertical slice — the same chip, built from my own physics up

[CORDIC-1](https://github.com/JoonatanAlanampa/CORDIC) went to fabrication
on TinyTapeout's TTSKY26c built out of SkyWater's `sky130_fd_sc_hd`
standard cells. This is the same chip — same RTL, bit for bit — rebuilt
on a standard-cell library I designed myself: transistor widths sized
from device physics I solved from scratch ([`devphys`](https://github.com/JoonatanAlanampa/devphys)),
cell layouts drawn and DRC/LVS-signed-off by my own tooling, timing
characterized by my own ngspice-to-Liberty characterizer
([`stdcells`](https://github.com/JoonatanAlanampa/stdcells)).

One variable changed, everything else held fixed. The fabricated chip is
the control group.

Riding along: **ring-oscillator test structures**, one per cell flavor
(INV, NAND2, NOR2), which let the die report the propagation delay of my
own cells in real silicon — the number that my device model, my
characterizer and the signoff STA each predicted, and that nothing has
yet been able to falsify.

- **[Die viewer](https://joonatanalanampa.github.io/vertical-slice/)** — the
  actual layout, 2D and 3D, rebuilt by CI on every green run
- [PLAN.md](PLAN.md) — the vertical slice, phase by phase, and what the
  measurement is actually for
- [Datasheet](docs/info.md) — pinout, read-out protocol, bring-up, and the
  per-corner counts the die should return
- [READINESS.md](READINESS.md) — the findings ledger: every defect found in
  this design, what it cost, and what closed it. Read it before trusting a
  green badge here
- [Test suite](test/) — cocotb, both halves of the chip

## What "self-designed" means here, exactly

| layer | source |
|---|---|
| device physics, mobility, velocity saturation | mine (`devphys`, calibrated to measured sky130 silicon) |
| transistor sizing | mine (drives measured in ngspice) |
| cell schematics and layouts | mine (own GDS; official DRC + LVS decks pass) |
| timing/power characterization (`own.lib`) | mine (own characterizer, ~175 ngspice runs) |
| logic (RTL) | mine (the fabricated CORDIC-1) |
| synthesis, place & route, signoff tools | open source (yosys, OpenROAD/LibreLane, magic, netgen, KLayout) |
| **process, masks, design rules, TT harness** | **SkyWater / TinyTapeout — not mine** |

That last row is the honest boundary: this is self-*designed* silicon on
somebody else's process, not self-fabricated silicon. Everything above it
is enforced mechanically — the hardened netlist is checked for
`sky130_fd_sc_hd` content, including tie cells, hold buffers and CTS
buffers, and the build fails if any is found.

## Status

**Hardened and signed off; not submitted.** The all-own flow runs end to end
in CI — synthesis, place & route, DRC, LVS, antenna, timing at nine corners,
TinyTapeout's own precheck, and a gate-level simulation of the ring read-out
on the routed netlist. The library arrives as a pinned `stdcells` release,
verified against a per-file checksum before anything is built.

```
python test/run.py          # both suites (icarus + cocotb, no make needed)
```

## What the die should return

This is the whole point of the chip: three ring oscillators built from one cell
flavour each, whose frequency is a direct read-out of that cell's propagation
delay in real silicon. The numbers below are what my own model predicts, and
they are what the first die gets held against.

Counts are per **short** window (2^12 clocks at 25 MHz); multiply by 256 for the
long window. Computed from run `32576208363` on `stdcells` **`lib-v2.2`**.

| ring | ff (-40 C, 1.95 V) | tt (25 C, 1.80 V) | ss (100 C, 1.60 V) |
|---|---|---|---|
| INV | 486.7 MHz / 312 | **397.3 MHz / 254** | 285.2 MHz / 183 |
| NAND2 | 353.4 MHz / 226 | **278.5 MHz / 178** | 187.9 MHz / 120 |
| NOR2 | 253.4 MHz / 162 | **201.3 MHz / 129** | 140.2 MHz / 90 |

The parasitic-extraction corner is worth about 1.5 %, so it is a band rather
than a single number. `min`..`max` RC brackets the `nom` column above:

| ring | ff min..max | tt min..max | ss min..max |
|---|---|---|---|
| INV | 313 .. 310 | 256 .. 253 | 183 .. 182 |
| NAND2 | 228 .. 224 | 180 .. 177 | 121 .. 119 |
| NOR2 | 164 .. 161 | 130 .. 127 | 90 .. 89 |

And the cell delays those counts imply — the three numbers this whole project
exists to compare against device physics:

| corner | `tp_INV` | `tp_NAND2` | `tp_NOR2` |
|---|---|---|---|
| ff (-40 C, 1.95 V) | 32.72 ps | 45.64 ps | 63.65 ps |
| tt (25 C, 1.80 V) | **40.02 ps** | **57.91 ps** | **80.12 ps** |
| ss (100 C, 1.60 V) | 55.58 ps | 85.84 ps | 115.04 ps |

> The INV ring is 30 inverters plus the NAND2 that gates it, so its raw period
> is a 30:1 *blend* of two cells. `tp_INV` above is de-blended using the NAND2
> ring, which measures that stage directly; the blend is worth
> +1.16 % (ff) / +1.38 % (tt) / +1.62 % (ss).

**None of these are typed by hand.** `flow/check_ring_doc.py` re-derives all
nine headline figures, all eighteen band figures and all nine cell delays from
the routed design on every CI run, and compares them against this README, the
datasheet and the bring-up script — the three places they are published — plus
the `ro_clk` constraint in `harden/signoff.sdc`. If the design moves and a
table does not, the build fails. That guard exists because these numbers went
stale twice without anyone noticing.

## Signoff

Nine timing corners, on the netlist that actually ships. Every metric below is
in `tools/check_signoff.py`'s must-be-zero list, and a metric that is *missing*
fails the build too — a check that cannot run is not a check that passed.

| | |
|---|---|
| LVS | **match uniquely**, 7006 vs 7006 devices, 3040 nets |
| DRC (magic + KLayout FEOL/BEOL/offgrid) | **0** |
| antenna violations | **0** |
| power-grid violations | **0** |
| setup / hold violations, 9 corners | **0 / 0** |
| max-slew / max-fanout / max-cap | **0 / 0 / 0** |
| foundry cells in the submitted netlist and GDS | **0** |
| TinyTapeout precheck | **pass** |

Margins on `lib-v2.2` (run `32576208363`; re-derived and recorded in
[`READINESS.md`](READINESS.md) on every library re-pin):

| | worst | where |
|---|---|---|
| hold slack | **+54.41 ps** | bare-die build, `min_ff` |
| setup slack | **+887.3 ps** | bare-die build |
| `min_pulse_width` margin | **+856.7 ps** | `_4879_/CLK`, `max_ff` |
| prescaler headroom vs its ring | **1.46x** | `ss`, the binding corner |

The last row is the one to check the first silicon against: the counter
tolerates a ring **46 % faster than predicted** at the binding corner. A
picosecond count against a constraint I chose myself would say less.

### What is asserted on every run, and why that list is long

This repo has repeatedly found checks that *ran, printed zeros, and were
believed* — a hold check against a requirement of `0.0`, a max-fanout check
against a library that declared no fanout load, a zero-foundry audit that ran
only on a build nobody submitted, nine "timing corners" that were byte-identical
copies of one. Each fix therefore came with a guard, and each guard is proven
to be capable of failing:

- zero foundry content in the **submitted netlist** *and* the **fabricated
  GDS**, tie/fill/tap/diode/CTS buffers included
- the pinned library is the library that was built with (checksums, and the
  set — an unpinned file in `lib/` fails the build)
- LVS matches uniquely, DRC/antenna/PDN clean, and the verdicts are *read*
  rather than left in a log
- every clock pulse on the die is wider than the library's **measured**
  minimum pulse width, at nine corners, with a positive control that flags
  the ring flops when the requirement is inflated
- the ring predictions published in the datasheet and in the bring-up script
  still match the design being built — regenerated and compared, not trusted

**A green badge here is evidence about what was checked, not proof the chip is
right.** [READINESS.md](READINESS.md) is the honest version, including the
things known to be wrong and knowingly accepted.
