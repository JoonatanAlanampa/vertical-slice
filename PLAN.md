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

Two things measured on the way in, both worth keeping:

**A ring oscillator does not survive synthesis by default.** With the
ring nodes merely marked `(* keep *)`, yosys + ABC collapsed all three
31-stage chains to a single gate each — a chain of 31 inverters is, to a
logic optimizer, one inverter.

**Per-stage `keep_hierarchy` is not the fix either.** It does stop the
collapse (verified: 31 stages survive), but LibreLane then dies with
`3 Unmapped Yosys instances found` / `ABC: Error: The network is
combinational` — ABC will not map a kept, purely combinational
submodule. The fix that works is also the one a test structure wants on
its merits: **instantiate cells by name** (`ro_stage` under
`` `USE_HD_CELLS `` / `` `USE_OWN_CELLS ``). A liberty cell instance is
opaque to yosys, so the ring survives flatten, constant propagation and
ABC with no attributes at all — and, more importantly, we know exactly
which cell the frequency measured. A "NAND2 ring" that ABC remapped to
an `o21ai` would measure nothing. The reference build selects its define
in `src/config.json`; only simulation uses behavioural gates.

Re-verify both after any tool-version bump: this is exactly the kind of
thing that silently degrades a test structure into a wire.

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

### Phase 3 — all-own hardening (IN PROGRESS, library pinned at lib-v1.0)
`tools/fetch_lib.py` pulls the release by tag into `lib/` and checks every
artifact against the committed `lib.lock`; `flow/make_hardening.py` builds
the netlist locally and commits it, so CI does place-and-route only and
cannot re-decide the logic. `harden/config.json` + the `harden` workflow
carry stdcells' hard-won settings verbatim (core margins 1/1/2/2, hold
margins 0.005, density 85, `EXTRA_EXCLUDED_CELLS: sky130_fd_sc_hd__*`,
`heal_hvtp.py`, KLayout-deck signoff in-container).

**The netlist is all-own and audited — 2804 cells, zero `sky130_` content
of any kind, tie cells included** (lib-v1.0's `TIE_X1` is what made that
reachable; the earlier hybrid still used foundry ties):

| cell | count | area µm² |
|---|---|---|
| NAND2_X1 | 1089 | 4088 |
| NOR2_X1 | 904 | 3393 |
| INV_X1 | 347 | 1303 |
| DFF_X1 | 274 | 4457 |
| BUF_X2 | 112 | 561 |
| TIE_X1 | 78 | 293 |
| **total** | **2804** | **14 094** |

That is **83.4 % of a 1x1 core before CTS, hold fixing and fill** — so a
1x1 is an experiment worth running, not a foregone conclusion (stdcells'
all-own CORDIC-1 routed at 87.4 % once). `harden/config.json` therefore
tries 1x1 first; if placement or routing dies, the fallback is the 1x2
line in that file, and this is the number to revisit.

The library also **changed the RTL**, which is the honest cost of building
on cells you designed yourself: `DFF_X1` has no reset pin, so the
ring-domain prescaler could not keep its async reset. It is now cleared
during warm-up (when the ring is, by construction, running) and its MSB is
masked outside the measurement window so an un-cleared power-up state
cannot reach a pin. Side benefit: the start phase is deterministic, and
the three rings now read identical counts instead of differing by one.

Open question still to settle: the rings are a combinational loop, which
OpenSTA reports as a broken timing arc and CTS must be told to ignore. The
STA exceptions belong in the hardening config, not in the RTL.

### Phase 4 — gate-level verification
Re-run `test/` against the post-layout netlist (the `gl_test` job already
does this for the reference build; the all-own build needs the same job
pointed at our Verilog models).

**The rings are excluded from gate-level simulation, and that is not a
shortcut.** sky130's `FUNCTIONAL` models are plain `not`/`buf` primitives
with no delay (`UNIT_DELAY` reaches only the sequential cells), so a
gate-level ring is a zero-delay combinational loop: the simulator does
not fail, it *hangs* at a single timestamp. Measured — a `gl_test` job
burned 2 h before being killed. `test_ro.py` therefore skips every
ring-enabling test under `GATES=yes`, and `ro_meas` gates the ring
enables with `rst` so an unresolved FSM state cannot light a ring in a
netlist that has no delays to damp it.

What that leaves for silicon-adjacent confidence, in increasing cost:
the read-out path is fully GL-tested with the rings dark; an
SDF-annotated GL run would give a real (if pessimistically modelled)
frequency; and the number that actually settles the question is the die.
An SDF run against our own `own.lib` timing is worth doing once in phase
4 precisely because it is the last prediction before silicon.

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
