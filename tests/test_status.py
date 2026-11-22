"""Fix 2: no official call until enough independent companies have enough recent coverage."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from probe.status import build, readiness
from probe.store import LocalStore, to_jsonl

CFG = json.loads((Path(__file__).parent.parent / "trigger_v1_rolling.json").read_text())
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def minutes(hours_back: float, every: int = 1, stop_back_min: int = 1):
    end = NOW - timedelta(minutes=stop_back_min)
    t = NOW - timedelta(hours=hours_back)
    out = []
    while t <= end:
        out.append(t.strftime("%Y-%m-%dT%H:%MZ"))
        t += timedelta(minutes=every)
    return out


def test_two_companies_with_full_recent_coverage_can_decide():
    r = readiness({"microsoft": set(minutes(24)), "cloudflare": set(minutes(24))}, NOW, CFG)
    assert r["ok"] and r["reason"] is None


def test_low_coverage_means_not_enough_data():
    patchy = set(minutes(24, every=2))                     # about 50% of the day
    r = readiness({"microsoft": patchy, "cloudflare": set(minutes(24))}, NOW, CFG)
    assert not r["ok"]
    assert "microsoft" in r["reason"] and "95%" in r["reason"]
    assert r["operators"]["microsoft"]["meets_rule"] is False


def test_stale_company_means_not_enough_data():
    stale = set(minutes(24, stop_back_min=40))              # full day but silent for the last 40 minutes
    r = readiness({"microsoft": stale, "cloudflare": set(minutes(24))}, NOW, CFG)
    assert not r["ok"] and "last report" in r["reason"]


def test_one_company_is_never_enough():
    r = readiness({"cloudflare": set(minutes(24))}, NOW, CFG)
    assert not r["ok"] and "1 of the 2" in r["reason"]


def _records(network, mins, seq0=1):
    out, seq = [], seq0
    for m in mins:
        for svc in ["control"] + CFG["services"]:
            out.append({"network": network, "minute": m, "service": svc, "ok": True, "kind": "ok", "error": None,
                        "latency_ms": 50, "seq": seq, "at": m[:-1] + ":00.000Z", "host": network})
            seq += 1
    return out


def test_status_file_withholds_the_call_until_coverage_is_met(tmp_path):
    store = LocalStore(tmp_path)
    for net, mins in (("github", minutes(24, every=2)), ("cloudflare", minutes(24))):
        recs = _records(net, mins)
        store.put(f"runs/{net}/2026-11-22/all.jsonl", to_jsonl(recs))
    s = build(store, str(tmp_path / "keys"), CFG, now=NOW)
    assert s["can_decide"] is False
    assert s["readiness"]["reason"].startswith("Not enough data")
    assert s["networks"]["cloudflare"]["age_min"] <= 2 and s["networks"]["github"]["coverage_pct"] < 95
