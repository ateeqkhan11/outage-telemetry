"""Keep a local copy of the public data branch and count what is in it.

  sync(data_dir, db_path, repo_url)   git fetch the latest data branch (shallow), then ingest()
  ingest(data_dir, db_path, cfg)      count every new per-minute file into minute_counts; drop files that left runs/
                                      (a fork moved to archive/forks/ by scripts/prune_forks.py); then refresh the
                                      daily roll-ups (history.py) for the days that changed
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path

from probe.detect import round_counts

from . import history
from .db import connect, now


def git_sync(data_dir: str, repo_url: str) -> None:
    d = Path(data_dir)
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--single-branch", "--branch", "data", repo_url, str(d)],
                       check=True)
        return
    subprocess.run(["git", "-C", str(d), "fetch", "--quiet", "--depth", "1", "origin", "data"], check=True)
    subprocess.run(["git", "-C", str(d), "reset", "--quiet", "--hard", "FETCH_HEAD"], check=True)
    subprocess.run(["git", "-C", str(d), "clean", "--quiet", "-fd"], check=True)


def file_counts(records, cfg) -> dict:
    """{(network, minute, service): [checks, ok, failed, usable, lat_sum, lat_n]} for one file's records.

    Reference networks get raw numbers only (failed/usable stay 0), exactly as the outage rule ignores them.
    """
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for r in records:
        c = out[(r["network"], r["minute"], r["service"])]
        c[0] += 1
        if r["ok"]:
            c[1] += 1
            c[4] += int(r.get("latency_ms") or 0)
            c[5] += 1
    counts, _ = round_counts(records, cfg)
    for minute, nets in counts.items():
        for net, svcs in nets.items():
            for svc, (f, n) in svcs.items():
                c = out[(net, minute, svc)]
                c[2], c[3] = f, n
    return out


def ingest(data_dir: str, db_path: str, cfg: dict) -> dict:
    root = Path(data_dir) / "runs"
    con = connect(db_path)
    seen = {}
    for f in root.glob("*/*/*.jsonl"):
        seen[str(f.relative_to(root))] = f
    have = {r["src"]: r["size"] for r in con.execute("SELECT src, size FROM ingested_files")}
    added = removed = 0
    changed = set()
    for src in sorted(set(have) - set(seen)):                 # moved away (e.g. an abandoned fork)
        con.execute("BEGIN")
        con.execute("DELETE FROM minute_counts WHERE src = ?", (src,))
        con.execute("DELETE FROM ingested_files WHERE src = ?", (src,))
        con.execute("COMMIT")
        changed.add(src.split("/")[1])
        removed += 1
    for src in sorted(seen):
        f = seen[src]
        size = f.stat().st_size
        if have.get(src) == size:
            continue
        recs = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        net, day = src.split("/")[:2]
        rows = [(src, n, m, s, *c) for (n, m, s), c in file_counts(recs, cfg).items()]
        con.execute("BEGIN")
        con.execute("DELETE FROM minute_counts WHERE src = ?", (src,))
        con.executemany("INSERT INTO minute_counts (src, network, minute, service, checks, ok, failed, usable, lat_sum, lat_n)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute("INSERT OR REPLACE INTO ingested_files (src, network, day, size, ingested_at) VALUES (?, ?, ?, ?, ?)",
                    (src, net, day, size, now()))
        con.execute("COMMIT")
        changed.add(day)
        added += 1
    rolled = history.rollup_days(con, cfg, history.days_to_refresh(con, changed))
    con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('last_sync', ?)", (now(),))
    con.close()
    return {"files_added": added, "files_removed": removed, "files_total": len(seen), "days_rolled_up": rolled}


def sync(data_dir: str, db_path: str, repo_url: str, cfg: dict) -> dict:
    git_sync(data_dir, repo_url)
    return ingest(data_dir, db_path, cfg)
