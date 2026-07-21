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

- [PLAN.md](PLAN.md) — the vertical slice, phase by phase, and what the
  measurement is actually for
- [Datasheet](docs/info.md) — pinout, read-out protocol, bring-up
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

Scaffold. The RTL and the test bench are in and green; the library
arrives as a pinned `stdcells` release, and the all-own hardening flow is
phase 3 of [PLAN.md](PLAN.md).

```
python test/run.py          # both suites (icarus + cocotb, no make needed)
```
