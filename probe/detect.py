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
    """{minute: {service: 'down' | 'up' | 'unknown'}}

    An operator fails a service when at least "window_fail_share" of its usable checks over the last
    "window_minutes" failed (defaults 1.0 and 1: every check that minute failed). A rolling window with a lower share
    catches partial outages, where some calls still succeed, which a single-minute rule sees as flickering.
    Several checks a minute (probe.run --rounds) make that judgement much less noisy.
    """
    ops = cfg["operators"]
    fail_kinds = set(cfg.get("fail_kinds", ["server_error", "timeout", "network", "throttled"]))
    # minute -> operator -> service -> [failed, usable] check counts. A network's round counts only if its control
    # check in the same round worked; a failure counts only if its kind means the service was down.
    counts: Dict[str, Dict[str, Dict[str, List[int]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    rounds = defaultdict(dict)                                # (minute, network, at) -> {service: record}
    for r in records:
        rounds[(r["minute"], r["network"], r.get("at", r["minute"]))][r["service"]] = r
    for (minute, net, _), res in rounds.items():
        op = ops.get(net, net)
        ctl = res.get("control")
        if ctl is None or not ctl["ok"]:
            continue                                          # the probe itself couldn't reach the outside world
        for svc in cfg["services"]:
            r = res.get(svc)
            if r is None:
                continue
            kind = r.get("kind", "ok" if r["ok"] else "server_error")
            if not r["ok"] and kind not in fail_kinds:
                continue                                      # e.g. 403: AWS answered, so this says nothing about an outage
            c = counts[minute][op][svc]
            c[0] += 0 if r["ok"] else 1
            c[1] += 1
    minutes = sorted({k[0] for k in rounds})
    window, share = int(cfg.get("window_minutes", 1)), float(cfg.get("window_fail_share", 1.0))
    need = cfg["operators_required"]
    all_ops = sorted({op for m in counts.values() for op in m})
    out: Dict[str, Dict[str, str]] = {}
    for i, minute in enumerate(minutes):
        t_now = datetime.strptime(minute, FMT)
        recent = [m for m in minutes[max(0, i - window * 2):i + 1]
                  if (t_now - datetime.strptime(m, FMT)).total_seconds() < window * 60]
        out[minute] = {}
        for svc in cfg["services"]:
            fails = usable = 0
            for op in all_ops:
                f = sum(counts[m][op][svc][0] for m in recent if op in counts[m])
                n = sum(counts[m][op][svc][1] for m in recent if op in counts[m])
                # share 1.0 (the minute rule): an operator fails only if every usable check it made failed
                st = "unusable" if n == 0 else ("fail" if f / n >= share else "ok")
                fails += st == "fail"
                usable += st != "unusable"
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
