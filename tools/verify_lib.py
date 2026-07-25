"""Verify the COMMITTED lib/ against lib.lock, without any network access.

Why this exists. The cell library used to be fetched at CI time by
tools/fetch_lib.py and never committed. That is fine for our own workflows, but
the TinyTapeout submission is built from the repository, so anything the
submitted GDS depends on has to be IN the repository — otherwise the flow
silently falls back to foundry cells (that was blocker 1; see
research/vertical-slice-presubmit-codex.md).

So lib/ is now committed. That introduces exactly one new failure mode: the
committed bytes drifting from the release lib.lock pins — someone bumps the tag
without re-fetching, or edits a file in place. This checks that in a second,
offline, and is wired into every workflow that builds or ships the design.

fetch_lib.py remains the way to CHANGE the pin (it talks to GitHub and rewrites
lib.lock); this only ever reads.

    python tools/verify_lib.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "lib.lock"
LIB = ROOT / "lib"


def main():
    if not LOCK.exists():
        sys.exit("ERROR: lib.lock is missing")
    lock = json.loads(LOCK.read_text())
    pins = lock.get("files", {})
    if not pins:
        sys.exit("ERROR: lib.lock names no files")

    missing, bad = [], []
    for rel, want in sorted(pins.items()):
        # lib.lock keys are paths in the stdcells release (e.g. out/own.lef);
        # they land in lib/ under their basename, which is what fetch_lib.py
        # writes and what harden/config.json and src/config.json reference.
        f = LIB / Path(rel).name
        if not f.exists():
            missing.append(f"{f.relative_to(ROOT)}  (pinned as {rel})")
            continue
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        if got != want:
            bad.append(f"{f.relative_to(ROOT)}\n     pinned {want}\n     found  {got}")

    if missing or bad:
        if missing:
            print("MISSING from the committed lib/:", *missing, sep="\n  ")
        if bad:
            print("CHECKSUM MISMATCH vs lib.lock:", *bad, sep="\n  ")
        sys.exit(
            f"\nlib/ does not match lib.lock ({lock.get('repo')} @ "
            f"{lock.get('tag')}).\nRe-run `python tools/fetch_lib.py` and commit "
            f"the result, or fix the pin with --update if the move is intended.")

    print(f"lib/ matches lib.lock: {len(pins)} files, "
          f"{lock.get('repo')} @ {lock.get('tag')}")


if __name__ == "__main__":
    main()
