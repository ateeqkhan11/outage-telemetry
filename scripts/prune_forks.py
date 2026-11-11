"""Move abandoned chain branches out of runs/ into archive/forks/, openly.

  python scripts/prune_forks.py --store store --network aws

If a probe is started twice in the same minute, both copies extend the chain from the same head and the chain forks.
Only one branch continues: the one the network's head.json leads back to. Files whose records are all off that path
are moved to archive/forks/<network>/<day>/ and listed in archive/forks/LOG.md, so nothing is deleted or hidden and
the main chain verifies again. Files that mix main-path and off-path records are never moved; they are reported.
"""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store")
    ap.add_argument("--network", required=True)
    a = ap.parse_args()
    root = Path(a.store)
    head_p = root / "chains" / a.network / "head.json"
    if not head_p.exists():
        return print(f"{a.network}: no head, nothing to prune")
    by_hash, files = {}, {}
    for f in sorted((root / "runs" / a.network).glob("*/*.jsonl")):
        recs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        files[f] = recs
        for r in recs:
            by_hash[r["hash"]] = r
    main_path, h = set(), json.loads(head_p.read_text())["hash"]
    while h in by_hash and h not in main_path:
        main_path.add(h)
        h = by_hash[h]["prev"]
    moved = []
    for f, recs in files.items():
        off = [r for r in recs if r["hash"] not in main_path]
        if not off:
            continue
        if len(off) != len(recs):
            print(f"{a.network}: {f.name} mixes main and abandoned records; left in place")
            continue
        dest = root / "archive" / "forks" / a.network / f.parent.name / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest)
        moved.append((f, recs))
    if moved:
        log = root / "archive" / "forks" / "LOG.md"
        if not log.exists():
            log.write_text("# Abandoned chain branches\n\nA probe started twice in one minute; both copies signed records "
                           "from the same chain head. The branch the chain did not continue from was moved here. Its "
                           "records are genuine and still verify with the network's key.\n\n")
        with log.open("a") as fh:
            for f, recs in moved:
                fh.write(f"- {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ} moved {a.network}/{f.parent.name}/{f.name}: "
                         f"{len(recs)} records, seq {recs[0]['seq']}-{recs[-1]['seq']}, at {recs[0]['at']}\n")
    print(f"{a.network}: {len(moved)} abandoned file(s) archived, main chain {len(main_path)} records")


if __name__ == "__main__":
    main()
