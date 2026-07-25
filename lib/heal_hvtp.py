"""Post-P&R hvtp corner healing (KLayout batch: -b -r heal_hvtp.py
-rd input=chip.gds -rd output=healed.gds).

Why: sky130_fd_sc_hd cells carry an hvtp implant band that assumes hd
neighbors on all sides. Interleaving our svt (hvtp-less) cells breaks
that assumption: wherever an hd run ENDS at some x in one row and
another hd run BEGINS at the same x in the adjacent (mirrored) row, the
two hvtp bands touch corner-to-corner across the shared row boundary —
a zero-width pinch flagged as hvtp.1 (width) + hvtp.2 (spacing) by the
official KLayout deck (72 sites in the first v2 hardening; every other
layer was chip-level clean).

Fix: find each pinch (a vertex the merged hvtp polygon visits twice)
and cover it with a DIAMOND (axis half-diagonal 0.28 um). The two 45
degree chamfers it leaves are parallel at 0.28*sqrt(2) = 0.396 >= 0.38
(a square patch fails here: its corners give 0.2*sqrt(2) = 0.283
diagonal widths — measured). The diamond also narrows away from the
row boundary, so it cannot reach any cell's pdiff (>= 0.135 um in from
the cell edge; the diamond is 0.045 um wide at that depth). The added
implant is verified INERT: the script asserts the patches touch no
diff (65/20); implant over field/nwell has no electrical effect.
Deterministic and re-runnable; the healed GDS is re-checked by the
full official deck afterwards.
"""
import pya

lay = pya.Layout()
lay.read(input)          # noqa: F821  (klayout -rd variables)
top = lay.top_cell()
li = lay.layer(78, 44)
ldiff = lay.layer(65, 20)

hvtp = pya.Region(top.begin_shapes_rec(li))
hvtp.merge()

D = 280  # nm axis half-diagonal (dbu = 1 nm)
patches = pya.Region()
npinch = 0
for poly in hvtp.each():
    seen = {}
    for pt in poly.each_point_hull():
        key = (pt.x, pt.y)
        seen[key] = seen.get(key, 0) + 1
    for (x, y), n in seen.items():
        if n > 1:
            npinch += 1
            patches.insert(pya.Polygon([
                pya.Point(x - D, y), pya.Point(x, y + D),
                pya.Point(x + D, y), pya.Point(x, y - D)]))
patches.merge()

diff = pya.Region(top.begin_shapes_rec(ldiff)).merged()
touching = patches.interacting(diff)
assert touching.is_empty(), \
    f"healing patches touch diff — refusing: {touching.count()} shapes"

print(f"hvtp merged polygons: {hvtp.count()}, pinch points: {npinch}, "
      f"patch area: {patches.area()/1e6:.3f} um2")
top.shapes(li).insert(patches)
lay.write(output)        # noqa: F821
print(f"wrote {output}")
