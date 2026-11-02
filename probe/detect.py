"""Turn signed probe records from several networks into outage events, using the rules in trigger_v1.json.

  python -m probe.detect daily/2026-11-08/ --config trigger_v1.json

Per minute and per service, each operator (Microsoft, Cloudflare, Google, ...) is one of:
  ok        at least one of its networks completed the check
  fail      its networks reached a site outside AWS (control check passed) but the AWS check failed
  unusable  its probe was down (control failed) or it sent nothing for that minute
A service-minute is DOWN when `operators_required` operators say fail, UNKNOWN when fewer than that are usable.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

FMT = "%Y-%m-%dT%H:%MZ"


def minute_states(records: Iterable[dict], cfg: dict) -> Dict[str, Dict[str, str]]:
    """{minute: {service: 'down' | 'up' | 'unknown'}}"""
    ops = cfg["operators"]
    fail_kinds = set(cfg.get("fail_kinds", ["server_error", "timeout", "network", "throttled"]))
    by = defaultdict(lambda: defaultdict(dict))               # minute -> network -> service -> True / False / None
    for r in records:
        # True = worked, False = failed in a way that means the service was down, None = says nothing about AWS
        kind = r.get("kind", "ok" if r["ok"] else "server_error")
        by[r["minute"]][r["network"]][r["service"]] = True if r["ok"] else (False if (kind in fail_kinds or r["service"] == "control") else None)
    out: Dict[str, Dict[str, str]] = {}
    for minute, nets in by.items():
        out[minute] = {}
        for svc in cfg["services"]:
            per_op: Dict[str, str] = {}
            for net, res in nets.items():
                op = ops.get(net, net)
                if not res.get("control", False) or res.get(svc) is None:
                    state = "unusable"
                else:
                    state = "ok" if res[svc] else "fail"
                prev = per_op.get(op)
                # within one operator, any success wins; a usable failure beats unusable
                if prev == "ok" or state == "ok":
                    per_op[op] = "ok"
                elif prev == "fail" or state == "fail":
                    per_op[op] = "fail"
                else:
                    per_op[op] = "unusable"
            fails = sum(1 for s in per_op.values() if s == "fail")
            usable = sum(1 for s in per_op.values() if s != "unusable")
            need = cfg["operators_required"]
            out[minute][svc] = "down" if fails >= need else ("unknown" if usable < need else "up")
    return out


def events(states: Dict[str, Dict[str, str]], cfg: dict, key: Optional[str] = None) -> List[dict]:
    """Outage events for one service (key) or for the region (key=None: any service down)."""
    if not states:
        return []
    mins = sorted(states)
    t, end = datetime.strptime(mins[0], FMT), datetime.strptime(mins[-1], FMT)
    timeline = []
    while t <= end:
        m = t.strftime(FMT)
        s = states.get(m, {})
        vals = [s.get(key, "unknown")] if key else [s.get(v, "unknown") for v in cfg["services"]]
        timeline.append((m, "down" if "down" in vals else ("up" if all(v == "up" for v in vals) else "unknown"),
                         sorted(v for v in cfg["services"] if s.get(v) == "down") if not key else [key]))
        t += timedelta(minutes=1)
    out, cur, clear = [], None, 0
    for m, st, svcs in timeline:
        if st == "down":
            if cur is None:
                cur = {"start": m, "end": m, "down_minutes": 0, "unknown_minutes": 0, "services": set()}
            cur["end"], clear = m, 0
            cur["down_minutes"] += 1
            cur["services"].update(svcs)
        elif cur is not None:
            if st == "unknown":
                cur["unknown_minutes"] += 1
            else:
                clear += 1
                if clear >= cfg["recovery_minutes"]:
                    out.append(cur); cur, clear = None, 0
    if cur is not None:
        cur["ongoing"] = True
        out.append(cur)
    for e in out:
        e["duration_min"] = int((datetime.strptime(e["end"], FMT) - datetime.strptime(e["start"], FMT)).total_seconds() // 60) + 1
        e["services"] = sorted(e["services"])
        e["meets_waiting_period"] = {str(w): e["duration_min"] >= w for w in cfg["waiting_periods_min"]}
    return out


def detect(records: Iterable[dict], cfg: dict) -> dict:
    st = minute_states(list(records), cfg)
    return {"rules": cfg["version"], "minutes": len(st), "region": events(st, cfg),
            "by_service": {s: events(st, cfg, s) for s in cfg["services"]}}


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Find outage events in probe results")
    ap.add_argument("path", help="a folder of <network>.jsonl files (e.g. daily/2026-11-08/) or one file")
    ap.add_argument("--config", default="trigger_v1.json")
    a = ap.parse_args(argv)
    p = Path(a.path)
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    recs = [json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]
    print(json.dumps(detect(recs, json.loads(Path(a.config).read_text())), indent=2))


if __name__ == "__main__":
    main()
