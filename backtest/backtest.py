"""Backtest: how would trigger v1 have handled past AWS us-east-1 outages?

  python -m backtest.backtest            # writes backtest/results.json and prints a summary

Our probes didn't exist during these events, and AWS never publishes per-API error rates, only service-level
descriptions ("largely unavailable", "elevated error rates"). So for each event we simulate what three independent
probe operators would have seen, minute by minute, and run those records through the real detection code
(probe/detect.py) with both draft rules:

  minute   trigger_v1.json, 1 check a minute (the draft as planned): a service-minute is down when 2 operators'
           checks fail that minute
  rolling  trigger_v1_rolling.json, 6 checks a minute (recommended): an operator fails a service when 10% of its
           checks in the last 10 minutes failed

Failure rates per check, by how the AWS summary describes the service (two scenarios, because "partial" is vague):
  largely unavailable 95%;  very high errors 55%;  partial 20% (low) or 50% (high);  latency only 5% or 20%.
Outside the impaired window each check fails 0.05% of the time (background noise). GitHub's network misses 15% of
minutes (late schedules). Each combination is run 30 times with different random draws.
"""
from __future__ import annotations

import json
import random
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from probe.detect import detect

ROOT = Path(__file__).resolve().parent.parent
FMT = "%Y-%m-%dT%H:%MZ"
RATES = {"largely": (0.95, 0.95), "very_high": (0.55, 0.55), "partial": (0.20, 0.50), "latency": (0.05, 0.20)}
NETWORKS = {"github": 0.15, "cloudflare": 0.0, "gcp": 0.0}          # share of minutes each network misses
NOISE, RUNS = 0.0005, 30
CHECKS_PER_MINUTE = {"minute": 1, "rolling": 6}

# How each source statement maps onto our five checks. Anything not listed here comes from the event file as is.
OVERRIDES = {
    ("2017-02-28", "lambda"): {"window_from": "s3", "cls": "partial",
                               "note": "AWS says Lambda was impacted while S3 was down, with no window; we assume S3's window"},
    ("2017-02-28", "ec2_api"): {"skip": "New instance launches (RunInstances) failed; our check is DescribeInstances"},
    ("2021-12-07", "sts"): {"start": "2021-12-07T15:30:00Z", "cls": "latency",
                            "note": "Federation latency only; GetCallerIdentity probably mostly worked; start not stated"},
    ("2021-12-22", "ec2_api"): {"skip": "Launches in one availability zone only; DescribeInstances is regional"},
    ("2024-07-30", "lambda"): {"skip": "Only functions that block on logging were affected; our function doesn't"},
}
CHECK = {"s3": "s3", "dynamodb": "dynamodb", "lambda": "lambda", "ec2_api": "ec2", "sts": "sts"}


def _t(s: str) -> datetime:
    return datetime.strptime(s.replace(":00Z", "Z")[:16] + "Z", FMT) if len(s) > 17 else datetime.strptime(s, FMT)


def severity_class(text: str) -> str:
    t = (text or "").lower()
    if "largely" in t:
        return "largely"
    if "very high" in t:
        return "very_high"
    return "partial"


def impairments(ev: dict) -> tuple:
    """[(check, start, end, class, note)], [(check, reason skipped)]"""
    use, skipped = [], []
    for svc, v in ev["services"].items():
        if not v.get("impaired"):
            continue
        o = OVERRIDES.get((ev["id"], svc), {})
        if "skip" in o:
            skipped.append((CHECK[svc], o["skip"]))
            continue
        src = ev["services"][o["window_from"]] if "window_from" in o else v
        start, end = o.get("start") or src.get("start_utc"), o.get("end") or src.get("end_utc")
        if not start or not end:
            skipped.append((CHECK[svc], "impaired, but the source gives no time window"))
            continue
        use.append((CHECK[svc], _t(start), _t(end), o.get("cls") or severity_class(v.get("severity")), o.get("note") or ""))
    return use, skipped


def simulate(imps, scenario: int, rng: random.Random, per_minute: int = 1):
    t0 = min(i[1] for i in imps) - timedelta(minutes=20)
    t1 = max(i[2] for i in imps) + timedelta(minutes=20)
    recs, t = [], t0
    services = ["s3", "dynamodb", "lambda", "ec2", "sts"]
    while t <= t1:
        minute = t.strftime(FMT)
        for net, miss in NETWORKS.items():
            if rng.random() < miss:
                continue
            for k in range(per_minute):
                at = f"{minute}/{k}"
                recs.append({"network": net, "minute": minute, "at": at, "service": "control", "ok": rng.random() > 0.001, "kind": "network"})
                for svc in services:
                    p = NOISE
                    for c, a, b, cls, _ in imps:
                        if c == svc and a <= t <= b:
                            p = max(p, RATES[cls][scenario])
                    ok = rng.random() >= p
                    recs.append({"network": net, "minute": minute, "at": at, "service": svc, "ok": ok, "kind": "ok" if ok else "server_error"})
        t += timedelta(minutes=1)
    return recs


def summarise(results, waits):
    longest = [max([e["duration_min"] for e in r["region"]], default=0) for r in results]
    down = [sum(e["down_minutes"] for e in r["region"]) for r in results]
    return {"p_meets": {str(w): sum(1 for x in longest if x >= w) / len(longest) for w in waits},
            "longest_event_min_median": int(statistics.median(longest)),
            "longest_event_min_range": [min(longest), max(longest)],
            "down_minutes_median": int(statistics.median(down)),
            "events_median": int(statistics.median(len(r["region"]) for r in results))}


def false_positive_checks(rules):
    """Situations that must NOT trigger: one operator's trouble, or our own mistakes."""
    rng = random.Random(7)
    start = datetime(2026, 11, 3, 12, 0)
    cases = {}

    def run(build):
        recs = []
        for i in range(240):
            t = (start + timedelta(minutes=i)).strftime(FMT)
            recs += build(i, t)
        return {name: max([e["duration_min"] for e in detect(recs, cfg)["region"]], default=0) for name, cfg in rules.items()}

    def rows(net, t, control=True, fail=False, kind="server_error"):
        out = [{"network": net, "minute": t, "service": "control", "ok": control, "kind": "network"}]
        for s in ["s3", "dynamodb", "lambda", "ec2", "sts"]:
            bad = fail or not control
            out.append({"network": net, "minute": t, "service": s, "ok": not bad, "kind": kind if bad else "ok"})
        return out

    cases["Microsoft-only problem for 3 hours (GitHub and Azure both fail, Cloudflare fine)"] = run(
        lambda i, t: rows("github", t, fail=60 <= i < 240) + rows("azure", t, fail=60 <= i < 240) + rows("cloudflare", t))
    cases["One probe network loses its internet for 3 hours"] = run(
        lambda i, t: rows("cloudflare", t, control=not (60 <= i < 240)) + rows("gcp", t) + rows("github", t))
    cases["Our AWS credentials expire on every network (AWS answers 403)"] = run(
        lambda i, t: sum((rows(n, t, fail=i >= 60, kind="client_error") for n in ("github", "cloudflare", "gcp")), []))
    cases["Real outage seen by two operators for 3 hours (control)"] = run(
        lambda i, t: rows("cloudflare", t, fail=60 <= i < 240) + rows("gcp", t, fail=60 <= i < 240) + rows("github", t))
    return cases


def main():
    events = json.loads((ROOT / "backtest" / "aws_us_east_1_events.json").read_text())["events"]
    rules = {"minute": json.loads((ROOT / "trigger_v1.json").read_text()),
             "rolling": json.loads((ROOT / "trigger_v1_rolling.json").read_text())}
    waits = rules["minute"]["waiting_periods_min"]
    out = {"method": __doc__, "rates": RATES, "runs": RUNS, "events": [], "false_positives": false_positive_checks(rules)}
    for ev in events:
        imps, skipped = impairments(ev)
        row = {"id": ev["id"], "title": ev["title"], "scope": ev["scope"], "start_utc": ev["start_utc"], "end_utc": ev["end_utc"],
               "duration_min": ev.get("duration_min"), "confidence": ev.get("confidence"),
               "secondary_source_only": ev.get("secondary_source_only", False), "sources": ev.get("sources", []),
               "checks_impaired": [{"check": c, "start": a.strftime(FMT), "end": b.strftime(FMT), "class": cls, "note": n}
                                   for c, a, b, cls, n in imps],
               "not_counted": [{"check": c, "reason": r} for c, r in skipped], "results": {}}
        if imps:
            for si, sname in enumerate(["low", "high"]):
                for rname, cfg in rules.items():
                    rng = random.Random(f"{ev['id']}-{sname}-{rname}")
                    res = [detect(simulate(imps, si, rng, CHECKS_PER_MINUTE[rname]), cfg) for _ in range(RUNS)]
                    row["results"][f"{rname}/{sname}"] = summarise(res, waits)
        out["events"].append(row)
        r = row["results"]
        print(f"{ev['id']:<11} {ev['scope']:<10} checks hit: {','.join(sorted({c['check'] for c in row['checks_impaired']})) or '-':<26}"
              + "  ".join(f"{k}: >=60 {v['p_meets']['60']:.0%} >=120 {v['p_meets']['120']:.0%} (longest ~{v['longest_event_min_median']}m)"
                          for k, v in r.items()))
    # how the rolling rule's threshold changes which events pay (6 checks a minute)
    out["sensitivity"] = {}
    for share in (0.10, 0.25, 0.50):
        cfg = dict(rules["rolling"], window_fail_share=share)
        for si, sname in enumerate(["low", "high"]):
            hits = {}
            for ev in events:
                imps, _ = impairments(ev)
                if not imps:
                    continue
                rng = random.Random(f"sens-{ev['id']}-{share}-{sname}")
                res = [detect(simulate(imps, si, rng, 6), cfg) for _ in range(15)]
                hits[ev["id"]] = summarise(res, waits)["p_meets"]
            out["sensitivity"][f"{int(share * 100)}%/{sname}"] = hits
            print(f"threshold {share:.0%} {sname}: meets 2h in " + ", ".join(f"{k}:{v['120']:.0%}" for k, v in hits.items()))
    print("\nMust not trigger:")
    for k, v in out["false_positives"].items():
        print(f"  {k}: longest event minute rule {v['minute']} min, rolling rule {v['rolling']} min")
    (ROOT / "backtest" / "results.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
