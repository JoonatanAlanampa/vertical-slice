"""Make a flat netlist + its SDF annotatable by Icarus.

OpenROAD writes a FLAT netlist: what used to be a hierarchy path becomes a
single escaped Verilog identifier containing dots —

    \\u_ro_meas.u_ro_inv.g_stage[0].u_stage.g_cell.u_cell

and the SDF names the same cell with the dots backslash-escaped. Icarus'
SDF annotator does not honour those escapes: it splits on the divider and
goes looking for a scope called `u_ro_meas`, which does not exist, so every
such cell is silently left UNANNOTATED. The simulation then runs on
whatever default delays the cell models carry — which looks like a working
gate-level run and is worth nothing.

The fix is mechanical: rewrite both files so the names contain no dots at
all, using `$` (legal in Verilog identifiers, absent from these names).
Simulation-only — nothing here goes near the GDS.

    python flow/sdf_sanitize.py <netlist> <sdf> <out-dir>
"""

import re
import sys
from pathlib import Path

SEP = "$"


def _flatten(name: str) -> str:
    for ch in ".[]":
        name = name.replace(ch, SEP)
    return name


def sanitize_netlist(text: str) -> str:
    # An escaped identifier runs from the backslash to the next whitespace.
    # Brackets go too: icarus reads `g_stage[0]` in an SDF instance name as an
    # ARRAY INDEX, so a name containing them can never match a flat instance.
    return re.sub(r"\\(\S+)", lambda m: "\\" + _flatten(m.group(1)), text)


def sanitize_sdf(text: str) -> str:
    # In SDF the same names carry their dots and brackets BACKSLASH-ESCAPED,
    # and that is the discriminator: an escaped `\[` belongs to a flattened
    # hierarchical name, while a bare `[` is a genuine bus index on a real
    # vector and must be left alone. The port separator is the one dot that
    # survives, and it is never escaped.
    for esc in ("\\.", "\\[", "\\]"):
        text = text.replace(esc, SEP)
    return text


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    netlist, sdf, out_dir = (Path(a) for a in sys.argv[1:])
    out_dir.mkdir(parents=True, exist_ok=True)

    nl_out = out_dir / netlist.name
    sdf_out = out_dir / sdf.name
    nl_out.write_text(sanitize_netlist(netlist.read_text()))
    sdf_out.write_text(sanitize_sdf(sdf.read_text()))

    n = len(re.findall(r"\$", nl_out.read_text()))
    print(f"netlist -> {nl_out}  ({n} name separators rewritten)")
    print(f"sdf     -> {sdf_out}")


if __name__ == "__main__":
    main()
