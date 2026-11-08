"""Build the public status summary the dashboard reads: status/latest.json.

  python -m probe.status --local store --keys keys --config trigger_v1_rolling.json

Covers the last 24 hours of every probe network found in the store:
  - per service: current state, uptime, latency per network, and a 10-minute timeline of failed checks
  - outage events under the trigger rules (counting independent operators only)
  - per network: operator, last result, minutes covered, longest gap, and whether its signed chain verifies
  - a few of the latest signed records, so anyone can check one by hand with the public key
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .chain import load_public, verify
from .detect import detect, minute_states
from .store import open_store, read_jsonl

FMT = "%Y-%m-%dT%H:%MZ"
BUCKET_MIN = 10


def load_window(store, hours: int, now: datetime) -> List[dict]:
    """Records from the last `hours` hours, read from the per-minute files of every network."""
    since = now - timedelta(hours=hours)
    days = {(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((now - since).days + 2)}
    out = []
    for key in store.list("runs/"):
        parts = key.split("/")
        if len(parts) < 4 or parts[2] not in days:
            continue
        for r in read_jsonl(store.get(key)):
            if datetime.strptime(r["minute"], FMT).replace(tzinfo=timezone.utc) >= since:
                out.append(r)
    return sorted(out, key=lambda r: (r["network"], r["seq"]))


def build(store, keys_dir: str, cfg: dict, hours: int = 24, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    recs = load_window(store, hours, now)
    services = cfg["services"]
    reference = set(cfg.get("reference_networks", []))
    nets = sorted({r["network"] for r in recs})

    networks = {}
    for net in nets:
        rs = [r for r in recs if r["network"] == net]
        pub = Path(keys_dir) / f"{net}.pub"
        problems = verify(rs, load_public(pub.read_text())) if pub.exists() else [f"no public key for {net}"]
        minutes = sorted({r["minute"] for r in rs})
        gaps, prev = [], None
        for m in minutes:
            t = datetime.strptime(m, FMT)
            if prev and (t - prev).total_seconds() > 60:
                gaps.append(int((t - prev).total_seconds() // 60) - 1)
            prev = t
        networks[net] = {
            "operator": "reference (inside AWS, not counted)" if net in reference else cfg["operators"].get(net, net),
            "counted": net not in reference,
            "last_minute": minutes[-1] if minutes else None,
            "minutes_covered": len(minutes), "minutes_in_window": hours * 60,
            "longest_gap_min": max(gaps, default=0), "records": len(rs),
            "chain_valid": not problems,
            "problems": problems[:5],
            "host": rs[-1].get("host") if rs else None,
        }

    counted = [r for r in recs if r["network"] not in reference]
    states = minute_states(counted, cfg)
    last_min = max(states) if states else None
    operators = sorted({cfg["operators"].get(n, n) for n in nets if n not in reference})

    svc_out = {}
    for svc in services:
        rows = [r for r in recs if r["service"] == svc]
        by_net = defaultdict(list)
        for r in rows:
            by_net[r["network"]].append(r)
        known = [m for m in states if states[m][svc] != "unknown"]
        up = sum(1 for m in known if states[m][svc] == "up")
        # timeline: share of failed checks per 10 minutes, all networks together
        buckets = defaultdict(lambda: [0, 0])
        for r in rows:
            t = datetime.strptime(r["minute"], FMT)
            b = t.replace(minute=t.minute - t.minute % BUCKET_MIN).strftime(FMT)
            buckets[b][0] += 0 if r["ok"] else 1
            buckets[b][1] += 1
        timeline = []
        start = (now - timedelta(hours=hours)).replace(second=0, microsecond=0)
        start = start.replace(minute=start.minute - start.minute % BUCKET_MIN)
        t = start
        while t <= now:
            k = t.replace(tzinfo=None).strftime(FMT)
            f, n = buckets.get(k, (0, 0))
            timeline.append({"t": k, "checks": n, "failed": f})
            t += timedelta(minutes=BUCKET_MIN)
        hour_ago = (now - timedelta(hours=1)).replace(tzinfo=None)
        svc_out[svc] = {
            "state": states[last_min][svc] if last_min else "unknown",
            "uptime_pct": round(100 * up / len(known), 3) if known else None,
            "minutes_judged": len(known),
            "latency_ms_p50_last_hour": {n: int(statistics.median([r["latency_ms"] for r in rs if r["ok"] and datetime.strptime(r["minute"], FMT) >= hour_ago] or [0]))
                                         for n, rs in by_net.items()},
            "checks": len(rows), "failed": sum(1 for r in rows if not r["ok"]),
            "last_error": next((r["error"] for r in reversed(rows) if r["error"]), None),
            "timeline": timeline,
        }

    det = detect(counted, cfg) if counted else {"region": []}
    sample = {}
    for net in nets:
        rs = [r for r in recs if r["network"] == net]
        if rs:
            sample[net] = rs[-3:]
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_hours": hours, "region": cfg["region"],
        "rules": {"version": cfg["version"], "operators_required": cfg["operators_required"],
                  "window_minutes": cfg.get("window_minutes", 1), "window_fail_share": cfg.get("window_fail_share", 1.0),
                  "waiting_periods_min": cfg["waiting_periods_min"]},
        "independent_operators": operators,
        "can_decide": len(operators) >= cfg["operators_required"],
        "overall": ("down" if last_min and any(states[last_min][s] == "down" for s in services)
                    else ("up" if last_min and all(states[last_min][s] == "up" for s in services) else "unknown")),
        "last_minute": last_min,
        "services": svc_out, "networks": networks, "outages": det["region"],
        "public_keys": {n: (Path(keys_dir) / f"{n}.pub").read_text().strip() for n in nets if (Path(keys_dir) / f"{n}.pub").exists()},
        "sample_records": sample,
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build status/latest.json for the dashboard")
    ap.add_argument("--local", required=True, help="the checked-out data branch")
    ap.add_argument("--keys", default="keys")
    ap.add_argument("--config", default="trigger_v1_rolling.json")
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args(argv)
    store = open_store(a.local)
    s = build(store, a.keys, json.loads(Path(a.config).read_text()), a.hours)
    store.put("status/latest.json", json.dumps(s, separators=(",", ":")).encode())
    print(f"status: overall {s['overall']}, operators {s['independent_operators']}, "
          + ", ".join(f"{k} {v['state']}" for k, v in s["services"].items()))


if __name__ == "__main__":
    main()
