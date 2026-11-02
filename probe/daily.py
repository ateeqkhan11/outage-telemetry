"""Build the signed daily file for each probe network and a manifest for the day.

  python -m probe.daily --date 2026-11-08 --keys keys            # from R2
  python -m probe.daily --date 2026-11-08 --keys keys --local out

For each network: gathers the day's per-minute objects in sequence order, verifies the chain and signatures,
reports gaps (minutes with no record), and writes daily/<date>/<network>.jsonl. The manifest lists each file's
SHA-256, so committing the manifest to the public repo fixes the day's data in place: changing any record later
changes the file hash and no longer matches the commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .chain import load_public, verify
from .store import open_store, read_jsonl, to_jsonl


def build_day(store, day: str, keys_dir: str) -> dict:
    networks = sorted({k.split("/")[1] for k in store.list("runs/") if k.split("/")[2] == day})
    manifest: Dict[str, object] = {"date": day, "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "networks": {}}
    for net in networks:
        recs: List[dict] = []
        for k in store.list(f"runs/{net}/{day}/"):
            recs += read_jsonl(store.get(k))
        recs.sort(key=lambda r: r["seq"])
        pub_file = Path(keys_dir) / f"{net}.pub"
        problems = verify(recs, load_public(pub_file.read_text())) if pub_file.exists() else [f"no public key at {pub_file}"]
        minutes = sorted({r["minute"] for r in recs})
        expected = 24 * 60
        have = set(minutes)
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        gaps, run = [], None
        for m in range(expected):
            t = (start + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%MZ")
            if t not in have:
                run = run or [t, t]
                run[1] = t
            elif run:
                gaps.append(run); run = None
        if run:
            gaps.append(run)
        body = to_jsonl(recs)
        store.put(f"daily/{day}/{net}.jsonl", body)
        manifest["networks"][net] = {
            "records": len(recs), "minutes_covered": len(have), "minutes_in_day": expected,
            "first_seq": recs[0]["seq"] if recs else None, "last_seq": recs[-1]["seq"] if recs else None,
            "first_prev": recs[0]["prev"] if recs else None, "last_hash": recs[-1]["hash"] if recs else None,
            "longest_gap_min": max((_span(g) for g in gaps), default=0), "gaps": gaps[:200],
            "chain_valid": not problems, "problems": problems[:50], "sha256": hashlib.sha256(body).hexdigest()}
    store.put(f"daily/{day}/manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode())
    return manifest


def _span(g: List[str]) -> int:
    a, b = (datetime.strptime(x, "%Y-%m-%dT%H:%MZ") for x in g)
    return int((b - a).total_seconds() // 60) + 1


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build and verify the daily files")
    ap.add_argument("--date", default=(date.today() - timedelta(days=1)).isoformat(), help="UTC day, default yesterday")
    ap.add_argument("--keys", default="keys", help="folder with <network>.pub files")
    ap.add_argument("--local", help="read and write this folder instead of R2")
    ap.add_argument("--copy-to", help="also copy daily/<date>/ into this folder (the workflow commits it)")
    a = ap.parse_args(argv)
    store = open_store(a.local)
    m = build_day(store, a.date, a.keys)
    for net, s in m["networks"].items():
        print(f"{a.date} {net}: {s['records']} records, {s['minutes_covered']}/{s['minutes_in_day']} minutes, "
              f"longest gap {s['longest_gap_min']} min, chain {'valid' if s['chain_valid'] else 'INVALID'}")
    if a.copy_to:
        out = Path(a.copy_to) / a.date
        out.mkdir(parents=True, exist_ok=True)
        for k in store.list(f"daily/{a.date}/"):
            (out / Path(k).name).write_bytes(store.get(k))
    if any(not s["chain_valid"] for s in m["networks"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
