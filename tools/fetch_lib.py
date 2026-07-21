"""Fetch the standard-cell library from a PINNED stdcells release tag.

This repo never consumes stdcells' working tree or its master branch — the
library is an external dependency with a version, exactly like any other.
The rule and its reasoning live in PLAN.md ("Library consumption: pinned,
never live"); this script is the mechanism.

    python tools/fetch_lib.py            # fetch the tag named in lib.lock,
                                         # verify every checksum
    python tools/fetch_lib.py --tag lib-v1.1 --update
                                         # move to a new release and rewrite
                                         # lib.lock with the new checksums

Downloaded artifacts land in lib/ (gitignored). lib.lock IS committed: it
names the tag, the commit it dereferences to, and a sha256 per file, so a
silently edited artifact fails the build instead of quietly changing what
went to fabrication.
"""

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "JoonatanAlanampa/stdcells"
ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
LOCK = ROOT / "lib.lock"

# What this chip actually needs out of the library. Deliberately explicit:
# a wildcard would let a future release quietly add or drop a file.
ARTIFACTS = [
    "out/own.lib",            # timing/power, the P&R library
    "out/own_hardening.lib",  # own.lib + the physical-only cells (TIE/FILL/TAP/DIODE)
    "out/own_abc.lib",        # combinational-only copy: ABC trips on a liberty with a flop
    "out/own.lef",            # abstracts (pins + OBS) for the router
    "out/own_cells.gds",      # the layouts themselves, merged at stream-out
    "flow/heal_hvtp.py",      # signoff-DRC healing pass, run after P&R
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_tag(tag: str) -> dict:
    """Return {artifact_path: bytes} from the repo tarball at `tag`."""
    url = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/{tag}"
    print(f"fetching {REPO}@{tag}")
    with urllib.request.urlopen(url, timeout=120) as r:
        blob = r.read()

    out, wanted = {}, set(ARTIFACTS)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member in tf:
            # strip the "<repo>-<tag>/" prefix the tarball adds
            rel = member.name.split("/", 1)[-1]
            if rel in wanted:
                f = tf.extractfile(member)
                if f is not None:
                    out[rel] = f.read()

    missing = wanted - set(out)
    if missing:
        sys.exit(f"ERROR: {tag} does not contain: {', '.join(sorted(missing))}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="release tag (default: the one in lib.lock)")
    ap.add_argument("--update", action="store_true",
                    help="rewrite lib.lock with the fetched checksums")
    args = ap.parse_args()

    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    tag = args.tag or lock.get("tag")
    if not tag:
        sys.exit("ERROR: no tag given and no lib.lock to read one from")

    files = fetch_tag(tag)

    if args.update or not lock:
        lock = {
            "repo": REPO,
            "tag": tag,
            "files": {p: sha256(b) for p, b in sorted(files.items())},
        }
        LOCK.write_text(json.dumps(lock, indent=2) + "\n")
        print(f"lib.lock updated -> {tag}")
    else:
        if tag != lock["tag"]:
            sys.exit(f"ERROR: fetched {tag} but lib.lock pins {lock['tag']}; "
                     f"pass --update if the move is intended")
        bad = [p for p, b in files.items() if sha256(b) != lock["files"].get(p)]
        if bad:
            sys.exit("ERROR: checksum mismatch (the release was edited in "
                     f"place, or lib.lock is stale): {', '.join(sorted(bad))}")
        print(f"checksums verified against lib.lock ({len(files)} files)")

    LIB_DIR.mkdir(exist_ok=True)
    for path, blob in sorted(files.items()):
        dest = LIB_DIR / Path(path).name
        dest.write_bytes(blob)
        print(f"  {dest.relative_to(ROOT)}  {len(blob):>9,} B")


if __name__ == "__main__":
    main()
