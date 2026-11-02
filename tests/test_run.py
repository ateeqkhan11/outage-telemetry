import base64
import json

from probe.chain import load_private, load_public, public_b64, verify
from probe.daily import build_day
from probe.run import run_minutes
from probe.store import LocalStore, read_jsonl

KEY = load_private(base64.b64encode(bytes(range(32))).decode())


def ok():
    pass


def boom():
    raise TimeoutError("timed out")


def fake_clock(start):
    t = [start]
    def clock():
        return t[0]
    def sleep(s):
        t[0] += s
    return clock, sleep


def test_run_writes_one_object_per_minute_and_continues_the_chain(tmp_path):
    store = LocalStore(tmp_path)
    clock, sleep = fake_clock(1793714700.0)                 # 2026-11-03 14:05:00 UTC
    checks = [("s3", "GetObject", ok), ("dynamodb", "GetItem", boom)]
    n = run_minutes("local", 3, store, KEY, checks, ("control", "HTTPS GET", ok), wait=True, clock=clock, sleep=sleep)
    assert n == 9
    runs = store.list("runs/local/")
    assert len(runs) == 3 and all(k.endswith(".jsonl") for k in runs)
    recs = [r for k in runs for r in read_jsonl(store.get(k))]
    assert [r["seq"] for r in recs] == list(range(1, 10))
    assert verify(recs, load_public(public_b64(KEY))) == []
    failed = [r for r in recs if not r["ok"]]
    assert len(failed) == 3 and all(r["service"] == "dynamodb" and r["error"].startswith("TimeoutError") for r in failed)
    assert all(r["kind"] == "timeout" for r in failed) and all(r["kind"] == "ok" for r in recs if r["ok"])
    # a second run picks up from the saved head
    run_minutes("local", 1, store, KEY, checks, ("control", "HTTPS GET", ok), wait=True, clock=clock, sleep=sleep)
    head = json.loads(store.get("chains/local/head.json"))
    assert head["seq"] == 12


def test_daily_file_verifies_and_reports_gaps(tmp_path):
    store = LocalStore(tmp_path / "s")
    clock, sleep = fake_clock(1793714700.0)
    run_minutes("local", 5, store, KEY, [("s3", "GetObject", ok)], ("control", "HTTPS GET", ok), clock=clock, sleep=sleep)
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "local.pub").write_text(public_b64(KEY))
    m = build_day(store, "2026-11-03", str(keys))
    s = m["networks"]["local"]
    assert s["chain_valid"] and s["records"] == 10 and s["minutes_covered"] == 5
    assert s["longest_gap_min"] > 0 and len(s["sha256"]) == 64
    assert store.get("daily/2026-11-03/local.jsonl") and store.get("daily/2026-11-03/manifest.json")
