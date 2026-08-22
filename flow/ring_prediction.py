"""What our own timing model says the rings will do in silicon.

This is the last prediction that exists before the die does, and the number
the whole chip exists to be compared against. It has two modes:

    python flow/ring_prediction.py <sdf-dir-or-file> [...]   # raw SDF table
    python flow/ring_prediction.py --run <run-dir>           # what silicon does

**They are not the same number, and the difference is the point (M7).** The
raw table is what the SDF says, which is exactly what a gate-level simulation
of that SDF will reproduce — the two agree by construction, and that agreement
was never evidence about silicon. The `--run` mode corrects the SDF for what it
structurally cannot contain.

A ring's period is one full loop for the rising edge plus one for the falling
edge, so it is the sum of BOTH transition delays over every stage:

    T = sum_stages(t_plh + t_phl)          f = 1 / T

THREE BIASES, all measured 2026-08-03 against run 30767123276, all making the
raw SDF number OPTIMISTIC. The first two are corrected here. The third is not
correctable and is carried as an error bar.

  1. **One stage per ring reports zero.** A ring is a combinational loop and
     OpenSTA must break it to get an acyclic timing graph, so exactly one
     stage's A->Y arc comes through as (0.000:0.000:0.000). Correcting it is
     not a percentage: for the NAND2 and NOR2 rings the missing stage is one
     of 31 identical ones, but for the INV ring the broken arc is **the single
     NAND2 gate** — the most expensive stage in that ring — so the raw number
     is short by 4.5%, not 3%. The fix substitutes the same cell type's
     measured arc, taken from the ring where it is not broken.

  2. **No interconnect at all.** Every ring INTERCONNECT entry in the SDF is
     exactly 0.000 while ordinary nets in the same file carry 1-2 ps, and STA
     reports ~98 unannotated drivers — i.e. the ring nets specifically were
     never annotated. But the parasitics DO exist: `final/spef/` carries them,
     and this script reads them. The wire's own RC propagation is negligible
     (14.3 ohm against 0.83 fF is ~0.012 ps); what matters is that the wire is
     **extra load on the driver**, 0.33-0.75 fF against a ~2.1 fF pin cap, so
     15-35% more load than the SDF delay was computed for. Converted to delay
     through our OWN liberty's load axis, that is worth 3-12 ps per stage.
     The conversion is robust even though the slew is not: the load slope
     barely moves between characterized slew rows (see `--run` output).

  3. **The ring operates below the characterized slew grid.** ~~The input
     slew is unknowable from this library~~ — that was M11, and it is FIXED
     at the source: `stdcells` lib-v1.4 (pinned here since 2026-08-04)
     measures output transitions by direction instead of by crossing ordinal,
     so the tables are positive and correctly labelled. STA no longer clamps
     anything to zero.
     What remains is not a defect but a fact about rings: a 31-stage loop
     settles at 12-87 ps of slew depending on cell and corner, and the NLDM's
     first characterized row is 20 ps. You cannot look up a slew nobody
     measured. So the `self-consistent` column solves the ring's own fixed
     point — each stage's input slew IS the previous stage's output slew —
     and that is the number to quote.

Point either mode at `harden/runs/*` (all-own bare die) or at the submitted
build's run directory to compare the two libraries on the same structure.
"""

import re
import statistics as st
import sys
from pathlib import Path

STAGES = 31
PRE = 8                      # ro_meas PRE_BITS
WIN = {"short": 12, "long": 20}
CLK_HZ = 25e6                # the ship clock
BS = chr(92)                 # backslash; SPEF and SDF escape their names

REPO = Path(__file__).resolve().parents[1]
LIBDIR = REPO / "lib"

# stage composition per ring: the INV ring is 30 inverters + the NAND2 that
# gates it; the other two are homogeneous
COMPOSITION = {
    "INV":   {"INV_X1": STAGES - 1, "NAND2_X1": 1},
    "NAND2": {"NAND2_X1": STAGES},
    "NOR2":  {"NOR2_X1": STAGES},
}

RING_KEY = {"INV": "u_ro_inv", "NAND2": "u_ro_nand2", "NOR2": "u_ro_nor2"}


def ring_of(inst):
    for ring, key in RING_KEY.items():
        if key in inst:
            return ring
    return None


def parse(sdf_path):
    """-> {(ring, celltype): ([rise...], [fall...])} using every IOPATH A->Y.

    Deliberately RAW: the loop-breaking zero arc is left in. `test_ro.py`
    compares gate-level simulation against this, and the simulation is
    annotated from the same SDF, so it reproduces the zero too. Removing it
    here would break an agreement that is real (sim vs SDF) in order to chase
    one that is not (SDF vs silicon).
    """
    text = Path(sdf_path).read_text()
    out = {}
    # SDF writes "(CELL\n (CELLTYPE ...", so the split must not expect a space
    for block in re.split(r"\n\s*" + re.escape("(CELL") + r"\b", text)[1:]:
        m = re.search(r'\(CELLTYPE "(\w+)"\)\s*\(INSTANCE ([^\n]*?)\)', block)
        if not m:
            continue
        celltype, inst = m.group(1), m.group(2)
        if "u_stage" not in inst:
            continue
        ring = ring_of(inst)
        if ring is None:
            continue
        # ONLY the arc the oscillation actually travels. Every stage takes
        # the previous stage on A; B is the enable leg, tied to its inactive
        # constant inside the chain, so B->Y is never in the loop. Averaging
        # both arcs (the first version of this script did) skews a NAND2
        # ring's predicted frequency by tens of percent.
        for io in re.finditer(r"\(IOPATH (\w+) (\w+) (.*)", block):
            if io.group(1) != "A":
                continue
            ds = [float(d) for d in re.findall(r"\(([\d.]+):", io.group(3))]
            if not ds:
                continue
            # one triple means rise and fall are the same number
            rise, fall = (ds + ds)[:2]
            r_list, f_list = out.setdefault((ring, celltype), ([], []))
            r_list.append(rise)
            f_list.append(fall)
    return out


def measured_arcs(per):
    """-> {(ring, celltype): (live_rise, live_fall, raw_rise, raw_fall, n_zero)}

    Both averages, on purpose, because they answer different questions:

      * `raw_*` includes the loop-breaking zero. It is what the SDF says, so
        it is what a gate-level simulation annotated from that SDF will
        reproduce — `test_ro.py` checks exactly this agreement, and it is a
        real one (sim vs SDF), just not a statement about silicon.
      * `live_*` excludes it. The zero is a graph artifact, not a fast stage,
        so this is the number a silicon prediction has to start from.

    `live_*` is None when every arc of that cell in that ring was the break —
    which happens to the INV ring, whose single NAND2 gate is the broken one.
    """
    out = {}
    for key, (rise, fall) in per.items():
        pairs = list(zip(rise, fall))
        live = [(r, f) for r, f in pairs if not (r == 0.0 and f == 0.0)]
        out[key] = (st.mean([r for r, _ in live]) if live else None,
                    st.mean([f for _, f in live]) if live else None,
                    st.mean(rise), st.mean(fall),
                    len(pairs) - len(live))
    return out


# --------------------------------------------------------------- liberty ---

def parse_liberty(path):
    """-> {cell: {'pins': {pin: cap_pF}, 'tab': {'cell_rise': (i1, i2, rows)}}}"""
    txt = Path(path).read_text()
    starts = [(m.group(1), m.end()) for m in re.finditer(r'\n  cell \((\w+)\) \{', txt)]
    cells = {}
    for i, (name, pos) in enumerate(starts):
        body = txt[pos:starts[i + 1][1] if i + 1 < len(starts) else len(txt)]
        pins = {p.group(1): float(p.group(2)) for p in re.finditer(
            r'pin \((\w+)\) \{ direction : input; capacitance : ([\d.]+);', body)}
        tabs = {}
        # The NLDM template name is READ, not assumed. It used to be spelled
        # `tbl44` here, and lib-v2.0 renamed it to `tbl54` when M27 added the
        # 10 ps slew row -- at which point this function silently parsed ZERO
        # tables and silicon() died with a KeyError on 'cell_rise' three
        # frames later. Nothing caught it because the gds run was failing in
        # placement (M31) and never reached check_ring_doc.py. Restricting to
        # the four table NAMES is already sufficient: power tables are
        # rise_power/fall_power and constraints are rise/fall_constraint, so
        # no other group can match.
        for tm in re.finditer(r'(cell_rise|cell_fall|rise_transition|'
                              r'fall_transition) \(\w+\) \{\s*'
                              r'index_1\("([^"]+)"\);\s*index_2\("([^"]+)"\);\s*'
                              r'values\((.*?)\);', body, re.S):
            if tm.group(1) in tabs:      # first timing group is the A->Y arc
                continue
            tabs[tm.group(1)] = (
                [float(x) for x in tm.group(2).split(",")],
                [float(x) for x in tm.group(3).split(",")],
                [[float(v) for v in r.split(",")]
                 for r in re.findall(r'"([^"]+)"', tm.group(4))])
        cells[name] = {"pins": pins, "tab": tabs}

    # Refuse to hand back a library nobody could read. A parser that returns
    # empty on a format change looks exactly like a design with no timing,
    # and the failure then surfaces somewhere that cannot explain it.
    want = {"cell_rise", "cell_fall", "rise_transition", "fall_transition"}
    for probe in ("INV_X1", "NAND2_X1", "NOR2_X1"):
        got = set(cells.get(probe, {}).get("tab", {}))
        if got != want:
            sys.exit(f"ERROR: {Path(path).name}: parsed {sorted(got)} for "
                     f"{probe}, expected {sorted(want)}. The liberty's NLDM "
                     f"group shape changed and this parser did not.")
    return cells


# Set by interp() whenever a lookup lands below the table's first slew row,
# so silicon() can refuse to publish a number computed at the grid edge.
# See the M27 note on interp().
SUBGRID = []


def interp(tab, slew, load):
    """Bilinear on (input slew, output load). Clamped at the grid edges:
    this model refuses to extrapolate, which is the whole point of bias 3.

    ⚠️ CLAMPING IS NOT FREE, AND IT WAS NOT BEING COUNTED (M27). Refusing to
    extrapolate is the right policy, but a clamp still RETURNS A NUMBER --
    the value at the grid edge, presented with the same confidence as an
    interpolated one. The ring's own fixed-point slew had slid to 14.1 ps at
    tt and 11.5 ps at ff against a first row of 20 ps, so the headline
    prediction was the 20 ps value for a stage running at 14. Using the
    table's own 20->50 slope instead moved the INV ring +5.09 % at tt and
    +7.89 % at ff -- against a published band of +/-0.8 %, one-signed, on the
    headline number.

    Note also that OpenSTA EXTRAPOLATES below index_1[0] rather than clamping
    (measured against 2.7.0 while closing M19), so the two halves of the same
    signoff had opposite out-of-range policies on the same tables.

    The fix is a measured 10 ps row in stdcells lib-v2.0, not a change of
    policy here. This records sub-grid lookups so silicon() can fail rather
    than quietly publish one.
    """
    i1, i2, rows = tab

    def axis(idx, v):
        if v <= idx[0]:
            if v < idx[0]:
                SUBGRID.append((v, idx[0]))
            return 0, 0.0
        for k in range(len(idx) - 1):
            if v <= idx[k + 1]:
                return k, (v - idx[k]) / (idx[k + 1] - idx[k])
        return len(idx) - 2, 1.0

    a, fa = axis(i1, slew)
    b, fb = axis(i2, load)
    return ((1 - fa) * ((1 - fb) * rows[a][b] + fb * rows[a][b + 1])
            + fa * ((1 - fb) * rows[a + 1][b] + fb * rows[a + 1][b + 1]))


# ------------------------------------------------------------------ spef ---

def spef_wire_caps(path):
    """-> {net name: total wire capacitance in fF}. `PIN_CAP NONE` in the
    header means these are wire-only, which is exactly the load the
    unannotated SDF delays are missing."""
    txt = Path(path).read_text()
    nm = {m.group(1): m.group(2)
          for m in re.finditer(r'^\*(\d+) (\S+)$', txt, re.M)}
    return {nm.get(m.group(1), m.group(1)).replace(BS, ''):
            float(m.group(2)) * 1000.0
            for m in re.finditer(r'^\*D_NET \*(\d+) ([\d.eE+-]+)', txt, re.M)}


def ring_loop_caps(caps):
    """-> {ring: [wire cap fF]} for the 31 nets the oscillation travels.

    Every net under the ring hierarchy except the enable, which is static
    during a measurement: `<ring>.en` for INV/NAND2, `g_stage[0].b` for NOR2,
    whose enable enters on the first stage's B pin instead.
    """
    out = {}
    for ring, key in RING_KEY.items():
        loop = [c for n, c in caps.items()
                if key + "." in n
                and not n.endswith(".en") and not n.endswith("g_stage[0].b")]
        out[ring] = loop
    return out


def wire_delta(lib, cell, wire_fF, slew):
    """Extra (rise, fall) delay in ns from putting `wire_fF` on top of the
    receiving pin's capacitance, read off our own characterization."""
    cpin = lib[cell]["pins"]["A"]                     # pF
    load = cpin + wire_fF / 1000.0
    return tuple(interp(lib[cell]["tab"][k], slew, load)
                 - interp(lib[cell]["tab"][k], slew, cpin)
                 for k in ("cell_rise", "cell_fall"))


def extra_tap_delay(lib, cell, wire_fF, slew_r, slew_f):
    """How much SLOWER the one double-loaded stage is, in ns (rise+fall).

    The loop-closure node of every ring drives two pins: stage 0 of the ring
    and the tap into `ro_meas`. Measured on the routed netlist of run
    30934157150 — per ring, 29 nets carry one load and `fb` carries two.
    Charged once per ring, at the ring's own fixed-point slew.
    """
    tabs = lib[cell]["tab"]
    pin = lib[cell]["pins"]["A"]
    one = pin + wire_fF / 1000.0
    two = 2 * pin + wire_fF / 1000.0
    d1 = interp(tabs["cell_rise"], slew_f, one) + interp(tabs["cell_fall"], slew_r, one)
    d2 = interp(tabs["cell_rise"], slew_f, two) + interp(tabs["cell_fall"], slew_r, two)
    return d2 - d1


def self_consistent(lib, cell, wire_fF, iters=200, tol=1e-9):
    """(rise, fall, slew_rise, slew_fall) in ns for a stage in a real ring.

    The honest model, and the one this file exists to provide. A ring is a
    closed loop, so a stage's INPUT slew is the previous stage's OUTPUT slew;
    every stage here is identical and inverting, so the pair (s_rise, s_fall)
    has a fixed point. Iterate to it:

        d_rise = cell_rise(s_fall, load)     an inverting output rises
        d_fall = cell_fall(s_rise, load)     because its input fell

    The `abs()` below is now a NO-OP and is kept only as a guard. It used to
    be the M11 workaround, back when every inverting cell carried negative
    transition tables; `stdcells` lib-v1.4 fixed that at the source and this
    repo has been pinned to it since 2026-08-04, so the tables are positive.

    ⚠️ M11 was NOT the sign error it was written up as, and this function was
    wrong in a way that happened not to matter. The tables were negated AND
    EXCHANGED, so `abs(rise_transition)` returned the FALL time — meaning the
    loop below drove `d_rise = cell_rise(s_fall)` with the wrong-direction
    slew, and vice versa. Re-running against a fixed library moved the
    predictions by **under 1%** (tt: INV 625.0 → 628.4 MHz, NAND2 459.1 →
    460.1, NOR2 294.5 → 294.8). That near-invariance is structural, not luck:
    a ring's period is the SUM of both edges over the loop, so exchanging
    which slew drives which edge preserves the total almost exactly. Do not
    read it as evidence that the old library was fine — the same defect cost
    766 ps of setup slack on stdcells' own CORDIC-1 harden, where the two
    edges are not summed.
    """
    tabs = lib[cell]["tab"]
    load = lib[cell]["pins"]["A"] + wire_fF / 1000.0
    s_r = s_f = tabs["cell_rise"][0][0]          # seed at the fastest row
    d_r = d_f = 0.0
    for _ in range(iters):
        d_r = interp(tabs["cell_rise"], s_f, load)
        d_f = interp(tabs["cell_fall"], s_r, load)
        n_r = abs(interp(tabs["rise_transition"], s_f, load))
        n_f = abs(interp(tabs["fall_transition"], s_r, load))
        if abs(n_r - s_r) < tol and abs(n_f - s_f) < tol:
            break
        s_r, s_f = n_r, n_f
    return d_r, d_f, s_r, s_f


# ------------------------------------------------------------------ report --

def count_of(f_hz, window="short"):
    return f_hz / 2 ** PRE * (2 ** WIN[window] / CLK_HZ)


def report(sdf_path):
    """The raw SDF table — what a gate-level sim of this SDF will reproduce."""
    per = parse(sdf_path)
    if not per:
        print(f"  {Path(sdf_path).name}: no ring cells found")
        return
    arcs = measured_arcs(per)

    print(f"\n{Path(sdf_path).parent.name}")
    print(f"  {'ring':<7}{'stage cell':<11}{'t_plh':>8}{'t_phl':>8}"
          f"{'period':>10}{'f_ring':>11}{'count/short':>13}")

    for ring, comp in COMPOSITION.items():
        period_ns = 0.0
        rows = []
        zeros = 0
        for celltype, n in comp.items():
            got = arcs.get((ring, celltype))
            if not got:
                continue
            _, _, rise, fall, nz = got      # RAW means: the SDF as annotated
            zeros += nz
            period_ns += n * (rise + fall)
            rows.append((celltype, n, rise * 1000, fall * 1000))
        if zeros:
            print(f"  [{ring}] {zeros} stage arc(s) reported 0.000 — OpenSTA's "
                  f"loop break, INCLUDED here so this matches a GL sim of the "
                  f"same SDF; for silicon use --run")
        if not rows or not period_ns:
            continue
        f_hz = 1e9 / period_ns
        first = True
        for celltype, n, tr, tf in rows:
            shown = (f"{tr:>7.1f}p{tf:>7.1f}p" if tr is not None
                     else f"{'break':>8}{'':>8}")
            if first:
                print(f"  {ring:<7}{celltype+f' x{n}':<11}{shown}"
                      f"{period_ns:>9.3f}n{f_hz/1e6:>9.1f}M"
                      f"{count_of(f_hz):>13.0f}")
                first = False
            else:
                print(f"  {'':<7}{celltype+f' x{n}':<11}{shown}")


def silicon(run_dir):
    """The corrected prediction, per corner, with its error bar."""
    SUBGRID.clear()
    run = Path(run_dir)
    sdfs = sorted((run / "final" / "sdf").glob("*/*.sdf"))
    if not sdfs:
        sys.exit(f"no final/sdf/*/*.sdf under {run}")

    for sdf in sdfs:
        corner = sdf.parent.name                     # e.g. nom_tt_025C_1v80
        rc, pvt = corner.split("_", 1)
        libp = LIBDIR / f"own_hardening_{pvt}.lib"
        spefp = next((run / "final" / "spef" / rc).glob("*.spef"), None)
        if not libp.exists() or spefp is None:
            print(f"\n{corner}: missing {'lib' if not libp.exists() else 'spef'}"
                  f" — skipped")
            continue
        lib = parse_liberty(libp)
        loops = ring_loop_caps(spef_wire_caps(spefp))
        arcs = measured_arcs(parse(sdf))
        slew = lib["INV_X1"]["tab"]["cell_rise"][0][0]     # characterized floor

        print(f"\n{corner}   (lib {libp.name}, spef {rc})")
        print(f"  {'ring':<7}{'raw SDF':>10}{'+stage':>10}{'+wire':>10}"
              f"{'self-consistent':>17}{'count/short':>13}")

        slews = {}
        for ring, comp in COMPOSITION.items():
            wire = loops.get(ring, [])
            if not wire:
                continue
            w_mean = st.mean(wire)
            raw = fixed = wired = floor = 0.0
            ok = True
            tapped = {}
            for celltype, n in comp.items():
                got = arcs.get((ring, celltype))
                if not got:
                    ok = False
                    break
                raw += n * (got[2] + got[3])       # SDF as annotated
                rise, fall = got[0], got[1]
                if rise is None:
                    # this cell's only arc in this ring IS the loop break:
                    # borrow the same cell type from the ring that has it live
                    donor = next((arcs[k] for k in arcs
                                  if k[1] == celltype and arcs[k][0] is not None),
                                 None)
                    if donor is None:
                        ok = False
                        break
                    rise, fall = donor[0], donor[1]
                fixed += n * (rise + fall)
                dr, df = wire_delta(lib, celltype, w_mean, slew)
                wired += n * (rise + fall + dr + df)
                sr, sf, slew_r, slew_f = self_consistent(lib, celltype, w_mean)
                floor += n * (sr + sf)
                slews[celltype] = (slew_r, slew_f)
                # Review-brief Q4, measured 2026-08-04 on the ROUTED netlist:
                # exactly ONE node per ring drives TWO pins, not one. It is the
                # loop-closure net `fb` — the alias of n[STAGES-1] and `osc` —
                # which feeds stage 0 AND the tap into ro_meas. (Fanout
                # histogram per ring: 29 nets at 1 load, `fb` at 2. There is no
                # buffer on it, which is H3 staying fixed.) Every other stage
                # in the model carries a single pin load, so the ring was
                # predicted ~1.0-1.2% fast. Charge that one stage the second
                # pin instead of documenting the error.
                tapped[celltype] = extra_tap_delay(lib, celltype, w_mean,
                                                   slew_r, slew_f)
            if not ok:
                continue
            # The tapped stage is the driver of n[STAGES-1], i.e. the ring's
            # majority cell — stage 0 (the enable gate) is at the OTHER end of
            # the loop. Verified against the routed netlist: the INV ring's
            # `fb` is driven by an INV_X1 and loads NAND2_X1.A (stage 0) +
            # INV_X1.A (the tap); NOR2's is driven by NOR2_X1 and loads
            # NOR2_X1.A + NAND2_X1.A. Charged ONCE per ring.
            if tapped:
                floor += tapped[max(comp, key=comp.get)]
            f = [1e9 / p for p in (raw, fixed, wired, floor)]
            print(f"  {ring:<7}{f[0]/1e6:>9.1f}M{f[1]/1e6:>9.1f}M"
                  f"{f[2]/1e6:>9.1f}M{f[3]/1e6:>16.1f}M"
                  f"{count_of(f[3]):>13.0f}")

        # The ring's own fixed-point slews. These sit BELOW the characterized
        # grid's first row, which is why the column exists at all: the NLDM
        # cannot be asked about a slew it never measured, so the fixed point
        # is the honest operating point rather than an interpolated one.
        # (Before lib-v1.4 this line also reported "STA used 0", because M11's
        # negative tables were clamped. That is fixed at the source now.)
        i1 = lib["INV_X1"]["tab"]["cell_rise"][0]
        print("  fixed-point slews (ps, rise/fall): "
              + "  ".join(f"{c} {r*1000:.1f}/{f*1000:.1f}"
                          for c, (r, f) in sorted(slews.items()))
              + f"   [grid starts at {i1[0]*1000:.0f} ps]")

    # M27. A clamp RETURNS the grid-edge value with the same confidence as an
    # interpolated one, so a prediction computed there is not the prediction it
    # claims to be. lib-v2.0 measures a 10 ps row precisely so the ring's own
    # fixed point is interior; if a future ring slides under it again, this
    # says so instead of quietly publishing the edge.
    if SUBGRID:
        worst = min(v for v, _ in SUBGRID)
        floor = SUBGRID[0][1]
        sys.exit(
            f"\nREFUSING TO PUBLISH: {len(SUBGRID)} lookup(s) fell BELOW "
            f"the library's first slew row ({floor*1000:.1f} ps); the fastest "
            f"was {worst*1000:.1f} ps. interp() clamps rather than "
            f"extrapolates, so those stages were evaluated at the GRID EDGE "
            f"and the number above is not a prediction for this ring -- it is "
            f"the prediction for a ring {floor/worst:.2f}x slower at that "
            f"node. Measure a lower slew row in stdcells (SLEWS in "
            f"flow/characterize.py) rather than relaxing this check. That is "
            f"what M27 was.")

    print("\nColumns, each adding one correction to the one before it:\n"
          "  raw SDF          what the SDF says, and what a GL sim of that "
          "SDF reproduces\n"
          "  +stage           OpenSTA's loop-break stage substituted, not "
          "averaged in as 0\n"
          "  +wire            SPEF wire load added through our own liberty's "
          "load axis\n"
          "  self-consistent  ...and at the ring's own fixed-point slew "
          "instead of STA's 0\n"
          "**Quote the last column.** Counts are per SHORT window (2**12 "
          "clocks at\n25 MHz); the long window is 256x.")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--run":
        if len(args) < 2:
            sys.exit("--run needs a run directory")
        silicon(args[1])
        return
    files = []
    for a in args:
        p = Path(a)
        files.extend(sorted(p.rglob("*.sdf")) if p.is_dir() else [p])
    if not files:
        sys.exit("no .sdf found")
    for f in files:
        report(f)
    print("\nNote: a count is per SHORT window (2**12 clocks at 25 MHz); the "
          "long window is 2**20, i.e. 256x these numbers.\nThis is the RAW "
          "table — for what silicon should do, use --run <run-dir>.")


if __name__ == "__main__":
    main()
