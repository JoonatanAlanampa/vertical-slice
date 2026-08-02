"""Connectivity audit of the ALL-OWN gate netlist. Fanout-aware, by design.

Why this exists
---------------
The previous audit (inline in flow/make_hardening.py) keyed on instance NAME
and compared cell-type COUNTS:

    for cell, inst in re.findall(r"(\\w+)\\s+(\\S*u_stage\\S*)\\(", text): ...
    want = {"INV_X1": 30, "NAND2_X1": 32, "NOR2_X1": 31}

It passed at HEAD while 112 BUF_X2 hung off the design, 87 of them on ring
oscillator stage outputs, because a buffer named `_4906_` never matches
`*u_stage*` and **a count can never see a load**. Those buffers are pure
parasitic capacitance on the nodes whose delay this chip exists to measure:
silicon would have reported a slower ring and that number would have been
written down as the cell delay (READINESS.md H3).

So this audit asks the question a census cannot: *what is attached to each
ring node, and does anything in this netlist drive nothing at all?*

Pin directions come from the pinned liberty (lib/own_hardening.lib), not from
a table in this file, so a library change cannot silently invalidate the audit.

    python tools/audit_netlist.py [netlist] [--report]

Exit 0 = clean. Non-zero = a finding, printed. --report prints the full
picture without failing, for interactive use.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib" / "own_hardening.lib"
NETLIST = ROOT / "harden" / "vslice_gates.v"

STAGES = 31
# Exact instance names as they appear in the netlist. Getting these wrong is
# silent: a ring whose name does not match simply is not audited.
RINGS = ("u_ro_inv", "u_ro_nand2", "u_ro_nor2")

# Same expectation the census used, kept: the INV ring is 30 inverters plus
# the NAND2 that gates it, so NAND2 carries one more than a homogeneous ring.
EXPECT_RING = {"INV_X1": STAGES - 1, "NAND2_X1": STAGES + 1, "NOR2_X1": STAGES}


def _block(txt, i):
    """i indexes an opening brace -> its body. Brace-matched, because an
    output pin's timing tables nest several levels deep and a non-greedy
    [^{}]* silently drops exactly the output pins this audit needs."""
    depth, start = 0, i
    while i < len(txt):
        if txt[i] == "{":
            depth += 1
        elif txt[i] == "}":
            depth -= 1
            if depth == 0:
                return txt[start + 1:i]
        i += 1
    return txt[start + 1:]


def liberty_pins(path):
    """cell -> {pin: 'input'|'output'} straight from the pinned liberty."""
    txt = path.read_text()
    pins = {}
    for m in re.finditer(r"cell \((\w+)\)\s*\{", txt):
        body = _block(txt, m.end() - 1)
        d = {}
        for pm in re.finditer(r"pin \((\w+)\)\s*\{", body):
            dm = re.search(r"direction\s*:\s*(\w+)", _block(body, pm.end() - 1))
            if dm:
                d[pm.group(1)] = dm.group(1)
        pins[m.group(1)] = d
    return pins


def parse_netlist(path):
    """-> (instances, ports). instance = (cell, name, {pin: net})."""
    txt = path.read_text()

    ports = {}
    mm = re.search(r"\bmodule\s+\S+\s*\((.*?)\);", txt, re.S)
    if mm:
        for d in re.finditer(r"\b(input|output|inout)\b\s*(?:\[[^\]]*\])?\s*"
                             r"(\\\S+\s|\w+)", txt[:mm.end() + 4000]):
            ports[d.group(2).strip()] = d.group(1)

    instances = []
    # CELL  name  ( .PIN(net), ... );   name may be an escaped identifier.
    for m in re.finditer(r"^[ \t]*(\w+)[ \t]+(\\\S+[ \t]|\w+)[ \t]*\((.*?)\);",
                         txt, re.S | re.M):
        cell, name, body = m.group(1), m.group(2).strip(), m.group(3)
        if cell in ("module", "endmodule", "wire", "input", "output", "assign"):
            continue
        conns = {}
        for c in re.finditer(r"\.(\w+)\(([^)]*)\)", body):
            conns[c.group(1)] = c.group(2).strip()
        if conns:
            instances.append((cell, name, conns))

    # Continuous assignments are connectivity too. Without this, a net read
    # only through an `assign` looks unloaded and the dangling check invents
    # findings -- measured on an insbuf-free variant, which reported 18.
    assigns = [(m.group(1).strip(), m.group(2).strip()) for m in
               re.finditer(r"^\s*assign\s+(.+?)\s*=\s*(.+?)\s*;", txt, re.M)]
    return instances, ports, assigns


# Power pins are not signal connectivity, and the liberty does not declare
# them at all. The POWERED netlist (final/pnl/*.pnl.v) connects them
# explicitly, so without this the audit reports every cell as unreasonable
# and fails on an otherwise clean routed result.
POWER_PINS = {"VPWR", "VGND", "VPB", "VNB", "VDD", "VSS"}


def build_graph(instances, pins, assigns=()):
    """net -> drivers/loads, using liberty directions."""
    drivers, loads = defaultdict(list), defaultdict(list)
    unknown = set()
    for lhs, rhs in assigns:
        for tok in re.findall(r"\\\S+\s|\w+(?:\[[^\]]*\])?", rhs):
            loads[tok.strip()].append(("assign", lhs, "rhs"))
        drivers[lhs].append(("assign", lhs, "lhs"))
    for cell, name, conns in instances:
        if cell not in pins:
            unknown.add(cell)
            continue
        for pin, net in conns.items():
            if not net or pin in POWER_PINS:
                continue
            d = pins[cell].get(pin)
            if d == "output":
                drivers[net].append((cell, name, pin))
            elif d == "input":
                loads[net].append((cell, name, pin))
            else:
                unknown.add(f"{cell}.{pin}")
    return drivers, loads, unknown


def ring_of(inst_name):
    for r in RINGS:
        if f".{r}." in inst_name or inst_name.startswith(r + "."):
            return r
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    report = "--report" in sys.argv
    netlist = Path(args[0]) if args else NETLIST

    if not netlist.exists():
        sys.exit(f"ERROR: netlist not found: {netlist}")
    if not LIB.exists():
        sys.exit(f"ERROR: lib/own_hardening.lib missing — run tools/fetch_lib.py")

    pins = liberty_pins(LIB)
    instances, ports, assigns = parse_netlist(netlist)
    drivers, loads, unknown = build_graph(instances, pins, assigns)

    census = defaultdict(int)
    for cell, _, _ in instances:
        census[cell] += 1

    print(f"netlist   : {netlist.relative_to(ROOT) if netlist.is_relative_to(ROOT) else netlist}")
    print(f"instances : {len(instances)}  ({len(census)} cell types)")
    for c in sorted(census, key=lambda c: -census[c]):
        print(f"    {c:<12}{census[c]:>6}")

    findings = []

    # ---- 1. zero foundry content ------------------------------------------
    foundry = {c: n for c, n in census.items() if c.startswith("sky130")}
    if foundry:
        findings.append(f"foundry cells in an all-own netlist: {foundry}")
    else:
        print("\n[1] zero-foundry            : OK")

    if unknown:
        findings.append(f"cells/pins absent from the pinned liberty: "
                        f"{sorted(unknown)} — audit cannot reason about them")

    # ---- 2. ring census (what the old audit did) ---------------------------
    ring_cells = defaultdict(int)
    stage_insts = []
    for cell, name, conns in instances:
        if "u_stage" in name and ring_of(name):
            ring_cells[cell] += 1
            stage_insts.append((cell, name, conns))
    if dict(ring_cells) != EXPECT_RING:
        findings.append(f"ring stages wrong: expected {EXPECT_RING}, "
                        f"found {dict(ring_cells)} (a collapsed ring measures nothing)")
    else:
        print(f"[2] ring census             : OK ({sum(ring_cells.values())} stage cells)")

    # ---- 3. NEW: nothing in the netlist drives nothing ---------------------
    # A cell output with no load is at best dead area; on a ring node it is
    # parasitic capacitance on the measurement itself. This is H3.
    # A buffer on `uio_oe[3]` is NOT dangling: the module header declares the
    # bus (`output [7:0] uio_oe`) while the bits are driven individually, so
    # the bit never appears as a load. Strip the index before asking whether
    # the net leaves the chip -- but ask about loads on the EXACT bit, or
    # bit 16 inherits bit 3's reader and the check goes quiet.
    dangling = []
    for cell, name, conns in instances:
        for pin, net in conns.items():
            if pins.get(cell, {}).get(pin) != "output":
                continue
            base = re.sub(r"\s*\[[^\]]*\]\s*$", "", net).strip()
            if not loads.get(net) and net not in ports and base not in ports:
                dangling.append((cell, name, pin, net))
    if dangling:
        by_cell = defaultdict(int)
        for cell, _, _, _ in dangling:
            by_cell[cell] += 1
        findings.append(f"{len(dangling)} cell outputs drive NOTHING: {dict(by_cell)}")
        for cell, name, pin, net in dangling[:5]:
            findings.append(f"      e.g. {cell} {name} .{pin}({net})")
    else:
        print("[3] no dangling outputs     : OK")

    # ---- 4. NEW: what is actually attached to each ring node --------------
    # The invariant that H3 violated: a ring stage output drives the next
    # stage, and nothing else. The one tap per ring that leaves for the
    # counter is the single documented exception.
    taps, overloaded = [], []
    for cell, name, conns in stage_insts:
        out = next((n for p, n in conns.items()
                    if pins.get(cell, {}).get(p) == "output"), None)
        if out is None:
            continue
        ld = loads.get(out, [])
        ring_loads = [l for l in ld if l[1] in
                      {n for _, n, _ in stage_insts} and ring_of(l[1]) == ring_of(name)]
        other = [l for l in ld if l not in ring_loads]
        if other:
            taps.append((name, [(c, n, p) for c, n, p in other]))
        if len(ring_loads) != 1:
            overloaded.append((name, out, len(ring_loads)))

    non_stage_loads = sum(len(o) for _, o in taps)
    if overloaded:
        findings.append(f"{len(overloaded)} ring stages do not drive exactly one "
                        f"next stage: {overloaded[:4]}")
    if non_stage_loads != RINGS.__len__():
        findings.append(
            f"ring nodes carry {non_stage_loads} non-stage load(s); expected "
            f"exactly {len(RINGS)} (one tap per ring). Anything extra is "
            f"parasitic capacitance on the measurement — see READINESS.md H3.")
        for name, other in taps:
            for c, n, p in other:
                findings.append(f"      {name} -> {c} {n} .{p}")
    else:
        print(f"[4] ring node fanout        : OK (each stage -> 1 stage; "
              f"{non_stage_loads} taps)")

    if report:
        print("\n--- report mode: findings not fatal ---")
        for f in findings:
            print(f"  {f}")
        return 0

    if findings:
        print("\nAUDIT FAILED:")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("\naudit: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
