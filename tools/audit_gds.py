"""Zero-foundry audit of the GDS ITSELF — the artifact that gets fabricated.

Review-brief Q8 names two failure shapes this repo keeps producing: a guard on
an artifact that is not the one submitted, and a guard asserting a proxy
instead of the property. The existing zero-foundry step in `gds.yaml` greps the
Verilog netlist. That is both shapes at once, mildly: the netlist is not what
the foundry receives, and "no foundry cell is instantiated in the netlist" is a
proxy for "no foundry geometry is on the die".

They agree today — verified 2026-08-04 on run 30934157150, where the submitted
GDS contains exactly 15 structures: our 14 cells plus the top level, and
nothing else. But "they agree today" is the sentence that preceded every
finding in READINESS.md, so assert it every run instead.

The gap is not theoretical. The netlist lists what SYNTHESIS AND P&R placed;
the GDS is what magic/KLayout streamed out, after fill, tap, decap, diode and
any cell the tool merged in from the PDK path. `harden/config.json` points
every one of those flow roles at an own cell, and this is the check that the
pointing worked.

No third-party dependency on purpose: this parses the GDS records directly, so
CI does not grow a `pip install` that could itself fail open. Only two record
types matter --

    STRNAME (0x06) — a structure DEFINED in this file
    SNAME   (0x12) — a structure REFERENCED by an SREF/AREF

-- and a foundry cell would have to appear as one or the other to be on the die.

    python tools/audit_gds.py <gds> [<gds> ...]

Exit 0 = every structure name is ours. Non-zero = foundry geometry, or no GDS
to audit (a check that cannot find its input is not a passing check).
"""

import glob
import struct
import sys
from pathlib import Path

STRNAME, SNAME = 0x06, 0x12

# Anything the SkyWater PDK ships. `sky130_fd_pr__*` (the primitive devices)
# would be just as damning as `sky130_fd_sc_hd__*` (the standard cells): our
# cells are drawn from layers, not instantiated from PDK devices.
FOUNDRY_PREFIXES = ("sky130_",)


def structure_names(path):
    """-> (defined, referenced) sets of structure names in a GDSII file."""
    data = Path(path).read_bytes()
    defined, referenced = set(), set()
    i, n = 0, len(data)
    while i + 4 <= n:
        (length,) = struct.unpack(">H", data[i:i + 2])
        rectype, _dtype = data[i + 2], data[i + 3]
        if length < 4:
            raise ValueError(f"{path}: corrupt record header at byte {i}")
        if rectype in (STRNAME, SNAME):
            raw = data[i + 4:i + length]
            name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
            (defined if rectype == STRNAME else referenced).add(name)
        i += length
    return defined, referenced


def main():
    args = sys.argv[1:] or ["runs/*/final/gds/*.gds", "tt_submission/**/*.gds"]
    files = sorted({p for a in args for p in glob.glob(a, recursive=True)}
                   or ({a for a in args if Path(a).is_file()}))
    if not files:
        print("searched:", *args, sep="\n  ")
        sys.exit("no GDS found — cannot audit the artifact that gets fabricated")

    bad = False
    for f in files:
        defined, referenced = structure_names(f)
        allnames = defined | referenced
        hits = sorted(x for x in allnames
                      if x.startswith(FOUNDRY_PREFIXES))
        print(f"{f}: {len(defined)} structures defined, "
              f"{len(referenced)} referenced")
        if hits:
            bad = True
            print("  FOUNDRY GEOMETRY ON THE DIE:", *hits, sep="\n    ")
        else:
            print("  zero-foundry (GDS): OK — "
                  + ", ".join(sorted(defined)))

    if bad:
        sys.exit("\nzero-foundry claim broken in the FABRICATED GDS. The "
                 "netlist audit can pass while this fails: fill, tap, decap, "
                 "diode and CTS cells enter at the physical level. See "
                 "harden/config.json and PLAN.md.")
    print("\nzero-foundry: OK on the fabricated GDS")


if __name__ == "__main__":
    main()
