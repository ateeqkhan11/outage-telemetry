"""Check a results file yourself: hashes, links, sequence and signatures.

  python -m probe.verify daily/2026-11-08/github.jsonl --pub keys/github.pub
  python -m probe.verify daily/2026-11-08/                 # every file in the folder, keys from ./keys

Anyone can run this with the public keys in this repo. A valid result means the records are exactly what that
probe network signed, in order, with nothing removed or changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .chain import load_public, verify


def verify_file(path: Path, pub_path: Path) -> List[str]:
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not pub_path.exists():
        return [f"no public key at {pub_path}"]
    return verify(recs, load_public(pub_path.read_text()))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Verify signed probe results")
    ap.add_argument("path", help="a .jsonl file or a folder of them")
    ap.add_argument("--pub", help="public key file (default keys/<network>.pub)")
    ap.add_argument("--keys", default="keys")
    a = ap.parse_args(argv)
    p = Path(a.path)
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    bad = 0
    for f in files:
        pub = Path(a.pub) if a.pub else Path(a.keys) / f"{f.stem}.pub"
        problems = verify_file(f, pub)
        n = sum(1 for line in f.read_text().splitlines() if line.strip())
        print(f"{f}: {n} records, {'VALID' if not problems else 'INVALID'}")
        for q in problems[:20]:
            print("   ", q)
        bad += bool(problems)
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
