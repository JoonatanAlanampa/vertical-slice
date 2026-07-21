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

### Phase 1 — tile budget: DECIDED, 1x2 (measured, see phase 3)
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

### Phase 3 — all-own hardening: GREEN (2026-07-21, lib-v1.0)
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

**The 1x1 question is settled, by measurement: it does not fit.** The 1x1
was attempted first and global placement refused it outright —
`GPL-0301, utilization 108.499 %`, before a single clock buffer or hold
fix existed. 14 094 µm² of logic against a ~12 990 µm² core is not a
density-knob problem, and the trims in phase 1 (~75 µm² between them)
are nowhere near the ~1 100 µm² gap. **This chip is a 1x2**, and
`info.yaml` was right from the start. At 1x2 the logic sits at 45.2 % of
the core, which leaves genuine room to add test structures rather than
shave them.

The library also **changed the RTL**, which is the honest cost of building
on cells you designed yourself: `DFF_X1` has no reset pin, so the
ring-domain prescaler could not keep its async reset. It is now cleared
during warm-up (when the ring is, by construction, running) and its MSB is
masked outside the measurement window so an un-cleared power-up state
cannot reach a pin. Side benefit: the start phase is deterministic, and
the three rings now read identical counts instead of differing by one.

**Result — first 1x2 attempt, green end to end** (run 29854238836):

| | |
|---|---|
| placed std cells | 3450 (2804 logic + CTS, hold, taps, fill) |
| utilization | 47.6 % of the 1x2 core |
| setup slack | **+10.49 ns** worst corner (20 ns clock) |
| hold slack | **+0.012 ns** worst corner |
| antenna violations / diodes | 0 / 0 |
| **signoff DRC (official KLayout deck)** | **0 violations** |
| foundry cells | **0** — audited on the PLACED netlist |
| ring stages after P&R | 30 INV_X1 / 32 NAND2_X1 / 31 NOR2_X1 |

The audits are the part that matters. P&R is exactly where a flow inserts
cells nobody asked for — tie cells, hold buffers, CTS buffers, fill — so
the zero-foundry claim is checked *after* placement, on the netlist that
would be streamed out, not on the one synthesis produced. Same for the
rings: 93 stages in, 93 stages out, right flavors.

Nothing about the ring oscillators upset STA in practice — the loop is
broken at the enable gate, so there is no timing arc through it and CTS
had no reason to touch it. The exception knobs stayed unused. (Left
standing in case a future library or a longer ring changes that.)

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

What that leaves for silicon-adjacent confidence: the read-out path is
fully GL-tested with the rings dark, and the rings themselves are timed by
the SDF-annotated run below.

#### The prediction — GREEN (2026-07-21)

The all-own netlist, post-P&R SDF back-annotated, running the real read-out
protocol. This is the last prediction that exists before the die, and it is
what bring-up compares against:

| ring | stage t_plh / t_phl | period | f_ring | count (short window) |
|---|---|---|---|---|
| INV (30x INV_X1 + 1 NAND2) | 42.5 / 32.8 ps | 2.259 ns | **442.7 MHz** | **283** |
| NAND2 (31x NAND2_X1) | 44.6 / 45.2 ps | 2.784 ns | **359.2 MHz** | **230** |
| NOR2 (31x NOR2_X1) | 92.2 / 35.7 ps | 3.967 ns | **252.1 MHz** | **161** |

`flow/ring_prediction.py` computes those from the SDF; `test/run_gl_own.py`
simulates the netlist, and the instrument reports **283 / 230 / 161** — the
predictions exactly, through the prescaler, the synchronizer, the window
counter and the byte mux. Ordering INV > NAND2 > NOR2, the physically
sensible one: a NOR2's series PMOS stack makes it slowest, and its 92 ps
rise against 36 ps fall is that asymmetry, measured.

**The read-out design survives real frequencies.** The prescaler was sized
for a ~320 MHz ring; the fastest is 443 MHz, so the divided rate is
1.73 MHz against a 25 MHz sample clock — inside the f_clk/4 the crossing
needs. The long window gives 41k-72k counts, comfortably inside 24 bits.

Three things this phase caught that RTL simulation could not:

1. **`-gspecify` is not optional.** Without it icarus silently discards
   every `specify` block, skips `$sdf_annotate` and runs at zero delay —
   which for a ring means spinning forever at a single timestamp. It ate
   22 GB before being killed. `run_gl_own.py` now compiles a throwaway copy
   first purely to read the warnings, and refuses to run if annotation
   would be dropped.
2. **Icarus cannot annotate a flat netlist's escaped names.** OpenROAD
   emits the old hierarchy path as ONE escaped identifier; icarus splits it
   on the divider, looks for a scope that does not exist, and leaves the
   cell unannotated — silently, so the run *looks* fine while reporting the
   cell models' default delays. Brackets break it the same way (read as an
   array index). `flow/sdf_sanitize.py` rewrites netlist and SDF together
   so no name contains a dot or a bracket.
3. **The prediction script was wrong, and the simulation proved it.** Its
   first version averaged both NAND2 arcs, but only `A -> Y` is in the loop
   (`B` is the enable leg, tied to its inactive constant). That skewed the
   NAND2 ring by 31 % and put the flavors in the wrong order. Two
   independent paths to the same number is what caught it; either one alone
   would have shipped a confident wrong prediction to bring-up.

**Known limitation, and it belongs to the library rather than this chip:
`own.lib` is characterized at a single PVT** (`tt`, 1.8 V, 25 C). Ask the
flow for ss or ff and the nominal numbers come back — all nine SDF corners
here are byte-identical. So these predictions carry **no corner spread**:
silicon will land somewhere on a PVT curve nobody has characterized, and a
measured-vs-predicted gap cannot be attributed until it is. That is a
stdcells item for a future release, not a blocker here — 10.5 ns of setup
slack at a 20 ns clock absorbs any plausible ss derate, and the ship clock
is 25 MHz regardless.

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
