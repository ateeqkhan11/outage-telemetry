"""Run the probe: every minute, run all checks at once, seal the results onto this network's chain, save them.

  python -m probe.run --network github --minutes 6             # in GitHub Actions (scheduled every 5 minutes)
  python -m probe.run --network local --minutes 30 --local out # on your laptop, results under ./out

Records are written one object per minute, and the chain head after each minute, so a run killed half-way loses
at most the minute in progress. Runs on one network must never overlap (GitHub: the workflow's concurrency group),
or two runs would both link to the same previous record.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, List, Optional

from . import checks as chk
from .chain import GENESIS, load_private, seal
from .store import open_store, to_jsonl

RECORD_VERSION = 1


def _iso(ts: float, minute: bool = False) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%MZ") if minute else d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def where_am_i(network: str) -> str:
    """A short, ASCII description of the machine doing the probing (kept in every record)."""
    e = os.environ
    if e.get("GITHUB_RUN_ID"):
        return f"github-actions run {e['GITHUB_RUN_ID']} {e.get('RUNNER_OS', '')}".strip()
    if e.get("WEBSITE_SITE_NAME"):
        return f"azure-functions {e['WEBSITE_SITE_NAME']} {e.get('REGION_NAME', '')}".strip()
    return f"{network} {platform.node()}"[:80]


def probe_minute(network: str, checks: List[chk.Check], control: chk.Check, now: float) -> List[dict]:
    """Run the control check and every AWS check in parallel; return unsealed records."""
    everything = [control] + checks
    with ThreadPoolExecutor(len(everything)) as ex:
        outcomes = list(ex.map(lambda c: chk.run_check(c[2]), everything))
    host = where_am_i(network)
    return [dict(v=RECORD_VERSION, network=network, host=host, target=chk.TARGET_REGION, service=svc, op=op,
                 minute=_iso(now, minute=True), at=_iso(now), **out)
            for (svc, op, _), out in zip(everything, outcomes)]


def run_minutes(network: str, minutes: int, store, key, checks: List[chk.Check], control: chk.Check,
                wait: bool = True, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> int:
    head = json.loads(store.get(f"chains/{network}/head.json") or b"null") or {"seq": 0, "hash": GENESIS}
    seq, prev, written = head["seq"], head["hash"], 0
    for i in range(minutes):
        if wait and (i > 0 or os.environ.get("PROBE_ALIGN", "1") == "1"):
            sleep(60 - (clock() % 60) + 0.5)                 # start each round just after the minute boundary
        now = clock()
        sealed = []
        for rec in probe_minute(network, checks, control, now):
            seq += 1
            r = seal(rec, prev, seq, key)
            prev = r["hash"]
            sealed.append(r)
        day, hhmm = _iso(now)[:10], _iso(now)[11:16].replace(":", "")
        name = f"runs/{network}/{day}/{hhmm}.jsonl"
        if store.get(name) is not None:                      # never overwrite; can only happen if runs overlap
            name = f"runs/{network}/{day}/{hhmm}-{sealed[0]['seq']}.jsonl"
        store.put(name, to_jsonl(sealed))
        store.put(f"chains/{network}/head.json", json.dumps({"seq": seq, "hash": prev, "at": _iso(now)}).encode())
        written += len(sealed)
        failed = [f"{r['service']}" for r in sealed if not r["ok"]]
        print(f"{_iso(now)} {network}: {len(sealed)} checks, {'failed: ' + ', '.join(failed) if failed else 'all ok'}", flush=True)
    return written


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--network", required=True, help="probe network name: github, azure, cloudflare, gcp, local")
    ap.add_argument("--minutes", type=int, default=1)
    ap.add_argument("--local", help="write to this folder instead of R2")
    ap.add_argument("--no-wait", action="store_true", help="probe immediately instead of on minute boundaries")
    a = ap.parse_args(argv)
    seed = os.environ.get("PROBE_SIGNING_KEY")
    if not seed:
        raise SystemExit("PROBE_SIGNING_KEY is not set (make one with: python scripts/genkey.py --network NAME)")
    run_minutes(a.network, a.minutes, open_store(a.local), load_private(seed), chk.aws_checks(), chk.control_check(),
                wait=not a.no_wait)


if __name__ == "__main__":
    main()
