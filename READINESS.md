# Tapeout readiness — vertical-slice

Audited 2026-08-02 against HEAD, by re-deriving each finding from the repo
rather than reading the previous verdict forward. Written because this is now
**the last ASIC tapeout on this project** (user directive 2026-08-02): console
and koti are FPGA targets, ServoCtl-8 and TinyRV32 are finished portfolio
pieces, CORDIC-1 is already submitted and paid. There is no second chance and
no other vehicle for the physics→cells→silicon claim.

## Verdict: **the measurement is fixed; one signoff item and the red badge remain.**

Updated 2026-08-02 (second pass). H3 and H4 are closed in the RTL and the
netlist is regenerated; B2 turned out to be **misdirected** — the signoff it
said was missing is present, enforced and passing on the submitted build, and
what was actually missing was anyone reading it. Two numbers in the previous
pass were also wrong and are corrected below.

| # | Finding | State |
| --- | --- | --- |
| B1 | Submission path built the foundry-cell chip, not the all-own one | ✅ **FIXED** |
| H3 | Buffers loading the ring oscillators | ✅ **FIXED** — 0 on ring nodes, 0 dangling, audited in CI |
| H4 | Ring select and window length are live during a measurement | ✅ **FIXED** — latched at arm, test proves it |
| B2 | "No top-level LVS/DRC signoff on the all-own GDS" | ✅ **NOT A GAP** — it runs, is enforced, and matches uniquely; now asserted in CI |
| M9 | 4 max-cap violations at the `max_*` corners | ⛔ **OPEN — new**, found while closing B2 |
| — | `gds` workflow red since 2026-07-25 | 🟡 **DIAGNOSED, not fixed** — upstream defect, not the chip. Still blocks submission |
| M5 | Documented read sequence permits a torn 24-bit count | ⛔ open (not re-verified) |
| M6 | Prescaler in the RO clock domain has no generated-clock constraint | ⛔ open (not re-verified) |
| M7 | `ring_prediction.py` may sum cell delays only, not interconnect | ⛔ open (not re-verified) |
| L8 | User-facing text quotes one PVT although `lib.lock` pins three | ⛔ open (not re-verified) |

**Still do not pay**: the fixes need one green `gds` run to be real, the red
badge blocks submission on its own, and M5-M7/L8 have never been checked.

---

## B1 — FIXED, and it was the important one

Codex found that `.github/workflows/gds.yaml` — the path TinyTapeout actually
submits from — built the **foundry-cell reference**, while the all-own build
lived in `harden.yml` and was never packaged. Paying against the green badge
would have bought a die whose ring oscillators were `sky130_fd_sc_hd__*`: the
zero-foundry claim, the entire reason this chip exists, false with both badges
green.

Fixed in `603feca`, `bf04162`, `0081d14`. Verified at HEAD: `src/config.json`
carries the ALL-OWN block, `gds.yaml` runs `tools/verify_lib.py` against
`lib.lock` and then a zero-foundry audit that greps the **submitted** netlist
for `sky130_` and fails loudly if it cannot find a netlist at all — a check
that cannot pass vacuously.

## The red badge — CI plumbing, not the chip

The flow completes all 68 steps, LVS and Report Manufacturability included.
Then `tt-gds-action`'s summary step runs, under `bash -e`:

```
LINTER_LOG=(runs/wokwi/*-verilator-lint/verilator-lint.log)
cat $LINTER_LOG
```

`RUN_LINTER: 0` makes LibreLane skip `Verilator.Lint` entirely, so that
directory never exists, `cat` exits 1, and the whole **Build GDS** step fails
after the work is done — taking `precheck`, `gl_test` and `viewer` with it.
Confirmed still present upstream by a fresh dispatch today (run `30748353796`,
identical failure).

**Two workarounds were tried and both are dead ends. Do not repeat them:**

1. `RUN_LINTER: 1` plus `Checker.LintErrors` / `LintWarnings` /
   `LintTimingConstructs` set false — LibreLane answered *"An unknown key … was
   provided"* for all three. Those are step IDs, not config variables. The
   linter then ran (the log appeared, which is what the `cat` needed) but
   emitted `%Error-MODMISSING` per own-cell instance: a gate netlist naming
   `INV_X1`/`NAND2_X1`/`NOR2_X1` has no module bodies in scope. Run
   `30748790446`.
2. …plus `EXTRA_VERILOG_MODELS: ["dir::../sim/own_cells.v"]` to supply those
   bodies. MODMISSING went to zero — but that variable is consumed by **OpenSTA
   as well as the linter**, and behavioural models are not valid STA input. The
   flow died *earlier* than before, at `STA (Pre-PnR)`. Run `30748956528`.

Reverted to `RUN_LINTER: 0`, the setting that builds a **correct** chip. Correct
beats green. The real fix is either an upstream guard on that `cat`, or
synthesis-only blackbox stubs that OpenSTA will also accept.

**This does block submission** — TinyTapeout gates on the workflow being green.
It is not, however, the thing to fix first: H3 below requires regenerating the
netlist anyway, so a fresh green run is needed regardless of what is done here.

## H3 — buffers on every ring node. **FIXED 2026-08-02.**

**Two numbers in the first pass were wrong**, and both were wrong the same
way: they came from matching *names* in the netlist text, which is the exact
weakness that let the defect through in the first place. Re-derived from the
instance→net→load graph, with pin directions read from the pinned liberty:

| claim (first pass) | actual |
| --- | --- |
| 112 `BUF_X2`, *all 112* with unread outputs | 112 total: **96 drive nothing**, 16 legitimately drive `uio_oe`/`uio_out` pin bits |
| **87** hanging off ring-stage outputs | **93** — i.e. *every stage of all three rings*, not a subset |

The 87 came from grepping for nets named `*u_stage.y*`; six stages have their
output net named otherwise, so a name-based recount missed them. The harm was
therefore slightly worse and much more uniform than reported: not "most of the
ring", but every single node of it.

**Root cause, located and then measured.** `ro_ring.sv` marked the ring bus
`(* keep = "true" *)`. That kept each `n[i]` as a wire distinct from the stage
output driving it; `insbuf -buf BUF_X2 A Y` (flow/make_hardening.py) then
turned every one of those aliases into a real buffer, and `keep` protected the
buffers from `opt_clean`. Five yosys variants, all measured rather than
argued:

| variant | BUF_X2 | on ring nodes | dangling | `assign`s |
| --- | --- | --- | --- | --- |
| HEAD (insbuf, `keep`) | 112 | **93** | 96 | 0 |
| + `opt_clean -purge` | 109 | **93** | 93 | 0 |
| drop `insbuf` | 0 | 0 | 18 | 7 |
| drop `keep` | 19 | 0 | 3 | 0 |
| **drop `keep` + purge** | **16** | **0** | **0** | **0** |

The second row is the important one: **purging alone removes none of the 93**,
because `keep` is what protects them. And every variant still synthesises all
93 stage cells, which settles the fear that the attribute was load-bearing —
`ro_ring.sv`'s own comment already said a liberty cell instance is opaque to
yosys, and it was right.

**Fix**: drop the attribute, add `opt_clean -purge` after `insbuf`. Result —
2764 cells, 16 `BUF_X2` (all driving chip output pins), **0 on ring nodes, 0
dangling, 0 assign statements**; rings intact at 93 stage cells.

**The audit is now fanout-aware** (`tools/audit_netlist.py`, wired into
`make_hardening.py` and `gds.yaml`). It builds a driver/load graph with pin
directions taken from `lib/own_hardening.lib`, and asserts: zero foundry
cells, the ring census, **no cell output that drives nothing**, and **each
ring stage drives exactly one next stage plus the 3 documented taps**. The old
census could not have failed on this — the buffers are named `_4906_` and a
count cannot see a load.

## (superseded, kept for the record) H3 as first written

Re-derived independently from `harden/vslice_gates.v` at HEAD by parsing every
instance and counting net occurrences:

```
BUF_X2 total          : 112
  with unread output  : 112     (every .Y net appears exactly once — at its driver)
  ...loading a ring stage output : 87
```

Cell census of the submitted netlist: 1089 NAND2_X1, 904 NOR2_X1, 347 INV_X1,
274 DFF_X1, **112 BUF_X2**, 78 TIE_X1.

Each ring stage therefore drives the next stage **plus** a buffer input and its
route. Silicon reports a slower ring; that number gets written down as the
propagation delay of the named cell; the delay published as "measured" is the
delay of a cell **plus a parasitic load that only exists because the resizer
put it there**. The whole value of this chip is that the number is trustworthy.

**Why nothing caught it.** The zero-foundry audit keys on instance *name*:

```python
for cell, inst in re.findall(r"^\s*(\w+)\s+(\S*u_stage\S*)\s*\(", text, re.M):
want = {"INV_X1": 30, "NAND2_X1": 32, "NOR2_X1": 31}
```

The buffers are named `_4906_`, `_4909_`… so they never match, and the check
compares cell-type *counts* — never fanout, never connectivity. It passes with
all 112 attached. **A count-based audit cannot see a load.**

Note the netlist file has not changed since 2026-07-22, i.e. this is the same
netlist the review looked at, and B1's fix means it is now the one that ships.

## H4 — selection is live during a measurement. **FIXED 2026-08-02.**

`sel` and `win_long` are now latched into `sel_q`/`win_long_q` on the
`S_IDLE → S_WARM` transition, and everything downstream — the ring enables,
the `ro_clk` mux and `win_top` — reads the latched copies. Arming is the only
place the live inputs are read.

The header comment that asserted *"`sel` is only ever changed with the FSM
idle"* has been corrected too: it was a hope about the operator stated as a
property of the design, and it is the reason nobody looked.

`test_selection_is_latched_at_arm` arms on INV, then swings `sel` across every
other value **including off** and flips the window bit mid-window, and asserts
the count is unchanged. **Verified to have teeth**: reverted against the
pre-fix RTL it fails with `still busy: the window length was taken from the
live switch, not the one latched at arm time`; against the fix it passes.
Whole suite 8/8, plus 9/9 bring-up.

One trap worth recording for anyone writing a similar test: `run` is a level,
so holding it high past the end of the window re-arms the FSM immediately and
`busy` reads 1 for an honest reason. The test drops `run` just before the
window closes, exactly as the existing `measure()` helper does — the first
draft did not, and failed against the *fixed* RTL.

## (superseded, kept for the record) H4 as first written

`src/ro_meas.sv:125-165`: `S_IDLE` enters `S_WARM` on `run && sel != 0`, but
**nothing captures `sel` or the window length**. `S_WARM` and `S_MEAS` keep
reading the live inputs, so a hand on the DIP switches mid-measurement changes
which ring is being counted and how long the window is, and the result is
reported as valid.

The cocotb suite and the virtual die in `bringup/test_bringup_host.py` both
model selection as captured-at-start, so neither can see this.

**Fix is small**: latch `sel` and `win_top` into registers on the
`S_IDLE → S_WARM` transition and use the latched copies in `S_WARM`/`S_MEAS`.

## B2 — **not a gap. The signoff exists, is enforced, and passes.**

Re-derived 2026-08-02 from the log artifact of run `30749148303` (commit
`2312cf2`) rather than from the config comment. B2 cited
`harden/config.json:84-88` — but **that file builds a bare die that is never
submitted** (no IO placement, no PDN, no tile template; `src/config.json` says
so explicitly). The chip that ships is built by `tt-gds-action` from
`src/config.json`, which disables none of it. On that build:

```
62-netgen-lvs   Final result: Circuits match uniquely.
                7026 devices / 3070 nets — equal on both sides, per cell type
                all 45 top-level pins equivalent
                ERROR_ON_LVS_ERROR = True, enforced by 63-checker-lvs
                design__lvs_*__count = 0   (all seven metrics)
58-magic-drc    magic__drc_error__count = 0
43-checker-trdrc route__drc_errors      = 0   (converged 2720 -> 0 over 35 iters)
                antenna 0 / PDN 0 / max_slew 0 / max_fanout 0
```

And netgen runs it **with `-blackbox`**, loading only the sky130 SPICE models,
so the own cells are black boxes: this is precisely the "hierarchical LVS with
the cells as black boxes" that the first pass proposed as the fix for B2. It
compares the magic-extracted GDS against the post-P&R netlist — the comparison
that catches a missing via, an open net or a LEF-to-GDS pin mismatch, which is
exactly what cell-level LVS in `stdcells` structurally cannot see.

Why it looked open: the config comment about magic's CIF read emitting "tens
of thousands of phantom errors" is true of the **bare-die** build, and was read
as if it applied to the tapeout. The comment now says which build it describes.

**What was genuinely missing was that nobody read the result.** It sat in a
984-file log artifact behind a red badge caused by an unrelated upstream `cat`.
`tools/check_signoff.py` now runs in `gds.yaml`, prints every signoff number,
and fails on a regression — including an anti-vacuity guard (a unique match
over fewer than 2000 devices is refused, because a check that passes over
nothing is what blocker 1 was).

## M9 — max-cap violations. **NEW, open, but NOT on the measurement path.**

`design__max_cap_violation__count` was 4 at `2312cf2` and is **6 at
`f2737a3`** — the H3/H4 fixes re-mapped the netlist, so these are different
nets, not a worsening of the same ones. Everything else in signoff is zero.
Caught automatically by `check_signoff.py` on its first real run, which is
what it is for.

Named, from `51-openroad-stapostpnr/*/checks.rpt` (worst corner shown):

```
max_ff_n40C_1v95        limit      cap      slack
clkbuf_0_clk/Y          0.100    0.1149   -0.0149   clock buffer
max_cap15/Y             0.100    0.1126   -0.0126   OpenROAD's own repair buffer
max_cap27/Y             0.100    0.1075   -0.0075   ditto
_3140_/Y                0.100    0.1032   -0.0032   logic cell
wire23/Y                0.100    0.1016   -0.0016   wire-repair buffer
max_cap24/Y             0.100    0.1004   -0.0004   ditto
```

Two things this settles:

- **No violator is a ring node, at any of the nine corners.** The instrument
  is unaffected. `check_signoff.py` now asserts this specifically rather than
  counting: a max-cap violation on a ring node is a loaded oscillator, i.e.
  the H3 failure by another route, and a count cannot tell that apart from
  "the clock tree is 1.5% over".
- **The earlier guess was wrong**: the limit being applied is `0.100`, which
  is the own library's declared `max_capacitance` — *not* `CTS_MAX_CAP` 0.05.
  So this is not a self-inflicted tight constraint; it is the clock tree and
  OpenROAD's own max-cap repair buffers failing to fully close against the
  drive strength our BUF cells actually have.

Severity: worst overage 14.9%, most under 3%, all on the clock/repair path.
Real, worth closing before silicon, not measurement-corrupting. Likely levers:
a stronger `CTS_ROOT_BUFFER`, or more clock-tree levels.

## The zero-foundry audit does not run when the badge is red — **fixed**

Found while wiring the above: `gds.yaml`'s zero-foundry step — the whole of
blocker 1's fix — had no `if:` condition, so GitHub skipped it whenever
`Build GDS` failed. `Build GDS` has failed on every run since 2026-07-25 for
the unrelated upstream reason, which means **B1's guard has been silently
inert for eleven days, on exactly the path it was written to protect.** The
flow completes all 68 steps and writes the netlist before that failure, so
the audit can and should still run. All three audit steps now carry
`if: success() || failure()`.

## (superseded, kept for the record) B2 as first written

`harden/config.json:84-88` disables `RUN_KLAYOUT_XOR`, `RUN_KLAYOUT_DRC`,
`ERROR_ON_MAGIC_DRC`, `ERROR_ON_ILLEGAL_OVERLAPS` and `ERROR_ON_LVS_ERROR`.

That was **deliberate and documented**, not an oversight: magic's extraction of
the own cells throws thousands of phantom errors and netgen LVS rides on that
same extraction, so cell-level LVS was done in `stdcells` against the PDK deck
instead.

Sound for the *cells*; it does not cover the *routed macro*. Cell-level LVS
cannot see a missing via, an open net, a LEF-to-GDS pin mismatch, or what
`heal_hvtp.py` did after streaming. Re-enabling LVS would just drown in phantom
errors — the fix is a connectivity check that works on own cells: hierarchical
LVS with the cells as black boxes, or extracted-netlist vs `vslice_gates.v`.
Failing that, a written waiver from whoever accepts the risk.

## What Codex explicitly cleared

Worth recording so it is not re-litigated: `S_WARM`/`S_MEAS` run exactly 256
and 2^W clocks; 24-bit overflow would need ~102.4 GHz; enable polarity is
correct through all three first-stage flavours; the resetless prescaler is
cleared by warm-up clocks and masked outside `S_MEAS`; `uo` has a single muxed
driver. And `src/cordic.sv` is byte-identical to `b646d057:src/cordic.sv`
(sha `8b399b1be922d0914ac08b628410a3683eb2c698`) — **the fabricated RTL is
intact**, which is the premise the whole comparison rests on.

## What is left, in order

1. ~~H3~~ ✅ ~~H4~~ ✅ ~~B2~~ ✅ — done 2026-08-02, see above.
2. ~~One green `gds` run~~ ✅ **the flow itself is confirmed clean on the new
   netlist** (run `30752441492`, commit `0a86598`): LVS *Circuits match
   uniquely* 6958 devices / 3028 nets, magic DRC 0, routing DRC 0,
   antenna/PDN/slew/fanout 0, zero-foundry clean on **both** `nl.v` and
   `pnl.v`, and the fanout audit passes. All three audit steps green. Local:
   8/8 cocotb, 9/9 bring-up. `harden` (bare die) also green at `f2737a3`.
   The **badge is still red** — item 3 — because `Build GDS` dies after the
   flow finishes. That is now the ONLY thing between this repo and a green
   submission path.
3. **The red badge.** Upstream `tt-gds-action` defect, unrelated to the chip,
   and it blocks submission on its own. ⛔ Do NOT retry the linter-config
   route — two workarounds are burned and recorded below. Honest routes: an
   upstream issue/PR, or synthesis-only blackbox stubs OpenSTA also accepts.
4. **M9** (4 max-cap violations) — diagnose; probably `CTS_MAX_CAP` 0.05 vs
   the library's own 0.100, but that must be measured.
5. **M5-M7, L8** — never independently verified. M5 (torn 24-bit read) is the
   one that could corrupt a reading in the same silent way H4 could.
6. Re-run the Codex bridge on the result before paying.

**Nobody should pay against this repo until 2-5 are closed.** The measurement
itself is now sound, which it was not this morning.
