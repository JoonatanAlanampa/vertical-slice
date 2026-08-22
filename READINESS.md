# Tapeout readiness — vertical-slice

Audited 2026-08-02 against HEAD, by re-deriving each finding from the repo
rather than reading the previous verdict forward. Written because this is now
**the last ASIC tapeout on this project** (user directive 2026-08-02): console
and koti are FPGA targets, ServoCtl-8 and TinyRV32 are finished portfolio
pieces, CORDIC-1 is already submitted and paid. There is no second chance and
no other vehicle for the physics→cells→silicon claim.

## Verdict: **`gds` is GREEN. All four jobs pass, including TT's own precheck.**

Third pass, 2026-08-02/03. The badge that had been red since 2026-07-25 is
green at `c029720`, and so are `test` and `docs`:

```
gds: success   precheck: success   gl_test: success   viewer: success
```

Every audit in the submission path passes with it: zero-foundry on the
submitted netlist, the signoff numbers (LVS unique, DRC/antenna/PDN clean,
`ro_clk` constrained), the connectivity audit of the committed **and** routed
netlists, and — for the first time — a real corner spread.

What that unblocks is the *mechanics* of submitting. It is not by itself a
recommendation to pay; see "What is left" at the end.

✅ **Updated 2026-08-04: M11 is CLOSED, and closing it immediately exposed —
then closed — M12.** The library is re-pinned to `stdcells` **lib-v1.4**, which
measures output transitions by direction instead of by crossing ordinal. The
first honest signoff then failed: **58 max-slew violations at ss** that the
clamped-to-zero slews had been hiding. Those are fixed too, and `gds` is green
at `3df8dc5` (run **30934157150**) with `precheck`, `gl_test` and `viewer`.

⚠️ **M11 was NOT the sign error it was written up as.** The tables were
negative *and exchanged*: every magnitude was present, attached to the opposite
table. `abs()` alone — the fix this file previously implied — would have
shipped **NOR2_X1's rise transition as 15.68 ps when it is 50.87**, a 3.2x
understatement on the cell driving the slowest ring on this die.

| # | Finding | State |
| --- | --- | --- |
| B1 | Submission path built the foundry-cell chip, not the all-own one | ✅ **FIXED** |
| H3 | Buffers loading the ring oscillators | ✅ **FIXED** — 0 on ring nodes in the SYNTHESIZED *and* ROUTED netlists; both audited in CI |
| H4 | Ring select and window length are live during a measurement | ✅ **FIXED** — latched at arm, test proves it |
| B2 | "No top-level LVS/DRC signoff on the all-own GDS" | ✅ **NOT A GAP** — it runs, is enforced, and matches uniquely; now asserted in CI |
| M9 | max-cap violations (clock tree + repair buffers) | ✅ **CLOSED 2026-08-05** — **0 at all nine corners**, was 5 (baseline 8). It was downstream of M15 and needed no knob of its own |
| M15 | `max_fanout` check structurally incapable of failing — the own liberty declared no fanout load at all | ✅ **CLOSED 2026-08-05** — fixed at source in `stdcells` **lib-v1.5**; 22 real violations surfaced, then **0**, independently verified on the shipped netlist |
| M16 | Every `internal_power` table silently discarded by OpenSTA (wrong template namespace) | ✅ **CLOSED 2026-08-05** — `power_lut_template` in lib-v1.5; this chip's reported power was understating by ~32% |
| M17 | **Hold is signed off against a DFF hold constraint of `0.0` that was never measured** | ✅ **CLOSED 2026-08-20** — measured in `stdcells` (**lib-v1.6**) and re-pinned here. It surfaced **3 hold violations = one endpoint**, then closed at **+41.45 ps**. See below |
| M20 | The bare-die `harden` build had silently drifted from the submitted build on **four** settings, so it was never the stand-in it is supposed to be | ✅ **CLOSED 2026-08-20** — aligning them closed hold at **+30.90 ps** and made `design__core__area` **identical** (34255.4). ⚠️ `CTS_MAX_CAP` was **not** the cause; that first answer is recorded as wrong. See below |
| — | `gds` workflow red since 2026-07-25 | ✅ **GREEN** — the linter now runs clean via `CELL_VERILOG_MODELS`, so the upstream `cat` finds its log |
| M5 | Documented read sequence permits a torn 24-bit count | ✅ **FIXED** — doc bug only; hardware and bring-up script were already correct |
| M6 | Prescaler in the RO clock domain has no generated-clock constraint | ✅ **CLOSED, re-measured on `lib-v2.1` 2026-08-22** — all nine views close, band **+694 .. +934 ps**; quote the **1.38x headroom** at the binding corner, not a slack figure. ⛔ The old **1.27x** and the +513..579 ps band are DEAD |
| M13 | `check_signoff.py` had **no timing entry at all** — a green run carried 5 setup violations | ✅ **CLOSED 2026-08-04** — setup/hold violation counts added; the previously-green run now fails |
| M14 | `ro_clk` SDC period table stale (pre-M7 predictions), over-constraining 35-47% | ✅ **CLOSED 2026-08-04** — regenerated from the corrected model; that gap *was* M13's violations |
| M7 | `ring_prediction.py` may sum cell delays only, not interconnect | ✅ **CLOSED** — the quoted prediction was **32-46% optimistic**; now computed from SPEF + a self-consistent slew, per corner |
| M11 | Liberty transition tables negative for inverting cells → STA timed the chip at **zero slew** | ✅ **CLOSED 2026-08-04** — fixed at source in `stdcells` **lib-v1.4** and re-pinned here. Was **negated AND exchanged**, not a sign error |
| M12 | 58 max-slew violations at ss, hidden by M11's clamped-to-zero slews | ✅ **CLOSED 2026-08-04** — repair could not see them (one estimated-parasitic view, no RC corners yet); fixed with repair margin, not a looser limit |
| L8 | User-facing text quotes one PVT although `lib.lock` pins three | ✅ **FIXED** — text corrected, and the stated *reason* was wrong (see M10) |
| M10 | Corner-aware STA was not in effect (0.2% of arcs moved between PVT views) | ✅ **FIXED** — now **98.5%**, max delta 155% |
| M19 | **No cell in the library declares a `min_pulse_width`**, so OpenSTA's min-pulse-width check has no requirement to apply and CANNOT FAIL — however narrow the clock pulse gets. It lands on the prescaler, which is clocked DIRECTLY by the ring | ✅ **CLOSED 2026-08-21** — measured in `stdcells` **lib-v1.7** and re-pinned here; `gds` green with the check passing at all nine corners. ⛔ The **+577.9 ps** binding margin was lib-v1.7's; on `lib-v2.1` it is **+704.6 ps** at `_4880_/CLK` (low), `max_ff`, positive control still firing. See below |
| M21 | **The published ring predictions in `docs/info.md` were computed on `lib-v1.4` and run `30934157150`, and nothing regenerates or checks them** | ✅ **CLOSED 2026-08-21** — regenerated against run `32481579140` (lib-v1.7) and now asserted on every `gds` run by `flow/check_ring_doc.py`. The wiring is the half that matters. See below |
| — | The DFF constraints are "optimistic by an **unquantified** margin" against foundry practice (capture boundary vs degradation criterion) — standing since lib-v1.0, spanning setup, hold and `min_pulse_width` | ✅ **QUANTIFIED 2026-08-21** — at most **+4.7 ps**, and **+0.5 ps** at the corner where hold binds. Recorded, not closed by redefinition. See item 3 of "What is left" |
| M31 | **The re-pin to `stdcells` `lib-v2.0` did not route: `gds` and `harden` both died at `[DPL-0036]`.** The cause was in the LIBERTY, not in placement — `DFF_X1` `cell_fall` at the **ff (hold) corner** held **−7.258…−8.499 ns in 15 of 20 entries** | ✅ **CLOSED 2026-08-22** — fixed at source in `stdcells` **`lib-v2.1`** and re-pinned here. The whole library diff is **one table, fifteen numbers**. See below |
| M32 | **`harden/signoff.sdc`'s `ro_clk` period table was two library generations stale, and it is M14 arriving a second time.** It demanded the ss prescaler close in **2.166 ns** while the ss ring physically runs at **3.116 ns** — a fast-ring/slow-counter pair that cannot occur in silicon | ✅ **CLOSED 2026-08-22** — regenerated from the routed run. It was the only setup violator on the die: one endpoint, `_4886_`, at all three ss views |
| M33 | **`flow/ring_prediction.py` hardcoded the NLDM template name `tbl44`.** `lib-v2.0` renamed it `tbl54` when the 10 ps slew row was added, so the parser silently returned ZERO tables and the prediction died with a `KeyError` three frames later | ✅ **CLOSED 2026-08-22** — the template name is now READ; the parser refuses to return a library it could not read |

✅ **UPDATED 2026-08-21: M19 AND M21 ARE CLOSED TOO, and the signoff now
checks two things it could not check before.** The paragraph below was written
on 2026-08-20; **M19** was found that evening and **M21** the next morning, so
for a day the "open list is EMPTY" claim was false. Both are now closed with CI
asserting them on every run — `gds` + `precheck` + `gl_test` + `viewer` green
at `b5120f4`, `harden` green at `d67f7fb`, pinned to **`lib-v1.7`**.
⚠️ **Read that history as the point, not as a footnote.** Twice now the open
list has been empty and twice a defect of the same shape was found immediately
afterwards — a guard that ran, printed zeros, and was believed. Ten of the
findings in this file are that shape. An empty list is evidence about what has
been looked for, not about what is there.

**M17 AND M20 ARE CLOSED (2026-08-20) and the open list is EMPTY.** Every
must-be-zero metric is zero — including `timing__hold_vio__count`, which for
the first time is zero against a hold requirement that was *measured* rather
than assumed. Max-cap is zero at all nine corners, LVS matches uniquely over
6954 devices, and `gds` + TT's own `precheck` + `gl_test` + `viewer` are all
green, as is the bare-die `harden` build. All eight review-brief questions are
closed, and so are M11, M12, M13, M14, M15, M16, M17 and M20.

⛔ **An empty list is not permission to pay, and this repo has better reason
than most to say so out loud.** Eight of these findings were guards that could
not fail, or numbers that meant less than they looked; the ninth (M20) was
found only because closing the eighth made a build go red. What the signoff
now says is that it is *capable* of saying something. Whether the physics is
right is what the die is for.

### M15 → M9, closed together 2026-08-05 (the whole story in one place)

`design__max_fanout_violation__count` had read 0 on every run this repo ever
produced, and was **structurally incapable of reading anything else**: the own
liberty declared neither `fanout_load` nor `default_fanout_load`, so OpenSTA
summed every net's fanout to 0.0 and `set_max_fanout 10` could not be exceeded
by any circuit. It sat in `check_signoff.py`'s MUST_BE_ZERO list being quoted
as assurance. Fixed at source in `stdcells` lib-v1.5 by one header line.

**It was bigger than a dead check — it was a limit that did not exist for any
tool in the flow.** OpenROAD's `repair_design` has no fanout flag; it repairs
whatever limits it can see, and it could see none. Measured on a 12-sink net,
one variable changed:

```
lib-v1.4:  Found 0 fanout violations,  0 buffers inserted,  13 -> 13 cells
lib-v1.5:  Found 1 fanout violation,   1 buffer inserted,   13 -> 14 cells
```

That is why nets reached 29 sinks unchallenged, and the violators' own names
said so: `max_cap75..83`, `load_slew29..72` and `wire31..82` were buffers
`repair_design` had inserted to fix capacitance and slew, and then loaded with
20-29 sinks apiece because nothing counted them. **The repair pass created the
nets that violated.**

Consequently M9 was never an independent item. Its two remaining violators at
tt were `wire82/Y` and `max_cap79/Y`, carrying **62.08 fF and 57.83 fF of PIN
load** on 29 and 27 sinks against a 100 fF limit. Once the limit existed, the
flow split them itself and both went away.

| | `0935bba` pre-M15 | `19ded23` re-pin | `a13fd30` + CTS margin |
| --- | --- | --- | --- |
| max-fanout violations | 0 *(dead check)* | **22 → 1** | **0** |
| max-cap violations (M9) | 5 | 1 | **0** |
| setup WS | 0.5166 | 0.5021 | **0.5292** |
| instances | 6935 | 6963 | 6953 |

The last net standing was `clkbuf_0_clk/Y` (fanout 16, cap 0.1157) — the top
branch net of the clock H-tree, not a data path and not a ring node.
TritonCTS's own log shows it already honours a fanout of 10 **at the leaves**
(`Stop criterion found. Max number of sinks is 10`, 49 buffers, min *and* max
3 deep). It was closed with `CTS_MAX_CAP` 0.05 → 0.025 — margin, in M12's
shape, because CTS clusters against *estimated* wire while RCX measures the
real thing (~81 fF of that 116 was wire, only ~34 was pin load). **`set_max_fanout`
was not touched and the metric was not removed from MUST_BE_ZERO.** It cost
2 clock buffers and *improved* setup slack at every corner.

Verification, because a 0 from a check that used to be incapable of failing is
exactly what this file exists to distrust: the shipped netlist was parsed
independently — **0 nets above 10, max fanout exactly 10** — and
`check_signoff.py` now NAMES max-fanout violators per corner and fails if any
is a ring node, mirroring max-cap. That reporting was proved by planting a
ring-node row in a real `checks.rpt`, which fails with the ring message.

### M17 → M20, closed together 2026-08-20 (the whole story in one place)

**What it was.** `timing__hold_vio__count = 0` with a worst hold slack of
**1.5 ps**, both computed against a DFF hold requirement of **`0.0` ns** that
had never been measured — a known deferral on the library side whose
consequence here had not been stated: **a hold check against a zero
requirement cannot fail for the reason hold actually fails.** It was the
eighth instance of this project's signature defect, and the apparent 1.5 ps
was not a margin in any case: it sits below OCV, below jitter, and below the
2 ps timestep of the characterizer that produced the library.

**The measurement** (`stdcells` lib-v1.6). Per direction, per corner, in ps —
against `0.00024`/`0.00024`/`0.01978` ns of setup for *both* directions and
`0.0` hold everywhere through lib-v1.5:

| corner | setup rise | setup fall | hold rise | hold fall |
|---|---|---|---|---|
| tt | -1.892 | +20.691 | **+6.653** | -5.554 |
| ss | +19.775 | +43.274 | -11.047 | -17.761 |
| ff | -8.911 | +10.315 | **+12.146** | +0.244 |

`0.0` was **optimistic, not conservative**: this flop captures a rising D
placed exactly on the clock edge. Note also that three of the six hold entries
are *negative* — looser than the placeholder — so a stricter constraint is not
what arrived; four signed, per-direction numbers are.

**What it surfaced.** Re-pinned to lib-v1.6, the submitted run came back with
every must-be-zero metric at zero except `timing__hold_vio__count = 3` — one
endpoint counted once per ff view (TNS equals WNS at all three, and every
non-ff corner reads 0):

  `min_ff -10.10 ps · nom_ff -9.42 ps · max_ff -7.74 ps`, against
  `min_tt +72.13 ps` and `min_ss +245.80 ps`.

The path is `u_cordic.st[3] → NOR2 → NAND2 → _4935_/D`, inside the CORDIC
logic — **not** the ring-oscillator path this die exists to measure. The STA
report states the finding rather than implying it: two paths, same corner,
same file, `library hold time 0.012150` slack **-0.010104 VIOLATED** on the
rise arc and `library hold time 0.000240` slack **+0.016502 MET** on the fall
arc. Under lib-v1.5 both read `0.0` and both passed.

**What was NOT the cause.** `RSZ-0064, "unable to repair all hold checks
within margin"` is the loudest line in the log and it is a red herring:
lib-v1.5 emitted it too (216 endpoints, 8 buffers) and still closed at
+1.53 ps. Repair giving up is chronic for this design. The requirement moved
+12.15 ps and the slack moved -11.6 ps — a near 1:1 transfer, which is what a
correct constraint should do.

**The fix, part 1: margin.** `PL_`/`GRT_RESIZER_HOLD_SLACK_MARGIN`
0.005 → 0.030. The old value was tuned when the requirement was zero.
Affordable here for a measured reason — 1x2 at 53.4% utilization — against
the 322-buffer explosion that happened at 87% on a 1x1. Result on the
submitted build: **`timing__hold_vio__count = 0` at all nine corners, worst
hold slack +41.45 ps at min_ff**, 63 hold buffers, utilization 56.2%, and
repair converging with **no RSZ-0064 at all**.

### M20 — the bare-die build was never the stand-in it is supposed to be. **FULLY CLOSED 2026-08-22.**

✅ **UPDATE 2026-08-22: the bare die now CLOSES.** On `lib-v2.1` the `harden` build (run **32563287295**) signs off at hold WNS **+35.67 ps** and setup WNS **+701.4 ps**. The paragraph below is the lib-v1.6 history and is kept because its diagnosis — that the two builds must place into the same core — is what made this closable; ⛔ do not read its "still does not" as current.

**(history) The bare-die `harden` build did not close on lib-v1.6.**
It went marginally *worse* under a 6x bigger hold margin (-7.62 → -9.02 ps,
buffers 20 → 55), with **WNS pinned at exactly -0.017 on `_4935_/D` from
iteration 250 to the end, identical at hold-margin 0.005 and 0.030**. A number
that does not move under a 6x change in the knob aimed at it is not a tuning
problem, so the search moved to what differs between the two builds.

❌ **First answer, and it was WRONG — recorded because being wrong here is the
point of writing it down.** `harden/config.json` planned CTS against
`CTS_MAX_CAP` 0.05 while `src/config.json` had been halved to 0.025 when M12
was fixed. That drift is real and has been aligned — but it was **not** the
cause: with 0.025 the bare die came back at **-8.97 ps and -261 ps of skew**,
against -9.02 ps and -258 ps before. Unchanged. A plausible mechanism that
survives argument can still be refuted by one run, and this one was.

✅ **What the config diff actually shows.** Four settings exist in the
submitted build and are simply *absent* or different here — three of them the
M12 repair fixes, which were applied to `src/` and never propagated:

| | `src/` (submitted) | `harden/` (bare die) |
|---|---|---|
| `LEFT`/`RIGHT_MARGIN_MULT` | 6 | **2** |
| `DESIGN_REPAIR_MAX_SLEW_PCT` | 40 | **absent** |
| `GRT_DESIGN_REPAIR_MAX_SLEW_PCT` | 40 | **absent** |
| `RUN_POST_GRT_DESIGN_REPAIR` | true | **absent** |

The margin difference is the one that reaches hold: same `DIE_AREA`
(161.00 x 225.76 both), but a different core (35066 vs 34255 um²), therefore a
different placement, a different clock tree, and a different answer to the same
question. **The bare die exists to be a locally debuggable replica of the
shipped build; a replica that drifts on four settings is a second design being
quietly maintained by accident.**

✅ **CLOSED — aligning the four settings fixed it, and the geometry says which
one mattered.** `harden` is green: worst hold slack **-8.97 ps → +30.90 ps**,
zero violations. The decisive change was the floorplan, and it is visible
without inference: `design__core__area` went **35066.1 → 34255.4 um²**, which
is *byte-identical* to the submitted build's, and utilization landed at
**0.5632** against the submitted build's **0.5624**. Once the two builds place
into the same core, they behave the same way.

⭐ **And it independently re-confirms the red herring: `RSZ-0064` was emitted
in this green run too.** Repair still "failed" to reach its margin, and the
design still closed with 30 ps to spare. Three runs now — lib-v1.5 at
+1.53 ps, the submitted build at +41.45 ps, this one at +30.90 ps — have
carried that warning while closing. It says nothing about whether the design
holds.

⚠️ **`clock__skew__worst_hold` is still -267 ps here**, so skew alone never
determined the outcome either. It is a standing property of this design, not a
regression, and it is what makes the design sensitive enough that a 12 ps
constraint decides the result.

⛔ **Nothing about the SUBMITTED artifact ever depended on this**: `harden/`
builds a bare die that is never submitted (this is the same config B2
mis-cited), and the shipped path was green throughout at +41.45 ps.

⚠️ **Underlying, recorded and NOT fixed:** `clock__skew__worst_hold` is
**-259 ps** on this design. That is pre-existing, identical under lib-v1.5,
and a CTS question rather than a constraint one. lib-v1.6 did not create it —
it removed the false margin that was hiding it.

⛔ What was deliberately not done: no restoring `0.0`, no relaxing
`set_max_transition`, and `timing__hold_vio__count` stays in
`check_signoff.py`'s `MUST_BE_ZERO`.

For the first time the timing signoff is capable of failing in both the ways
it needs to be: `design__max_slew_violation__count = 0` is a result rather
than an artefact of clamping (M11/M12), and `timing__setup_vio__count = 0` is
now *checked at all* (M13). The green run of 2026-08-04 reports **19
must-be-zero metrics all present and zero**.

⛔ **That is still not a recommendation to pay.** It is a statement that the
signoff now says something. What it cannot tell you is whether the *physics*
is right — that is what the die is for.

✅ **M6 HAS NOW BEEN RE-MEASURED (2026-08-04, run 30941144711) and the
embargo is lifted — but "266 ps" is dead, and so is quoting a slack figure at
all.** All nine views close with **+517 to +578 ps**, worst at `max_ss`. The
useful number is the RATIO: the counter tolerates a ring **1.27x faster than
predicted** at the binding corner (1.39x at tt, 1.53x at ff). That is what to
check the first silicon measurement against, because the thing that could
break the instrument is silicon ringing faster than the model says — not a
picosecond count against a constraint we chose.

✅ **REGENERATED ON `lib-v2.1`, 2026-08-22 — and the ratio is now COMPUTED
BY A RECORDED METHOD, which is what the ⛔ note below asked for.** The method
was never missing, only never written where anyone looked: `harden/signoff.sdc`
states it — *ring period / (worst `ro_clk`→`ro_clk` arrival + a 70 ps
setup/uncertainty allowance)*. Applied to the green run **32563287238**, it
reproduces the old figures from the old run's arrivals exactly (1.358/0.890 =
1.53x, 1.601/1.150 = 1.39x, 2.166/1.700 = 1.27x), so it IS the original method.
On `lib-v2.1`:

| corner | ring period | counter needs | headroom |
|---|---|---|---|
| ff | 1.774 ns | 1.159 ns | 1.53x |
| tt | 2.183 ns | 1.516 ns | 1.44x |
| ss | 3.116 ns | 2.264 ns | **1.38x** ← binding |

Setup slack in the `ro_clk` domain across all nine views is **+694 .. +934 ps**
(was +513..579 on lib-v1.6). ⭐ The headroom IMPROVED even though every cell got
slower, because the ring slowed *more* than the counter did — the ring is 31
lightly-loaded stages, the counter is not. ⛔ **The 1.27x / 1.39x / 1.53x band
below is superseded**; the ss entry coinciding with the old ff entry at 1.53x
is a coincidence of two different corners.

ℹ️ **(history) RE-EXAMINED ON lib-v1.6, 2026-08-20 — the direction survives, the
exact ratio was flagged rather than silently updated.** M17 was owed this: every
hold *and setup* statement in this file was written against constraints that
were `0.0` / `0.00024`, and lib-v1.6 moved the setup ones too (ss's falling-D
requirement went 19.775 → 43.274 ps). Measured on the submitted run, same
netlist source, only the library changed:

| corner | lib-v1.5 | lib-v1.6 | Δ |
|---|---|---|---|
| max_ss (binding) | +529.2 ps | **+513.2 ps** | **-16.1 ps** |
| max_tt | +529.3 ps | +521.5 ps | -7.9 ps |
| max_ff | +545.7 ps | +547.5 ps | +1.8 ps |

The whole nine-view band moves +529..586 → **+513..579 ps**, tightening at ss
and tt and easing slightly at ff — the sign pattern the measured setup
constraints predict. The prescaler still closes at every view with roughly
half a nanosecond, so **M6's conclusion is unchanged: comfortable, not
marginal.**

⛔ **But do not re-quote 1.27x / 1.39x / 1.53x as if they had been refreshed.**
Those ratios were hand-derived in 2026-08-04 and the method is not recorded
anywhere in this repo or in the flow — reconstructing it from
`period / (period - slack)` with M14's regenerated periods reproduces neither
the old figures nor the old slack band, so any "updated" ratio computed here
would be a new number wearing an old one's name. That is the exact failure
this file exists to prevent. The ratio needs recomputing by its original
method, or replacing with a scripted one; the slack table above is what is
measured and defensible today.
✅ **CLOSED 2026-08-22 by the block at the top of this section**: the original
method was recorded in `harden/signoff.sdc` all along, it reproduces the old
numbers from the old run's arrivals, and the `lib-v2.1` ratios are computed
with it rather than hand-derived.

**What M11 cost, so the size of it is on record.** On stdcells' own CORDIC-1
harden at a byte-identical netlist, correcting the library removed **766 ps of
phantom setup slack** (13.597 → 12.830 ns worst). Here it had been hiding 58
max-slew violations. But the *ring prediction* moved by **under 1%** (tt INV
625.0 → 628.4 MHz on the same model) — because a ring's period sums both edge
delays around the loop, and M11 exchanged which slew drove which edge, so the
total was preserved. Do not read that near-invariance as evidence the defect
was harmless; read it as the one place where the error happened to cancel.
The number now published is **620.6 MHz**, the difference being Q4's tapped
node rather than anything to do with M11.

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

## M12 — 58 max-slew violations. **FOUND AND CLOSED 2026-08-04.**

M11's fix made this appear within one run, which is the whole argument for
having fixed M11: the check that had been reporting `0` reported **58**.

**Where they were.** Per view, post-route (`56-openroad-stapostpnr`):

| | nom | max | min |
| --- | --- | --- | --- |
| **tt** | 0 | 10 | 0 |
| **ss** | 39 | **58** | 20 |
| **ff** | 0 | 0 | 0 |

Nine distinct drivers; the worst, `_2566_/Y`, measured 0.983 ns at `max_ss`
against `set_max_transition 0.750` — and `<=0.750` at `nom_tt`, where it is
not a violator at all. PVT dominates (+29% tt→ss), RC adds ~5% on top.

**Why repair had not fixed them, which is the transferable part.** Repair did
run and did succeed on its own terms: `32-openroad-repairdesignpostgpl` found
24 slew violations and fixed them with 50 buffers. But `repair_design` works
from **one estimated-parasitic view**, and the `min`/`nom`/`max` RC corners do
not exist until RCX at step 54. Signoff checks 3 RC × 3 PVT = 9 views. The
violations lived in views the optimizer structurally cannot see.

Enabling `RUN_POST_GRT_DESIGN_REPAIR` (absent from the flow because librelane
defaults it to `False` — verified by reading `flows/classic.py:139,:271`, not
guessed) proved this rather than fixing it: the step ran, reported *"Found 1
slew violations"*, 0 resized, 0 buffers, area +0.0%, and the netlist came out
byte-identical. It was not being lazy; at the view it can see there is nothing
wrong.

**The fix is margin, not a looser limit.** `DESIGN_REPAIR_MAX_SLEW_PCT` and
`GRT_DESIGN_REPAIR_MAX_SLEW_PCT` raised to 40, so repair targets 0.45 ns at
the view it can see — comfortably under the 0.545 ns the corner spread demands
(0.75 / 1.29 / 1.05). **`MAX_TRANSITION_CONSTRAINT` is untouched at 0.75**:
the signoff limit did not move, only what the optimizer aims at. Cost: 12
extra `INV_X1` in the routed netlist, and max-cap improved 8 → 5 as a side
effect.

**The ring risk was named in advance and checked.** This step inserts buffers,
and H3 was exactly that failure — an `insbuf` pass leaving a dangling buffer
on all 93 ring nodes. `audit_netlist.py` reports `ring census: OK (93 stage
cells)` and `ring node fanout: OK (each stage -> 1 stage; 3 taps)` on **both**
the committed and the routed netlist of the green run.

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

## M5 — torn read. **The hardware was fine; the instructions were not.**

`ro_meas` latches `count` and holds it, and `bringup/vslice_bringup.py`
already drops RUN, waits out the in-flight window, then reads — its docstring
even explains why. So there was never a hardware defect.

`docs/info.md` was the defect. "How to test" said *raise `ui[4]`, wait past
the window, then read the three count bytes*, and never said to lower it,
while the register section on the same page says measurements repeat back to
back while it is high. Anyone following the page — including a future us with
silicon on the bench — reads a torn value. On the short window a new result
lands every 164 us, i.e. between any two byte reads a human or a MicroPython
host will do; on the long window the count spans two bytes, so a tear at a
byte boundary is off by 256 and is the *normal* case, not the unlucky one.
Page fixed, with the reason.

## M6 — **CLOSED 2026-08-02. The domain is constrained, and the counter closes.**

`harden/signoff.sdc` now defines the ring domain, wired as `SIGNOFF_SDC_FILE`
in both configs. The proof that it was genuinely unanalysed before, and the
answer to "can an 8-bit counter run at 914 MHz on our own cells":

| metric | before | after |
| --- | --- | --- |
| `timing__setup_r2r__ws` | **inf** | **0.2661 ns** |
| `timing__setup__ws` | 10.34 ns | 0.2661 ns |
| `timing__setup_vio__count` | 0 | **0** |
| `timing__hold_vio__count` | 0 | 0 |

`inf` is the smoking gun: there were **no register-to-register paths being
timed at all**, which is what an unconstrained clock domain looks like from
the outside — and it reports zero violations, indistinguishable from success.
The 10.34 ns "worst setup slack" everyone had been quoting was the 20 ns `clk`
domain and nothing else.

**The prescaler meets timing at 1.094 ns with 266 ps of slack and zero
violations.** Data path = 1.094 − 0.266 = **0.828 ns**, so the counter holds
up to roughly **1.21 GHz** against rings predicted at 914 MHz — about 32%
frequency headroom. That is the honest answer, and it is comfortable rather
than marginal.

Two caveats that keep it honest:

- The 1.094 ns period is the *predicted* fastest ring, and that prediction is
  known optimistic (M7: no interconnect delay, one stage dropped by the loop
  break). Real silicon ringing faster eats the headroom directly. The 1.21 GHz
  figure is the number to re-check against the first measurement.
- The constraint is **signoff-only, on purpose**. `PNR_SDC_FILE` is untouched,
  so CTS never sees `ro_clk`; if it did it would build a clock tree on the
  rings, which is H3 by another road. The routed-netlist audit (which passes)
  is what proves it stayed away.

`check_signoff.py` now fails if `ro_clk` is absent from the STA clock list, so
the domain cannot quietly become unconstrained again. Verified green on the
submitted path: `[M6] ring clock : ro_clk present in STA clock list`.

Two attempts were needed: `create_clock` takes a pin or a port, and passing
the net killed STA at every corner (run `30755908998`). The pin is derived
from the net at read time rather than hardcoded, because the driver is a
generated instance name that changes on any resynthesis.

## (superseded) M6 as first written — there is no SDC at all

Not "the prescaler has no generated-clock constraint" — the repo contains no
`.sdc` file, no `create_clock`/`create_generated_clock` anywhere, and neither
config sets `SIGNOFF_SDC_FILE`/`PNR_SDC_FILE`. The run log says so directly:
`'SIGNOFF_SDC_FILE' is not defined. Using [the default]`.

So `ro_clk` is not a clock as far as STA is concerned, and **the fastest logic
on this die has never been timed**: `pre` is an 8-bit counter clocked directly
by the ring. At the post-H3 prediction that is a **914 MHz** clock on a DFF_X1
whose own liberty puts clk->Q at ~158-300 ps, with an 8-bit increment in the
same 1.09 ns period.

Note the direction of travel: fixing H3 sped the rings up 1.5-1.7x, so the
prescaler is now **closer to its limit than before this session**, not further
from it. If it miscounts, the instrument reports a wrong frequency and says
`valid` — the same silent-failure class as H3 and H4.

What it invalidates: the clean setup/hold/slew signoff covers the `clk` domain
only. Fix is to define the ring domain (a `create_clock` on each ring output
at its predicted period, with the loop arc explicitly broken) and let OpenSTA
check the prescaler and the synchronizer crossing.

## M7 — **CLOSED 2026-08-03. The prediction was 32-46% optimistic.**

Not a decision to accept a ~3% bias after all: measured properly against run
`30767123276`, the number this page and `docs/info.md` were quoting was wrong
by a third to a half, and **all three causes are properties of the SDF rather
than of the chip.** The prediction is now computed instead of read off, by
`flow/ring_prediction.py --run <run-dir>`.

| ring | was quoted | now predicted (tt) | ff .. ss band |
| --- | --- | --- | --- |
| INV | 914.1 MHz / 585 | **625.0 MHz / 400** | 464.8 .. 732.7 MHz |
| NAND2 | 658.3 MHz / 421 | **459.1 MHz / 294** | 308.7 .. 583.3 MHz |
| NOR2 | 411.7 MHz / 263 | **294.5 MHz / 188** | 212.1 .. 356.3 MHz |

**1. The dropped stage is not a flat 3%.** OpenSTA breaks the combinational
loop, so one stage per ring reports `(0.000:0.000:0.000)`. For NAND2 and NOR2
that is one of 31 identical stages (3.3%); for the INV ring the broken arc is
**its single NAND2 gate — the most expensive stage in that ring** — so it was
4.5% short. Corrected by substituting the same cell type's live arc from the
ring where it is not broken, not by scaling.

**2. The wire was never missing, only unread.** Every ring `INTERCONNECT` entry
is exactly `0.000` while ordinary nets in the same file carry 1-2 ps, and STA
reports ~98 unannotated drivers — the ring nets specifically. But
`final/spef/` has the parasitics all along. Reading them:

- wire cap per loop net: **INV 0.33 fF, NAND2 0.63, NOR2 0.75** (mean), against
  a ~2.1 fF receiver pin cap — **15-35% more load than the delay was computed
  for**;
- the wire's own RC propagation is **nothing**: 14.3 ohm on 0.83 fF is
  ~0.012 ps, four orders below the stage delay. It matters purely as load;
- converted through our own liberty's load axis: **3.0 / 7.2 / 11.5 ps per
  stage**. That conversion is trustworthy even though the slew is not — the
  load slope barely moves between characterized slew rows (2.97 vs 3.27 ps for
  INV_X1), which the tool prints so it can be checked.

**3. STA computed every inverting cell at an input slew of ZERO** — see M11
below, which is the bigger finding and was found by chasing this one. The
prediction now solves the ring's own fixed point instead: each stage's input
slew is the previous stage's output slew, iterated to convergence. It lands at
**14-85 ps** depending on cell and corner, converges from seeds spanning
1 ps to 1.5 ns, and is where a real ring operates.

**What made this findable at all** is that M10 was fixed first. Per-corner
predictions did not exist while every corner carried tt timing.

### (superseded) M7 as first written — CONFIRMED, but the cause is not the one stated

The finding guessed the script forgets interconnect. It does only sum
`IOPATH`, but that is not where the error comes from:

- **Every ring `INTERCONNECT` entry in the SDF is exactly `0.000`** — checked
  across all nine corners (189 ring arcs on the old netlist, 96 on the new).
  There is no interconnect delay to omit. STA also reports ~98 unannotated
  drivers. So *nobody's* prediction includes wire delay, and the script
  cannot fix that by reading a field that is zero.
- **One stage per ring reports zero delay.** A ring is a combinational loop;
  OpenSTA breaks it to build an acyclic graph, so exactly one stage's `A->Y`
  arc is `(0.000:0.000:0.000)`. The sum covers 30 of 31 stages — period ~3%
  short, frequency ~3% high. Confirmed present in every ring, on both the old
  and new netlists.

Both biases point the same way: **the prediction is optimistic**. The script
now prints the zero-arc count on every run and its docstring states both.

## M11 — **the library's transition tables are sign-flipped for every
inverting cell, so STA timed this chip at zero slew.** NEW 2026-08-03, HIGH.

Found while closing M7. It is not a ring problem — it is a **signoff-wide**
one, and it lives in `stdcells`, not here.

**The evidence, in three steps that each stand alone.**

1. **The liberty.** In `own_hardening_tt_025C_1v80.lib`, every value in
   `rise_transition` and `fall_transition` is negative for **INV_X1, INV_X2,
   INV_X4, NAND2_X1 and NOR2_X1**, and positive for **BUF_X1, BUF_X2, BUF_X4
   and DFF_X1**. That split is exactly inverting vs non-inverting: 112 of 176
   values negative, and not one mixed cell. A transition time cannot be
   negative, so this is a characterizer measuring `t(80%) - t(20%)` with fixed
   thresholds regardless of unateness.
2. **What OpenSTA does with it — it does not take the magnitude, it clamps.**
   From the signoff path report at `nom_tt_025C_1v80`, the Slew column:
   `BUF_X1` reports **0.119581**, and **every** `INV_X1`, `NAND2_X1` and
   `NOR2_X1` output on the path reports **0.000000** (20 of 21 driver rows).
   So every inverting cell in this design drives the next one with a slew of
   zero, and each downstream delay is looked up below the fastest row the
   library was ever characterized at.
3. **The magnitudes are right; only the sign is wrong.** `|transition|` rises
   monotonically with load exactly as the delay does (11.3 → 424.7 ps across
   the load axis), and **`BUF_X1` — two inverting stages, positive tables —
   reports 21.5 ps where `INV_X1` reports 11.3 ps at the same load**, almost
   exactly twice. That is the corroboration: the same quantity, measured on a
   non-inverting cell, comes out positive and twice as large.

**Consequences, in descending order of how much they should worry someone
about to pay:**

- **`max slew violation count 0` is vacuous.** A slew clamped to zero cannot
  exceed a limit. That check has never tested anything on an inverting cell,
  which is most of this netlist. **This is the fourth instance of this repo's
  recurring shape — a guard asserting a proxy instead of the property** — and
  the first one to reach a signoff metric.
- **Every setup and hold number is optimistic by an unquantified amount.**
  Zero input slew is the fastest possible lookup. The 25 MHz clock has ~10 ns
  of slack against ~50 ps stage delays, so the *chip* is almost certainly
  fine; what is not fine is that the signoff cannot say so.
- **M6's answer survives in direction but not in margin.** The prescaler was
  found to close with 266 ps of slack against a 1.094 ns ring. Both sides of
  that comparison move: the real ring is ~1.6 ns (slower, helps) while the
  counter's own path is also optimistic (hurts). It very likely still closes —
  do not re-quote 266 ps until it is re-run on a fixed library.
- It does **not** touch the netlist, the LVS/DRC signoff, the zero-foundry
  audit or the connectivity audits. Nothing about what gets fabricated changes.

**The fix is in `stdcells`**: negate the transition tables for negative-unate
arcs in the characterizer, re-release, re-pin `lib.lock` here, re-harden, and
re-run `flow/ring_prediction.py --run`. The prediction above is deliberately
computed with `abs()` on those tables so that it is already the number the
fixed library should reproduce — **which makes it a testable claim rather than
a workaround.**

## L8 — fixed, and the reason given for it was wrong

`bringup/vslice_bringup.py` said the numbers carry no corner spread because
"the library is characterized at tt/1.8V/25C only". That is false: `lib.lock`
pins three per-corner hardening libs and `check_corner_spread.py` measures a
13105% spread *between the liberty files*. The characterization is fine. The
spread is missing further downstream — see M10. Text corrected in both the
script and `docs/info.md`, which now carries the predicted numbers with all
three caveats attached.

## M10 — corner-aware STA was not in effect. **FIXED 2026-08-02.**

**Resolution first; the diagnosis below is kept because it is the reasoning
that found it, and because two of its statements were wrong on the way.**

`CELL_VERILOG_MODELS` is the variable that separates the two roles
`EXTRA_LIBS` was doing at once. `yosys.py` and `pyosys.py` pass it through
`create_blackbox_model()`, so elaborate gets port declarations with no bodies
— which is the only thing `EXTRA_LIBS` was still needed for — and **no
OpenROAD or OpenSTA code reads it**, so nothing overrides the corner-keyed
`LIB`. `EXTRA_LIBS` is now absent from both configs (`929b690`), and the
finding is recorded inline in each.

| | before | after |
| --- | --- | --- |
| arcs differing ff vs ss at signoff | 11 / 4884 = **0.2%** | **98.5%** |
| max delta | 12.4% | **155%** |

⚠️ **Fixing it immediately exposed 5 setup violations at `ss` (WNS −108 ps),
all in the ring domain — and they were artifacts of my own M6 constraint, not
of the chip.** A ring's period is built from the same cells as the counter it
clocks, so the two track: constraining every corner at the tt-derived 1.094 ns
demanded that period of a counter made of `ss` cells, a fast-ring/slow-counter
pairing that cannot occur in silicon. `harden/signoff.sdc` is now per corner,
keyed on `_CURRENT_CORNER_NAME`, from `ring_prediction.py` run against the
newly-real per-corner SDFs: **ff 1.006 / tt 1.116 / ss 1.477 ns** (the fastest
ring at each corner, since `ro_clk` is a mux). An unknown corner falls back to
the globally fastest ring and says so, so the failure mode is over-constrained
and loud. **That constraint was not derivable at all before this fix** — with
every corner carrying tt timing, all nine SDFs predicted the same ring.

`flow/check_corner_spread.py` measures the property directly (a majority of
arcs must move) and runs in `gds.yaml` as well as `harden.yml`, so this cannot
quietly regress on the submitted path. Green at `c029720`.

---

### (the diagnosis, as written while it was open)

Between `ff_n40C_1v95` (-40 C, 1.95 V) and `ss_100C_1v60` (100 C, 1.60 V),
**11 of 4884 cell delay arcs differ — 0.2%.** Ordinary logic cell `_3140_`
reports `(1.201...)` / `(0.411...)` at *both*. Fast and slow silicon cannot
have identical cell delays. Of the 28 lines that differ across the whole
34110-line SDF, most are the `(VOLTAGE)` and `(TEMPERATURE)` header and a few
`INTERCONNECT` arcs on the `clk`/`rst_n` input ports.

**It affects both builds** — the submitted `runs/wokwi` and the bare-die
`harden/runs` measure the same 0.2% at signoff. So the lib-v1.1 "corner-aware
re-pin", believed landed and CI-proven since 2026-07-22, is not in effect for
the own cells where it matters.

**Mechanism — identified.** (An earlier revision of this section called the
`EXTRA_LIBS` hypothesis refuted, on the strength of the pre-PnR number below.
That was wrong; the direct evidence points straight at it.)

Three facts settle it:

1. **The libraries are fine.** 100% of `cell_rise`/`cell_fall` values differ
   between `own_hardening_ff_n40C_1v95.lib` and `..._ss_100C_1v60.lib` (max
   delta 13104%). The characterization is genuinely corner-aware.
2. **The config is fine.** The resolved `LIB` at the signoff STA step keys the
   correct own lib to each corner.
3. **`own_hardening.lib` — the file `EXTRA_LIBS` injects into all nine corners
   — is byte-identical to the tt view.** Same sha256 `47cd2a3cd8c7037c` as
   `own_hardening_tt_025C_1v80.lib`, in `lib.lock` and on disk.

So every corner is handed a second definition of every own cell carrying **tt**
timing, and that is what comes out: at signoff, ff and ss agree with tt on
99.8% of arcs, when the liberty says ff should be faster than tt by up to
5673%. A fast corner reporting nominal delays is the override, not physics.

The two-step measurement, kept because the fix must move both numbers:

| STA step | arcs differing ff vs ss | max delta |
| --- | --- | --- |
| `08-openroad-staprepnr` (pre-PnR) | 290 / 4708 = **6.2%** | **88.0%** |
| `51-openroad-stapostpnr` (signoff) | 11 / 4884 = **0.2%** | 12.4% |

Pre-PnR retaining a little spread is a secondary puzzle, not a refutation —
both numbers are far below what real corner-aware STA produces.

**The obvious fix was tried and it does not work.** Dropping
`own_hardening.lib` from `EXTRA_LIBS` in both configs (commit `9dc1d5e`) fails
immediately, before P&R:

```
ERROR: Module `\NOR2_X1' referenced in module `\tt_um_joonatanalanampa_vslice'
   harden run 30754622184 — yosys elaborate, exit 2
```

So `EXTRA_LIBS` really is what lets `SYNTH_ELABORATE_ONLY` blackbox the own
cells, exactly as `harden/config.json` claimed. It is simultaneously
load-bearing and the cause of M10. Reverted in `4b1cb98`; both configs now
carry the finding inline so the next person does not repeat the experiment.

**So the fix has to separate the two roles.** Three candidates were written
down here; ✅ **the second one is what landed** (see the resolution at the top
of this section):

- a liberty for elaborate that carries **cell and pin definitions but no
  timing tables**, so that even loaded into every corner it has nothing to
  override with (needs checking that yosys accepts it and OpenSTA ignores it)
  — not needed in the end;
- ✅ **or a LibreLane knob that scopes an extra liberty to synthesis only —
  worth grepping the installed librelane 3.0.x for, the way the console
  session found the real `PL_RESIZER_*` variables.** This was the answer:
  grepping 3.0.5 found `CELL_VERILOG_MODELS`, read only by
  `verilator.py`/`yosys.py`/`pyosys.py`. **The lesson generalises — the
  variable that has the property you need is findable by reading the installed
  tool, and two CI cycles were spent guessing at ones that merely looked
  right.**
- ⛔ **not** `EXTRA_VERILOG_MODELS` with blackbox stubs. That was already
  burned during the linter saga: OpenSTA reads the same variable and dies at
  `STA (Pre-PnR)` (run 30748956528).

Whatever lands must be checked with `flow/check_corner_spread.py`, which now
measures the property directly instead of trusting the config.

(That 6.2%-vs-0.2% split was itself nearly missed: a run directory holds SDFs
from several STA steps whose corner subdirectories share names, so the first
version of the strengthened check silently compared the pre-PnR set. It now
selects the post-PnR step and prints which one it used.)

**Why nobody saw it.** `flow/check_corner_spread.py` exists precisely to catch
this and has been passing — because its SDF test asserted only that the files
are not *byte-identical*, and a differing `(TEMPERATURE)` header satisfies
that. A header is not a timing model. The check now compares delay content and
requires that a majority of arcs actually move; it fails on both builds today,
which is the correct answer. It was also only ever run in `harden.yml`, never
against the submitted chip — the same "guard on the wrong artifact" shape as
blocker 1 and the skipped zero-foundry step. It now runs in `gds.yaml` too.

Consequence for the tapeout, **as it stood while this was open**: the "10.5 ns
of setup slack" and the clean hold/slew/cap signoff were **single-PVT results
wearing three PVT labels**, with nothing verified at the slow corner. That is
no longer the case — signoff now runs against real ff/tt/ss timing, and the
slow corner is where the M6 constraint had to be corrected before it passed.

## M21 — the datasheet's ring predictions are two library releases stale, and nothing checks them. **NEW, OPEN 2026-08-21.**

**What it is.** `docs/info.md` publishes a per-corner table of what each ring
should do in silicon — 620.6 MHz / 397 counts for the INV ring at tt, and so
on. It says outright where it came from: *"run `30934157150`, `lib-v1.4`"*.
That is **two library releases and three netlist-changing fixes ago**:

* **lib-v1.5** (M15/M16) gave the liberty a fanout load for the first time and
  **22 real max-fanout violations surfaced and were repaired** — repair inserts
  cells.
* **lib-v1.6** (M17) gave the DFF a measured hold constraint, and closing it
  needed `RESIZER_HOLD_SLACK_MARGIN` 0.005 → 0.030. The shipped build now
  carries **63 hold buffers at 56.2% utilization**, against **53.4%** for the
  run the table came from.
* **M20** realigned the bare-die floorplan, which moved `design__core__area`.

Ring period is set by the ROUTED result — that is the whole lesson of H3 and
M7 — so a table computed from a different routed netlist is not a prediction
about this chip.

**Why it is not merely bookkeeping.** This is the number a person holds the
first silicon against, with no way to re-derive it once the chip is in hand.
Publishing a stale one is the same failure as M7 (a prediction quoted with
more confidence than it had earned) with the arithmetic now correct and the
INPUT wrong instead.

**Why it went unnoticed.** `flow/ring_prediction.py` **is not run in CI** —
grep `.github/workflows/` for it and there is nothing. Every other claim this
repo makes is asserted on every run; this one is regenerated by hand, and was
last regenerated at `5ded3aa`. A number nobody recomputes is a number that
drifts silently, which is this project's signature defect wearing yet another
hat.

✅ **BOTH HALVES DONE 2026-08-21**, and ✅ **REGENERATED AGAIN 2026-08-22 for
`lib-v2.1`** (run **`32562513694`**, re-verified on the green run
**`32563287238`**) — this time together with `bringup/vslice_bringup.py` and
`harden/signoff.sdc`, which descend from the same computation and had been
drifting independently (that was M32). (1) `docs/info.md` is regenerated,
both tables and the provenance sentence. (2) `flow/check_ring_doc.py` is wired into `gds.yaml` and now
asserts, on every run, that the published table still matches the design being
built — comparing both tables, failing loudly if either side parses to
anything other than 9 cells, and resolving the run directory rather than
spelling its name. **The wiring is the half that mattered**; regenerating
alone would just have reset the clock on the same drift.

ⓘ **A useful invariant fell out of it**: the lib-v1.7 prediction is
byte-identical to the lib-v1.6 one, which is independent confirmation that
adding a `min_pulse_width` constraint changed no routing — as it should not,
since it touches no delay table.

**MEASURED 2026-08-21, so this is drift and not bookkeeping.** The guard was
run against the `GDS_logs` artifact of run **32412600538** (`main`, lib-v1.6 —
i.e. the design as it ships today) and disagrees with every published headline
cell:

| ring | ff doc → fresh | tt doc → fresh | ss doc → fresh |
|---|---|---|---|
| INV | 731.8/468 → 732.0/468 | 620.6/397 → 620.8/397 | 457.8/293 → 458.0/293 |
| NAND2 | 584.0/374 → **586.1/375** | 455.0/291 → **456.9/292** | 304.8/195 → **306.0/196** |
| NOR2 | 361.9/232 → **359.0/230** | 291.9/187 → **289.5/185** | 207.4/133 → **205.5/132** |

plus four RC-band counts. **NOR2 moved most** — 2.4 MHz and 2 counts at tt, and
it is the slowest ring, the one whose absolute count is smallest and whose
percentage error is therefore largest.

⚖️ **Honest about the size**: the shifts are ≤0.8% and ≤2 counts, and the
published RC bands are 5-6 counts wide, so no reading that agrees with the new
table would disagree with the old one by more than a band. This is **not** a
number that invalidates the instrument. It is a published prediction that does
not match the design that will be fabricated, in a document whose whole purpose
is to be compared against silicon — and the reason it drifted (nothing
recomputes it) is what makes it worth fixing rather than patching.

⚠️ **Do not quote the current `docs/info.md` numbers as this chip's prediction
until step 1 is done.**

## M22-M25 — what two adversarial review gates found after the list went empty. **2026-08-21.**

The open list was empty, `gds` + `precheck` + `gl_test` + `viewer` were green,
and both gates were asked the payment question anyway. Verdict: **NO-GO**, on
four findings. All four are now fixed. **Both gates independently found M24** —
the strongest signal in the set.

### M22 — the datasheet's headline formula is wrong for the INV ring
`docs/info.md` published `tp = 1/(2*31*f_ring)`. Exact for the NAND2 and NOR2
rings, which are homogeneous 31-stage chains. **False for the INV ring**, which
is 30 `INV_X1` + the enabling `NAND2_X1` (`src/ro_ring.sv`) — an odd-stage ring
needs its enable gate somewhere. Dividing that ring's period by 62 returns a
**30:1 blend**, biased **+0.84 % (ff) / +1.21 % (tt) / +1.68 % (ss)**,
one-signed, on the simplest cell — the one the device model predicts most
directly and on which the physics→silicon claim rests.

For scale, this is larger than every effect this project has judged worth
fixing: the loop-closure tap correction was 1.0-1.2 %, M21's drift 0.03-1.7 %,
the published RC band ±0.8 %. **The page contained every fact needed to correct
it and did not.** `bringup/vslice_bringup.py::stage_delay_s()` had the same
defect, printing the blend as "stage delay" on the bench.

Fixed: the de-blend `tp_INV = (1/f_INV - 1/(31*f_NAND2))/60` is published with
its size and its own residual (~0.01 %, from charging that stage at the NAND2
ring's slew), a per-corner **cell-delay answer key** is published beside it, and
`stage_delay_s()` now returns **None rather than the blend** when no NAND2
reading is available. Asserted by `check_ring_doc.py`.

### M23 — the ring read-out had never been simulated on the netlist that ships
TT's own `gl_test` runs the netlist at **zero delay**, which turns a ring into a
combinational loop, so every ring test skipped: **TESTS=8 PASS=3 SKIP=5** at
`19aef52`. On the artifact being fabricated the only functionally verified
behaviour was the sine engine and "a dark ring reads zero" — the prescaler, the
CDC synchronizer, the window accumulator, the count latch, the byte mux and the
arm latch were all unverified post-route.

`test/run_gl_own.py` exists precisely to close this and **was in no workflow**;
its last recorded run was 2026-07-21 against a pre-H3 netlist. Run on this
artifact it passes **5/5 in ~30 s** — INV 436, NAND2 305, NOR2 193 counts,
correctly ordered. Now a `gl_rings` CI job.
⚠️ **It does not validate the published prediction and must not be quoted as
if it did**: the simulation is annotated from the same SDF the raw prediction
is summed from, so those two agree by construction. The corrected prediction is
a correction *to* that SDF. Only the die settles that.

### M24 — M21's guard did not reach the file that runs on the demo board
`bringup/vslice_bringup.py` carried `PREDICTED_HZ = {625.0, 459.1, 294.5}` MHz —
**two library generations stale** (620.8 / 456.9 / 289.5 shipped), worst error
+1.73 % on NOR2. `PREDICTED_BAND_HZ` was **dead code**: its only mention in the
repo was its own definition, so the script printed a ratio and never said
whether a reading was **in band** — the only judgement separating "the model is
wrong" from "this part is cold".

The mechanism was a comment reading *"Keep them in sync"*. M21 was fixed the
same morning by regenerating `docs/info.md` and pointing a guard at
`docs/info.md`; the sibling file kept a human instruction. **A one-test-per-fix
pattern, caught within hours by both gates.**

Fixed: constants regenerated, the band verdict is live, and `check_ring_doc.py`
now parses this file with `ast` (not import — a CI check should not execute a
bring-up script) and asserts all nine constants. Coverage went **27 → 45
numbers**. Also removed two L8 leftovers still claiming the library has a single
characterized PVT, which `READINESS.md` had recorded as fixed and which were not.

### M25 — a broken blockquote in the permanent datasheet
Two lines of `docs/info.md` lost their `>`, so the torn-read warning ended
mid-sentence on *"Compare them against `own.lib`, against the"* and the
remainder became an orphan paragraph whose "them" had no antecedent twelve
lines away. This is the file TinyTapeout renders into the shuttle datasheet.
Fixed by returning the sentence to the paragraph it belongs to.

### Accepted knowingly, recorded rather than fixed
- **The library is characterized PRE-LAYOUT.** `stdcells/flow/cells.py::spice()`
  emits `.subckt` + MOSFETs + `.ends` — no intra-cell RC anywhere. Silicon will
  read **slower** than predicted by an unquantified, one-signed amount.
- **The prediction is read below its own slew grid.** `ring_prediction.interp()`
  clamps below `index_1[0] = 20 ps`; the INV ring's fixed-point slew lands at
  **14.1 ps (tt)**. Using the table's own slope instead moves the headline ring
  **+5.09 % (tt) / +7.89 % (ff)** — roughly 4x the published RC band, one-signed.
  ⚠️ Note the two halves of the same signoff use **opposite** out-of-range
  policies: OpenSTA extrapolates (measured), `ring_prediction` clamps.
- **No independent ring observer.** `uo[6]`/`ring_alive` is post-prescaler and
  post-synchronizer, so it is independent of the accumulator and the FSM but
  **not** of the two blocks whose failure would silently corrupt the number.
- **The experiment publishes the least discriminating quantity.** Absolute
  readings span 44 % ff..ss; the flavour RATIOS span 8.9 % and are nearly
  P/V/T-immune. There is no on-chip supply or temperature sensor.

⇒ These four are why "the signoff is ready" and "the experiment is ready" are
different sentences. None blocks fabrication; together they mean the number
comes back with a wider and less attributable error bar than the ±0.8 % band on
the page suggests. **Closing them is measurement work in `stdcells`, not a
re-harden.**

## M31 — the re-pin to `lib-v2.0` did not route, and it was never a placement problem. **CLOSED 2026-08-22.**

Re-pinning to `lib-v2.0` (`62a3e8b`, the first library characterized from the
EXTRACTED layout) took `gds` and `harden` red at **`[DPL-0036]` detailed
placement failed** in `rsz_timing_postcts`, and they stayed red through three
more commits. The re-pin itself was correct — `lib.lock` **and** `lib/` both
moved, `verify_lib` passed.

**The signal was a different REGIME, not a degradation:**

| | hold WNS | hold TNS | endpoints |
|---|---|---|---|
| lib-v1.7 (green) | −0.096 ns | −7.652 ns | 237 |
| lib-v2.0 (fails) | **−7.461 ns** | **−1996.785 ns** | 277 |

TNS ÷ endpoints ≈ **−7.2 ns**, i.e. nearly every endpoint sitting at the worst
value — **a uniform offset**. That is the shape of a constant added to every
launch, and it is what should have pointed at the liberty on day one.

### What it actually was

`lib-v2.0`'s `DFF_X1` `cell_fall` (CLK→Q) table at `*_ff_n40C_1v95`:

```
values("-7.25779, -7.23695, -7.14883, 0.40892",   <- 15 of 20 entries
       "-7.26613, -7.24529, -7.15716, 0.41198",      are -7.2 .. -8.5 ns
       "-7.29113, -7.27029, -7.18216, 0.42132",
       "-7.49946, -7.47862, -7.39049, 0.46721",
       "-8.49946, -8.47862, -8.39049, 0.49927");
```

tt (0.250…0.802 ns) and ss (0.405…1.323 ns) were clean. **ff is the hold
corner**, so a −7.4 ns launch arc is a −7.4 ns hold violation on essentially
every endpoint, and hold repair chasing 7.4 ns of delay everywhere is what
flooded the detailed placer. The `stdcells` root cause is **M31**: at ff the
flop's operating point leaves Q at mid-rail (1.2906 V), it settles through
VDD/2 at 0.75 ns, and the characterizer's `targ v(Q) val=VDD/2 fall=1` latched
onto that **power-up settle** instead of the capture at 8.16 ns — an explicit
crossing ordinal is counted from t=0, not from the trig. Only the 100 fF
column escaped, because that load slows the settle past the threshold, which
is why the last column is byte-identical before and after the fix.

### Three things this file recorded that were wrong. They are corrected here.

- ⛔ **"~7.4 ns ≈ 31 ring stages at this library's per-stage delay."** A
  plausible, arithmetically apt hypothesis — and a **coincidence**. There was
  never a ring path involved, `ro_clk` is still correctly absent from the P&R
  SDC, and **no async/ring constraint should be added for this failure.**
- ⛔ **"NOT a corrupt liberty (max table value 1.71 vs 1.70 ns)."** The check
  was run against the **maximum**. The corruption was at the minimum.
- ⛔ **"NOT the clock tree (CTS identical: 51 buffers, 282 sinks)."** True, and
  it was correctly *excluding* a cause — but it was read as evidence that the
  problem must be in placement, which is how three CI cycles went to margin and
  density knobs. Those two remain **measured dead ends** (margin 0.030→0.020
  moved unplaceable 599→584; density 85→65 made it 584→**674, worse**) — but
  they were never near the cause, so they say nothing about this design.

⭐ **The whole diagnosis came out of a raw ngspice log that had been sitting in
`stdcells/out/` since the v2.0 run** — `dffq_ff_n40C_1v95_00_f.log`, which
prints `tcq = -7.25779e-09  targ= 7.50540e-10  trig= 8.00833e-09` next to
`Initial Transient Solution q = 1.2906`. No STA report and no CI cycle were
needed. The lesson is narrow and worth keeping: **when a violation is uniform
across endpoints, read the library before the floorplan.**

### The fix, and its blast radius

`stdcells` **`lib-v2.1`** (`9fe8382`, `harden` green). The entire library diff
from `lib-v2.0` is **one table, fifteen numbers**: both other corners,
`own.lib`, `own_abc.lib`, `own_hardening.lib`, `own.lef` and `own_cells.gds`
are byte-identical, `harden/cordic_gates.v` re-synthesizes to the same md5, and
the setup / hold / `min_pulse_width` searches re-ran from scratch and
reproduced `lib-v2.0` exactly. **This changes what we know about the chip, not
the chip.**

Two physical guards were added in `stdcells/flow/check_monotonic.py`, which had
passed this and was *right* to — it permits negative delay on purpose (early
trip is real for these asymmetric cells; the worst legitimate value is −96 ps)
and the corrupt row is still monotone in load. **(A)** a clocked cell's CLK→Q
cannot be ≤ 0, because it is measured from the edge that causes it and early
trip is a combinational effect; **(B)** no cell's delay may be more negative
than one full input ramp (`slew / 0.6`). Both fire on exactly the 15 corrupt
entries and on nothing else.

🧰 **Both workflows now upload `runs/**` logs and reports on failure.** The
existing artifact globbed `*/final`, which only exists when the flow
**completed** — so on the one occasion the logs were wanted it was 217 bytes of
nothing. That is what made the STA report unreadable and the guessing necessary.

## M32 and M33 — what fixing M31 uncovered. Both **CLOSED 2026-08-22.**

With placement no longer failing, the run reached checks that had not executed
since the `lib-v2.0` re-pin. Two things were waiting there. Neither is a
regression from M31; both had been latent since `lib-v2.0` and were simply
unreachable behind `[DPL-0036]`.

### M32 — the `ro_clk` period table was stale, and it is M14 a second time

`timing__setup_vio__count = 3`, and it was **one endpoint counted once per ss
view**: `_4879_ → _4886_`, both clocked by `ro_clk`, Path Group `ro_clk`
(max −0.069, nom −0.040, min −0.016 ns). tt and ff had **zero** setup
violations, and no other endpoint on the die violated anything.

`harden/signoff.sdc` hardcoded the ring period per corner — 1.358 / 1.601 /
**2.166** ns — computed on `lib-v1.4`. `lib-v2.0` characterized the cells from
the **extracted layout** for the first time; every release up to `lib-v1.7`
had no intra-cell parasitics at all (stdcells M26, ~+20 % one-signed). The ring
and the counter are built from the same cells, so both slowed — but only the
counter's requirement moved, because the ring's period was a **frozen
transcription**. The constraint therefore demanded the ss counter close in
2.166 ns against a ring that runs at **3.116 ns**: the fast-ring/slow-counter
combination that cannot occur in silicon, which is precisely what M14 was.

Regenerated from this run. The headroom the instrument actually has — the
number M6 says to quote, and to hold the first die against:

| corner | ring period | counter needs | headroom |
|---|---|---|---|
| ff | 1.774 ns | 1.159 ns | 1.53x |
| tt | 2.183 ns | 1.516 ns | 1.44x |
| ss | 3.116 ns | 2.264 ns | **1.38x** ← binding |

⚠️ **Every published ring number moved, and they are all regenerated.** The
rings are slower than `lib-v1.7` said — tt INV **620.8 → 455.4 MHz**, and the
tt cell delays **25.67 → 34.94 ps** (INV), **35.30 → 49.84** (NAND2), **55.71 →
71.59** (NOR2). ⛔ **Do not quote the old figures**; they were computed on a
library with no intra-cell RC. `docs/info.md` (three tables),
`bringup/vslice_bringup.py` (two constants) and this SDC all descend from ONE
computation on run `32562513694` and are now regenerated together, because
they drifting apart independently is what M21 and M14 both were.

### M33 — the prediction script could not read the library at all

`flow/ring_prediction.py`'s liberty parser matched `\(tbl44\)` literally.
`lib-v2.0` renamed the NLDM template to `tbl54` when M27 added the 10 ps slew
row, so the parser matched **nothing**, returned cells with empty table dicts,
and `silicon()` died on `KeyError: 'cell_rise'` three frames away from the
cause. It had been broken since the `lib-v2.0` re-pin and nothing noticed,
because `check_ring_doc.py` never ran — the flow was dying in placement first.

⭐ **This is the shape worth keeping**: a defect that hides *behind* another
defect, in a checker rather than in the design, and surfaces as an exception
that names the wrong thing. Fixed by reading the template name instead of
assuming it — restricting to the four table NAMES is already unambiguous — and
`parse_liberty()` now refuses to return a library in which the probe cells have
no NLDM tables, rather than handing back an empty one.

## The two pre-payment review gates, 2026-08-22. **Result: GO, and three things changed because of them.**

Both adversarial gates were run against `2570cd1` before any payment decision:
the submission preflight (is the artifact the chip we think we are buying, and
are the docs true?) and the test-blindspot gate (what can this suite
structurally not catch?).

**Preflight returned GO with no blockers**, having re-derived rather than
trusted: the packaged `tt_submission` netlist/LEF/GDS/OAS contain **zero**
`sky130` content; synthesis stats (2764 cells) match `tools/audit_netlist.py`
on the committed netlist instance-for-instance, so `SYNTH_ELABORATE_ONLY`
really did preserve it; all nine `lib-v2.1` artifacts sha256-match `lib.lock`
against the tag downloaded fresh from GitHub; each ring walks as a **single
closed 31-stage loop** with the only fanout-2 net being `fb`; LVS unique at
7006 devices matching the packaged netlist's own instance count; and the
`2570cd1` and `03fa735` GDS files are **byte-identical apart from the GDSII
timestamp records**.

### Fixed as a result

- **The CORDIC datapath had no shape assertion on the netlist that ships.**
  `test_wakeup_440` measures the DDS rate; `test_code64_and_sigma_delta`
  measures the sigma-delta's one-density. A triangle, a square, or a CORDIC
  with one mis-mapped iteration passes both. So ~2700 of the die's ~2800 cells
  — its stated function — were asserted only to be "periodic and zero-mean".
  `test_sine.py::test_sine_waveform_shape` now least-squares-fits `uo[5:1]`
  (which is `sin_s[15:11]` in offset binary, already on a pin) against an ideal
  sine whose period comes from the RTL constant. **Thresholds measured, not
  chosen**: this design fits to **0.795 LSB** worst residual, a triangle of
  identical amplitude and phase would deviate by **3.36 LSB** and a square by
  **15.92**, so the 1.5 LSB limit has ~2x margin on both sides. It carries **no
  skip guard** and was verified on the actual submission netlist at gate level:
  amplitude 15.97, residual 0.79 LSB, p2p 31 — identical to RTL, which is
  independent evidence that the ABC mapping onto the own-cell library preserved
  the waveform.
- **`harden/signoff.sdc`'s `ro_clk` period is now asserted.** It is the fourth
  descendant of the ring computation and was the only one nothing checked —
  and it had gone stale **twice** (M14, M32), both times fixed by regeneration
  rather than by a check, which is why it came back. `flow/check_ring_doc.py`
  now parses `ro_period_by_pvt` and asserts each entry is the fastest ring at
  that PVT over every RC variant, to 5 ps. Verified both ways: it passes on
  the current file and, with ss set back to the stale 2.166, fails naming
  3.116 ns / 320.9 MHz.
- **`flow/ring_prediction.py` now counts its arcs.** `parse()` collected
  whatever the SDF regex matched and `silicon()` multiplied the mean by the
  *assumed* stage count, so a ring that lost arcs would publish a confident
  frequency computed from a fraction of itself. This is M33's sibling on the
  same file. It now asserts the census against `COMPOSITION` (93 arcs) and
  exits naming the shortfall.
- **Twelve published figures were wrong**, all of them numbers living in a
  sentence rather than in one of the tables `check_ring_doc.py` asserts — M21's
  shape, one layer out. Corrected and re-verified: the blend bias
  (+0.84/+1.21/+1.68 → **+1.16/+1.38/+1.62 %**), the de-blend magnitude
  (1.2 → **1.38 %**), the ring fanout census (29 → **30** nets at fanout 1),
  the ring wire capacitance (0.33-0.75 fF against ~2.1 fF pin → **0.10-1.57 fF
  against 2.62-2.70 fF**, i.e. 4-58 %), the corner spread (98.5 → **98.4 %**),
  the SDC's tolerance ratio (27 → **38 %**, which had contradicted the headroom
  table three lines above it), two stale run citations, and the bring-up
  script's fixed-point slew range (14-85 → **16.8-118.6 ps**).
- ⭐ **`docs/info.md` never stated `ui[5]`'s polarity.** Every other selector
  had a table; the one bit that picks the measurement window had neither table
  nor sentence, so a person at the demo board had to guess it. Now spelled out
  (0 = short 2^12, 1 = long 2^20) with the RTL signal named.

### Refuted — recorded because the alarm was quantitative and wrong

⛔ **"`min_pulse_width` is 2.4-3.3x more optimistic than the foundry's."** It is
not, and the comparison that produced it is invalid. `sky130_fd_sc_hd__dfxtp_1`'s
`min_pulse_width` table is indexed at clock slews 0.01 / 0.5 / 1.5 ns with
values 0.1687 / 0.8333 / 2.5000 ns — and **0.8333333 is exactly 0.5 x 5/3, and
2.5 is exactly 1.5 x 5/3**. The foundry's two upper rows are a formulaic guard,
not silicon. Comparing our *measured* 238.5 ps at 300 ps slew against that
clamp compares a measurement to a placeholder. At the only genuinely measured
row, ours is **136.7 / 179.9 ps against the foundry's 168.7 / 208.2** — i.e.
**1.16-1.23x**, modest and in the direction a faster flop should go. The
published headroom stands.

⚠️ The underlying observation is still worth keeping: at the 300 ps `MPW_SLEWS`
row the boundary pulse is a triangle peaking near **0.74 x VDD**, so it never
reaches the rail, while a real narrow clock pulse at a flop pin is made of two
full-swing edges. That is a parameterization question about the top row of the
table, not a 3x error, and the prescaler's actual CLK slew (~195 ps) sits below
it.

### Refined — the direction matters, and it is the safe one

⚠️ **The DFF's setup+hold aperture IS narrower than the foundry's** (tt rise:
ours 4.5 + 2.1 = 6.6 ps, `dfxtp_1` 50.8 + (−28.5) = 22.3 ps), and
`READINESS`'s "≤ 4.7 ps criterion caveat" does **not** bound that gap — it
bounds only the criterion, measured on our own cell. That correction stands.
✅ **But on HOLD, which is the only check that binds on this die, our library is
MORE pessimistic than the foundry's, not less**: ours demands **+13.06 ps**
(ff, rising D) where `dfxtp_1` declares **−28.5 ps**. A negative hold
requirement is free margin the foundry grants itself and we do not. Setup is
where our aperture is genuinely tighter, and setup has **+10.3 ns** of slack at
a 20 ns constraint on a chip that ships at 40 ns. So the aperture difference
cannot move a conclusion here, and it errs safe on the check that could.

### Accepted, documented, and NOT closed

- 🔴 **M34 — intra-cell RESISTANCE was never extracted. M26 is half closed.**
  All nine `out/par/*.par.spice` contain **zero `R` devices**: a plain magic
  `extract all` writes no resistance network (that needs `extresist`), and
  `rthresh 0` cannot keep what was never extracted. So li1/met1 series
  resistance, contact/via resistance and distributed poly gate resistance are
  still absent — same sign as M26, one-signed and always optimistic, roughly an
  order of magnitude smaller, and **unquantified**. Two docstrings claimed
  otherwise and are corrected (`stdcells/flow/parasitic/README.md`,
  `stdcells/flow/characterize.py`). ⭐ **It moves the answer key, not the
  chip**: the die returns whatever count it returns, and a corrected library can
  be compared against that count afterwards. Closing it means adding
  `extresist` and re-characterizing — a stdcells task.
- **The GL SDF run exercises only `nom_tt`** (`test/run_gl_own.py`), while M31
  was an **ff-only** corruption. Running the three corners is two extra 32-second
  jobs and would give the ss/ff SDFs a consumer that is not the code that
  produced them.
- **`div_live` and the heartbeat are asserted nowhere.** The heartbeat is the
  clock reference every published ring number is computed from at bring-up;
  `div_live` is the datasheet's only independent cross-check on the counter.
- **No provenance binds the liberty to the layout it describes.** `lib.lock`
  freezes the files together; nothing proves the liberty was *derived from* that
  GDS. `lib-v2.1` was also built with `STDCELLS_REUSE_DECKS=1`, and the record
  of which decks were reused is a console line. A provenance header in
  `emit_liberty()` (GDS sha, per-cell extraction sha, reuse counts) checked by
  `tools/verify_lib.py` would close both.
- **`RUN_KLAYOUT_XOR = 0`** — a magic-vs-KLayout streamout discrepancy would be
  invisible. Bounded by both decks passing independently on the same file.
- **The CORDIC is never quiesced during a ring measurement**: `code` still
  drives the DDS in test mode, so ~2700 cells toggle while the ring is counted.
  Worst on-die IR drop is 46.6 µV and the window integrates 4096+ clocks, so it
  is second-order — but the die cannot report a quiet-supply ring frequency and
  nobody should be surprised by that in 2027.

## What is left, in order

`gds` is green, so nothing below blocks the *mechanics* of submitting. These
are the reasons to think before paying.

⛔ **REWRITTEN 2026-08-21. The list that stood here was stale in three of its
four entries** — it still called M9 open (closed 2026-08-05), still said 4 of
the 8 review-brief questions were open (all 8 closed), and still said
`docs/info.md` "quotes a single number" when it has carried a full per-corner
table since `5ded3aa`. The findings table above had been kept current and this
list had not. That is worth noticing in a file whose whole subject is numbers
that mean less than they look.

1. ✅ **M19 — `min_pulse_width`. CLOSED 2026-08-21, margins refreshed for
   `lib-v2.1` 2026-08-22.** Measured in `stdcells` **lib-v1.7** (`harden`
   green, tagged), re-pinned here, and checked on every `gds` run by
   `flow/check_min_pulse_width.py` — nine corners at nine ring periods,
   requirements read at the propagated clock slew, binding margin
   **+704.6 ps** at `max_ff` (⛔ lib-v1.7's +577.9 ps is dead), and a positive
   control that flags 16 ring pins when the requirement is inflated to 9 ns.
   ✅ **The associated WORRY is answered and should not be re-raised:**
   min-pulse-width is **not** the binding limit on the instrument. Measured
   2026-08-21 by running `flow/check_min_pulse_width.py` against the real
   routed design (run `32412600538`) with the lib-v1.7 liberties — so these are
   OpenSTA's own numbers at the propagated clock slew, not an estimate:

   ⛔ **The lib-v1.7 table that stood here is DEAD.** Regenerated 2026-08-22
   from the green run **32563287238** on `lib-v2.1` (`flow/check_min_pulse_width.py`
   runs it in CI at all nine corners, requirements read at the propagated clock
   slew):

   | corner | pulse available | worst requirement | headroom | M6 counter |
   |---|---|---|---|---|
   | ff | 887.0 ps | 182.4 ps | **4.86x** | 1.53x |
   | tt | 1091.5 ps | 267.3 ps | **4.08x** | 1.44x |
   | ss | 1558.0 ps | 406.5 ps | **3.83x** | **1.38x** |

   The counter still binds at every corner, now by a factor of **2.8–3.2**
   (was 3.8–4.4 — both margins grew, the counter's by less). The worst check on
   the die remains `_4879_/CLK`/`_4880_/CLK` — the prescaler flops clocked
   directly by the ring, i.e. exactly the pins this defect is about — and the
   binding margin is **+704.6 ps** at `max_ff` (was +577.9 on lib-v1.7).
   ⚠️ The **1.9x** that prompted the original worry came from extrapolating the
   FOUNDRY `dfxtp_1`; do not re-quote it. And the capture-boundary caveat that
   could have undermined this is measured at **1.05–1.06x** (item 3), not the
   3x once hypothesised.
2. ✅ **M21 — CLOSED 2026-08-21.** Regenerated and now asserted every run.
3. ✅ **The criterion caveat — MEASURED 2026-08-21, and it changes nothing.**
   setup, hold and `min_pulse_width` are all measured at the **capture
   boundary** (the metastability cliff) where a commercial library reports the
   point at which clk→Q has degraded by a fixed fraction, so all three are
   optimistic against foundry practice. That had stood as "an **unquantified**
   margin" since lib-v1.0 — true, unfalsifiable as written, and load-bearing
   for this decision. It is now a number. Re-running the same stimuli against a
   10% clk→Q degradation target, **on our own cell** (which isolates the
   criterion from the cell — comparing against the foundry's `dfxtp_1`
   confounds the two, and that is what made a 3x gap look plausible):

   | corner | setup rise | setup fall | hold rise | hold fall |
   |---|---|---|---|---|
   | tt | +1.8 ps | +4.6 ps | +1.2 ps | +4.7 ps |
   | ff | +0.9 ps | +1.5 ps | **+0.5 ps** | +1.3 ps |

   plus **1.05x** (50 ps clock slew) and **1.06x** (300 ps) on
   `min_pulse_width`. The largest shift anywhere is **+4.7 ps**, in the
   pessimistic direction. Against **+41.45 ps** of worst hold slack — at
   `min_ff`, where the shift is **+0.5 ps** — and M6's **1.27x**, it moves no
   conclusion in this file.
   ⓘ Why it is so small: this flop fails abruptly, so clk→Q is still within 10%
   of nominal a few ps from the cliff and the two criteria nearly coincide.
   **That is a property of this topology, not a general result** — do not quote
   it as a fact about flip-flops.
   ⛔ **Recorded, not closed by a change of criterion**, deliberately: switching
   would redefine three constraints across two repos to buy under 5 ps. Do not
   re-open without a number that says otherwise.
   ⚠️ **NOT RE-DERIVED ON `lib-v2.1`, and stated as an argument rather than a
   measurement.** The +4.7 / +0.5 ps figures were measured on `lib-v1.6`;
   re-running them is its own ngspice characterization. The reason it does not
   gate a decision: the shift is a property of how abruptly THIS flop fails, it
   was one-signed and pessimistic, and even scaling it with the ~+20 % the
   extracted layout added puts it under ~6 ps — against **+35.67 ps** of worst
   hold slack, **+694 ps** of `ro_clk` setup and **+704.6 ps** of
   `min_pulse_width` margin. It cannot flip any of the three. If a future
   session wants it closed rather than bounded, that is a stdcells
   characterization task, not a vertical-slice one.

**What is no longer a reason to wait**: the badge, the connectivity signoff,
the corner spread, the untimed ring domain, and both silent-corruption bugs
in the measurement itself.

## The review brief — what a pre-payment pass must actually answer

Ranked. The first is worth more than the rest combined.

1. ✅ **ANSWERED 2026-08-02 — nothing does. H3 is closed at the routed level,
   not just in synthesis.** This was the question worth more than the rest
   combined, so it was settled rather than left for a reviewer. P&R inserts
   **~155 buffers synthesis never saw** (102 `BUF_X2` + 69 `BUF_X4` + 8
   `BUF_X1` in the routed netlist, against 16 `BUF_X2` in
   `vslice_gates.v`) — CTS, hold repair and max-cap repair. The audit run
   against `final/nl/*.nl.v` and `final/pnl/*.pnl.v` from run `30752441492`:

   ```
   [2] ring census          : OK (93 stage cells)
   [3] no dangling outputs  : OK
   [4] ring node fanout     : OK (each stage -> 1 stage; 3 taps)
   ```

   Not vacuous: the routed netlist still carries 267 `u_stage` references, so
   the check really found the rings. `DIODE_X1` count is **0** — no antenna
   diode was inserted anywhere on the die (antenna violations were 0, so none
   was needed). **The rings reach silicon with exactly one load per node.**

   Now asserted on every run: `gds.yaml` audits the ROUTED netlist as well as
   the committed one. "None this time" is not a property.
2. ✅ **ANSWERED — M10.** The mechanism was `EXTRA_LIBS` injecting the
   tt-identical `own_hardening.lib` into all nine corners; the LibreLane 3.0.x
   variable that separates blackboxing from timing is `CELL_VERILOG_MODELS`.
   Fixed and measured: the spread is **98.5%** of arcs. **Residual question a
   reviewer could still take**: why did pre-PnR retain 6.2% while signoff
   collapsed to 0.2%, if both were fed the same override?
3. ✅ **ANSWERED — M6, and the answer is yes.** The prescaler meets timing
   with **266 ps of slack and zero violations**; the data path holds to
   ~1.21 GHz against rings predicted at 914 MHz, ~32% headroom. It now closes
   **per corner** (ff 1.006 / tt 1.116 / ss 1.477 ns). ⚠️ The margin is
   measured against a prediction known to be optimistic (M7), so silicon
   ringing faster eats it directly — **1.21 GHz is the number to re-check
   against the first measurement.**
4. ✅ **ANSWERED 2026-08-04 — the refutation fails, but it found a 1.2% bias.**
   Read off the ROUTED netlist of run 30934157150, not argued:
   - **Enable leg: not folded.** The dangerous case was yosys constant-folding
     a NAND2 with B=1 into an inverter, which would silently turn the NAND2
     ring into a second INV ring. It did not: all 60 chain stages of the NAND2
     and NOR2 rings take B from **their own dedicated `TIE_X1`** (`_2283_`
     .. `_2342_`, one per stage), and stage 0 of each takes the real enable.
     The INV ring has exactly one B pin, on its stage-0 NAND2.
   - **`fb` and `osc` collapsed into one net with NO buffer on it**, which is
     precisely what dropping `keep` was for — `fb` has no driver instance of
     its own because it is the alias of `n[30]`.
   - ⚠️ **But that alias is a node with TWO loads**, and the prediction assumed
     one. Fanout per ring: 29 nets at 1 load, `fb` at 2 — stage 0 plus the tap
     into `ro_meas`. Charging the second pin costs **1.0-1.2%**, so every
     prediction published before 2026-08-04 was that much fast.
     `ring_prediction.py` now charges it (`extra_tap_delay`) and `docs/info.md`
     is regenerated. **This is the ring-node load H3 was about, arriving by a
     different route** — not a buffer this time, a legitimate observer.
5. ✅ **ANSWERED 2026-08-04 — no, a mid-window `ui[7]` flip cannot corrupt a
   count.** Traced every live input through `ro_meas` and `project.sv`:
   - `sel` and `win_long` are latched at arm (that is H4's fix).
   - **`run` is read ONLY in `S_IDLE`.** `run = test_mode & ui_in[4]`, so
     `ui[7]` does feed it — but dropping either mid-window neither aborts the
     FSM nor darkens the rings (`ring_en` keys off `armed && sel_q`). The
     window completes and latches normally.
   - The **byte-select mux `ui[3:2]`** is combinational on the OUTPUT only and
     never reaches the FSM. Changing it mid-window changes what you are
     looking at, not what is being counted. Reading ACROSS a `count` update is
     the M5 torn read, already closed by the documented procedure.
   - `ui[7]` on the `uo_out` mux likewise only changes what is displayed.
   - ⚠️ **RESIDUAL, and it is the honest answer to "anything else": `ui_in` is
     never synchronized.** `sel`, `win_long` and `run` go straight from the pad
     into `always_ff @(posedge clk)`. This cannot corrupt a count, but if a
     selector is moved in the SAME clock as `run` rises, `sel_q` can latch a
     ring you did not intend — and then `valid` is true, the count is good, and
     only its *label* is wrong. That is the silent class again. It needs no
     gate: the documented procedure already sets the selectors first, and
     `docs/info.md` now says so as an instruction rather than an ordering
     accident.
6. ✅ **ANSWERED — M7, and the answer was no.** It was not a fit yardstick and
   it was not a ~3% question: the published number was **32-46% high**. It is
   now computed from the extracted parasitics and a self-consistent ring slew,
   per corner, rather than summed off the SDF. **Chasing it is what found
   M11.** Residual a reviewer could still take: the fixed-point model assumes
   every stage sees the ring's *mean* wire load, where the real spread is
   0.10-2.08 fF per net.
7. **Can the new audits pass vacuously?** `audit_netlist.py`,
   `check_signoff.py` and `check_corner_spread.py` are what future sessions
   will trust. The defect they exist for survived two earlier audits, so an
   audit that can lie is a first-class bug here. ⚠️ **M11 is a worked example
   arriving from outside that list**: `max slew violation count 0` passed
   every run and meant nothing, because the quantity it checks was clamped to
   zero. Re-read the other signoff metrics with that in mind.
8. **Sweep for the two failure shapes this repo keeps producing**: a guard on
   an artifact that is not the one submitted, and a guard asserting a proxy
   (bytes, counts, names) instead of the property. Three instances found on
   2026-08-02, **a fourth on 2026-08-03 (M11's vacuous max-slew check)**;
   assume there are more.

✅ **UPDATED 2026-08-04: M11 is fixed, and questions 4, 5, 7 and 8 are all
closed** — 7 and 8 by making three audits fail when they should (two could
pass vacuously; one guarded the netlist instead of the GDS), 4 and 5 by
reading the routed netlist and the RTL rather than arguing from the source.
Two real defects came out of it: the ring prediction was 1.0-1.2% fast
because the loop-closure node drives two pins, and `ui[]` is unsynchronized
so a selector moved in the arming clock can mislabel which ring was measured.
Both are closed — the first in the model, the second in the procedure.
**What remains before payment is M9 (max-cap, 5) and re-measuring M6.**

(superseded) ~~Nobody should pay against this repo until M11 is fixed and 4, 5, 7 and 8 are
closed.~~ The measurement circuit is sound and audited, the corners are real,
the ring domain is timed, and the prediction it will be compared against is
now honest. What is not sound is the **timing signoff itself**: it ran with
every inverting cell driving at zero slew, which is most of the netlist. That
is a `stdcells` fix, a re-pin and a re-harden away — and the die it produces
is expected to be identical, because none of this touches the netlist.
