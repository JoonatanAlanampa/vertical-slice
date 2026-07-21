# Vertical slice — plan

**The chip:** CORDIC-1, re-hardened on the fully self-made standard-cell
library, plus device-physics test structures that measure that library in
silicon.

Nothing about the logic is new. That is the point. CORDIC-1 already went
to fabrication on TTSKY26c (commit `b646d057`) built out of SkyWater's
`sky130_fd_sc_hd` cells, and its behaviour is verified to death:
exhaustive 65,536-angle engine check, FFT harmonic check, a SymbiYosys
k-induction proof of the control path. Re-submitting the *same* logic
built out of *our own* cells turns the fabricated chip into the control
group of a controlled experiment — one variable changed, everything else
held fixed.

The vertical slice being closed:

```
   math + physics            devphys/     from-scratch Poisson/DD solvers,
        |                                 DEVSIM 2D nfet calibrated to
        v                                 measured sky130 silicon (300 K & 77 K)
   device sizing             stdcells/    drives measured in ngspice ->
        |                     phase 1     transistor widths
        v
   cell netlists + layouts   stdcells/    9 cells, own GDS, DRC + LVS clean
        |                     phase 2,5   against the official decks
        v
   own characterization      stdcells/    ~175 ngspice runs -> own.lib
        |                     phase 3     (NLDM delays, caps, setup, leakage)
        v
   place & route             stdcells/    LibreLane on own.lib/own.lef;
        |                     phase 6     1787 own cells on a TT 1x1, DRC 0
        v
   SILICON                   THIS REPO    the chip that makes the loop
        |                                 measurable instead of asserted
        v
   measurement back to physics            ring oscillators on this die
```

Every arrow above is done and green except the last two. This repo is
the last two.

## What the test structures are for

Three ring oscillators, one per cell flavor (INV_X1, NAND2_X1, NOR2_X1),
31 stages each, enable-gated, prescaled by 256 and counted against the
system clock (see `docs/info.md` for the read-out protocol). Each
ring's frequency is a direct read of that cell's propagation delay at the
real supply, the real temperature and the real process corner:

```
tp = 1 / (2 * STAGES * f_ring)
```

That single number is predicted three times over by work already on
disk, and until this chip exists all three predictions are unfalsified:

1. **DEVSIM device physics** (`devphys/`) — mobility, velocity
   saturation and series resistance fitted to measured sky130 device
   data, never to a delay.
2. **Our own characterizer** (`stdcells/flow/characterize.py`) — ngspice
   transient measurements through our own cell netlists, the numbers
   inside `own.lib`.
3. **OpenSTA at signoff** — what the flow believed when it signed the
   die off.

A ring oscillator is the cheapest structure that discriminates between
them, and it needs no analog pins, no calibration and no external
instrument beyond a known clock. Three flavors, not one, because the
interesting failure is *differential*: if INV matches but NAND2 is 20 %
slow, the error is in our stack/series modelling, not in a global
supply or temperature offset.

Also free, and worth stating: the same counter is a process monitor. Ring
frequency vs the fabricated CORDIC-1's measured Fmax on the same shuttle
tells us where our die landed between the ss and ff corners.

## Deliberate constraint: zero foundry content

The whole reason to build this is the claim "self-designed, all the way
down". That claim is only worth making if it is enforced mechanically,
so:

- **No `sky130_fd_sc_hd` cells in the hardened netlist**, including the
  hidden ones: tie cells, hold-fix buffers, CTS buffers, fill. The
  hybrid netlist (own combinational + `dfxtp_1`) that unblocked
  `stdcells` phase 6 is explicitly *not* what ships here — the all-own
  netlist with `DFF_X1` and `BUF_X1` is.
- The one thing that stays foundry-supplied is the **process** (sky130
  masks, design rules, the TT harness and I/O ring). That is the line
  between "self-designed" and "self-fabricated", and it is drawn
  honestly in the README rather than blurred.
- A CI check should *fail the build* on any `sky130_` cell in the final
  netlist, rather than leaving it to eyeball review.

## Library consumption: pinned, never live

`stdcells` is a moving repo; this one must not move with it. The library
arrives as a **pinned release artifact** — `own.lib`, `own.lef`,
`own_cells.gds`, the `.mag`/`.maglef` views and `own.spice` — downloaded
by tag (`lib-vX.Y`), checksummed, and never edited here. Nothing in this
repo writes to `stdcells`, and nothing here is regenerated from it at
build time.

Consequence for the ring RTL: `src/ro_ring.sv` instantiates
`INV_X1` / `NAND2_X1` / `NOR2_X1` **by name** under `` `USE_OWN_CELLS ``.
Those names are a contract with the pinned release. If a release renames
a cell, this repo breaks loudly at elaboration, which is the correct
failure.

## Phases

### Phase 0 — scaffold (DONE)
TT template structure, top module `tt_um_joonatanalanampa_vslice`, the
CORDIC-1 RTL vendored unchanged from the fabricated revision, the ring
test structures, and a cocotb suite that passes on both halves.

Measured on the way in, and worth keeping: **a ring oscillator does not
survive synthesis by default.** With the ring nodes merely marked
`(* keep *)`, yosys + ABC collapsed all three 31-stage chains to a single
gate each — a chain of 31 inverters is, to a logic optimizer, one
inverter. What holds is a per-stage module boundary (`ro_stage`, marked
`keep_hierarchy`) so the optimizer never sees two stages at once. Verify
this again after any tool-version bump; it is exactly the kind of thing
that silently breaks a test structure into a wire.

### Phase 1 — tile budget (DECIDE FIRST, it costs money)
Generic-cell counts from an identical yosys `synth` run:

| design | generic cells |
|---|---|
| CORDIC-1 alone (the fabricated logic) | 969 |
| this chip (CORDIC-1 + test structures) | 1410 |

The fabricated hd build was 921 cells at **74.0 %** utilization of a 1x1;
the all-own `stdcells` build was 1787 cells at **87.4 %** of a 1x1. Adding
~45 % more logic to either does not fit a 1x1 tile. `info.yaml` therefore
starts at **1x2**, which is also the only honest place to be: a 1x2 has
room to *add* test structures rather than shave them.

If a 1x1 is wanted instead, the trims — in the order that costs least
insight — are: 24-bit counter -> 16-bit with the long window shortened to
2^18 (~50 cells); drop the separate `count` latch and read `acc` while
idle (~25 flops); drop the NOR2 ring (~31 cells, but it also drops the
differential measurement that makes three flavors worth having).

### Phase 2 — reference build (foundry library)
Keep the stock TT `gds` workflow green on `sky130_fd_sc_hd` throughout.
This is the fallback that guarantees a submittable chip if the all-own
hardening runs out of road before the deadline, and it is the A/B
partner for the PPA table.

### Phase 3 — all-own hardening
Port `stdcells/flow/make_hardening.py` here against the pinned release:
elaborate-only synthesis, `dfflibmap` to `own_hardening.lib`, ABC against
the combinational-only copy, then LibreLane with `own.lib` / `own.lef`.
Carry over the hard-won configuration from that repo — core margins
1/1/2/2, hold slack margins 0.005, density ~85, the `heal_hvtp.py` pass,
signoff by the official KLayout deck in-container — and the lessons that
produced them.

Open question to settle here: the ring oscillators are a combinational
loop, which OpenSTA will report as a broken timing arc and OpenROAD's CTS
must be told to ignore. The STA exceptions belong in the hardening
config, not in the RTL.

### Phase 4 — gate-level verification
Re-run `test/` against the post-layout netlist (the `gl_test` job already
does this for the reference build; the all-own build needs the same job
pointed at our Verilog models). The RO count assertions relax to
"oscillates and is counted" at gate level, since the flow's unit delay is
not our cell delay — the real number only exists in silicon.

### Phase 5 — submission
Next TT shuttle after TTSKY26c. Ship with a bring-up script (MicroPython
on the demo board's RP2040) that runs the frequency sweep and dumps the
three ring frequencies, so the measurement happens the day the chips
arrive rather than "eventually".

### Phase 6 — close the loop
Publish measured vs predicted: silicon ring frequency against our own
`own.lib` arcs, against DEVSIM's device-level prediction, and against
OpenSTA signoff. Whichever way it comes out, it is the first number in
this whole stack that was not produced by the same tools that produced
the prediction. If the delay is off by 30 %, that is a *result* — it
points at exactly one of three modelled stages, and the differential
between flavors says which.

## Related repos

| repo | role |
|---|---|
| `../devphys` | device physics; TCAD calibrated to measured sky130 silicon |
| `../stdcells` | the standard-cell library, its characterization and its hardening flow |
| `../tt-cordic` | the fabricated control-group chip (TTSKY26c, `b646d057`) |
