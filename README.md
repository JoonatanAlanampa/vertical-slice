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
