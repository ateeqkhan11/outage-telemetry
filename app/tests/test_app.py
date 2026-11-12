"""App tests: counting matches the probe's own outage rule, sign-in and invites, CSRF, admin, API keys, reports."""
import json
import re
import sys
from html import unescape as html_unescape
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from nimbus_app import create_app, mirror  # noqa: E402
from probe.chain import GENESIS, seal  # noqa: E402
from probe.detect import detect  # noqa: E402

DAY = "2026-11-10"
SERVICES = ["control", "s3", "dynamodb", "lambda", "ec2", "sts"]
CFG = json.loads((ROOT / "trigger_v1_rolling.json").read_text())


def make_data(root: Path):
    """90 minutes from 3 networks, 6 rounds a minute. From minute 30 to 59, S3 fails with 503 on github and
    cloudflare (an outage); on the aws reference network it fails all along (never counted)."""
    all_recs = []
    t0 = datetime(2026, 11, 10, 10, 0)
    for net in ("github", "cloudflare", "aws"):
        key, prev, seq = Ed25519PrivateKey.generate(), GENESIS, 0
        for i in range(90):
            t = t0 + timedelta(minutes=i)
            minute = t.strftime("%Y-%m-%dT%H:%MZ")
            lines = []
            for k in range(6):
                at = (t + timedelta(seconds=10 * k)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                for svc in SERVICES:
                    bad = svc == "s3" and (net == "aws" or 30 <= i < 60)
                    rec = {"v": 1, "network": net, "host": "test", "target": "us-east-1", "service": svc, "op": "x",
                           "minute": minute, "at": at, "ok": not bad, "kind": "server_error" if bad else "ok",
                           "latency_ms": 100, "error": "HTTP 503" if bad else None, "status": 503 if bad else None}
                    seq += 1
                    rec = seal(rec, prev, seq, key)
                    prev = rec["hash"]
                    lines.append(rec)
            all_recs += lines
            f = root / "runs" / net / DAY / f"{t:%H%M}.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in lines))
    (root / "status").mkdir(parents=True, exist_ok=True)
    (root / "status" / "latest.json").write_text(json.dumps({
        "generated_at": "2026-11-10T11:30:00Z", "region": "us-east-1", "last_minute": "2026-11-10T11:29Z",
        "can_decide": True, "overall": "up", "independent_operators": ["cloudflare", "microsoft"],
        "services": {s: {"state": "up", "uptime_pct": 99.0, "checks": 1, "failed": 0, "latency_ms_p50_last_hour": {}}
                     for s in CFG["services"]},
        "networks": {n: {"operator": n, "counted": n != "aws", "last_minute": "x", "minutes_covered": 90,
                         "longest_gap_min": 0, "records": 1, "chain_valid": True} for n in ("github", "cloudflare", "aws")},
        "outages": []}))
    return all_recs


@pytest.fixture()
def env(tmp_path):
    recs = make_data(tmp_path / "data")
    app = create_app({"DB_PATH": str(tmp_path / "t.db"), "DATA_DIR": str(tmp_path / "data"), "SECURE_COOKIES": False,
                      "TESTING": True})
    mirror.ingest(app.config["DATA_DIR"], app.config["DB_PATH"], app.config["RULES"])
    from nimbus_app import auth
    auth._ip_attempts.clear()
    return app, recs, tmp_path


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def invite_and_join(app, client, email="pilot@example.com", admin=False):
    with app.test_request_context():
        from nimbus_app import auth
        tok = auth.create_invite(email, "Pat", "Example MGA", "admin" if admin else "member")
    page = client.get(f"/invite/{tok}").get_data(as_text=True)
    r = client.post(f"/invite/{tok}", data={"csrf": csrf_of(page), "name": "Pat Pilot", "company": "Example MGA",
                                            "password": "a-long-test-password", "password2": "a-long-test-password"})
    assert r.status_code == 302, r.get_data(as_text=True)
    return tok


def test_counts_match_the_probe_rule(env):
    app, recs, _ = env
    from nimbus_app import reports
    from nimbus_app.db import connect
    db = connect(app.config["DB_PATH"])
    d = datetime(2026, 11, 10).date()
    rep = reports.report(db, CFG, d, d)
    direct = detect(recs, CFG)["region"]
    assert len(rep["outages"]) == 1 and len(direct) == 1
    for k in ("start", "end", "duration_min", "services"):
        assert rep["outages"][0][k] == direct[0][k]
    assert rep["outages"][0]["services"] == ["s3"]
    assert rep["summary"]["s3"]["down_minutes"] > 0 and rep["summary"]["dynamodb"]["down_minutes"] == 0
    assert rep["summary"]["dynamodb"]["official_uptime_pct"] == 100.0
    assert rep["networks"]["aws"]["counted"] is False
    assert rep["summary"]["s3"]["networks"]["aws"]["ok_pct"] == 0.0     # reference network: raw numbers only


def test_moved_files_are_uncounted(env):
    app, _, tmp = env
    f = tmp / "data" / "runs" / "github" / DAY / "1000.jsonl"
    dest = tmp / "data" / "archive" / "forks" / "1000.jsonl"
    dest.parent.mkdir(parents=True)
    f.rename(dest)
    out = mirror.ingest(app.config["DATA_DIR"], app.config["DB_PATH"], app.config["RULES"])
    assert out["files_removed"] == 1


def test_pages_need_sign_in_and_invites_work(env):
    app, _, _ = env
    c = app.test_client()
    assert c.get("/").status_code == 200
    r = c.get("/dashboard")
    assert r.status_code == 302 and "/sign-in" in r.headers["Location"]
    assert c.get("/api/v1/status").status_code == 401
    tok = invite_and_join(app, c)
    assert c.get("/dashboard").status_code == 200
    assert c.get("/dashboard/status.json").get_json()["can_decide"] is True
    assert c.get(f"/invite/{tok}").status_code == 410          # single use
    assert c.get("/admin/").status_code == 403                 # members aren't admins
    r = c.get("/reports?from=2026-11-10&to=2026-11-10")
    assert r.status_code == 200 and "Trigger ladder" in r.get_data(as_text=True)
    csv_ = c.get("/reports.csv?from=2026-11-10&to=2026-11-10").get_data(as_text=True)
    assert csv_.splitlines()[0].startswith("date,service,official_uptime_pct")
    body = c.get(f"/records/cloudflare/{DAY}.jsonl").get_data(as_text=True).splitlines()
    assert len(body) == 90 * 36 and [json.loads(x)["seq"] for x in body[:3]] == [1, 2, 3]
    assert c.get("/records/..%2Fetc/2026-11-10.jsonl").status_code == 404
    assert "at most 31 days" in c.get("/reports?from=2026-01-01&to=2026-11-10").get_data(as_text=True)


def test_csrf_and_lockout(env):
    app, _, _ = env
    c = app.test_client()
    invite_and_join(app, c)
    assert c.post("/sign-out").status_code == 400               # no CSRF token
    page = c.get("/account").get_data(as_text=True)
    c.post("/sign-out", data={"csrf": csrf_of(page)})
    assert c.get("/dashboard").status_code == 302
    page = c.get("/sign-in").get_data(as_text=True)
    tok = csrf_of(page)
    for _ in range(5):
        r = c.post("/sign-in", data={"csrf": tok, "email": "pilot@example.com", "password": "wrong-password-xx"})
    r = c.post("/sign-in", data={"csrf": tok, "email": "pilot@example.com", "password": "a-long-test-password"})
    assert "Too many wrong passwords" in r.get_data(as_text=True)


def test_request_access_to_admin_invite(env):
    app, _, _ = env
    visitor = app.test_client()
    page = visitor.get("/request-access").get_data(as_text=True)
    r = visitor.post("/request-access", data={"csrf": csrf_of(page), "name": "Sam", "email": "sam@mga.example",
                                              "company": "Some MGA", "use_case": "cloud outage cover"})
    assert "we have your request" in r.get_data(as_text=True)
    admin = app.test_client()
    invite_and_join(app, admin, "ateeq@example.com", admin=True)
    page = admin.get("/admin/").get_data(as_text=True)
    assert "Some MGA" in page
    req_id = re.search(r'name="request_id" value="(\d+)"', page).group(1)
    admin.post("/admin/invite", data={"csrf": csrf_of(page), "request_id": req_id})
    page = admin.get("/admin/").get_data(as_text=True)
    link = re.search(r'(http://localhost/invite/[\w-]+)', page).group(1)
    assert visitor.get(link.replace("http://localhost", "")).status_code == 200
    assert link not in admin.get("/admin/").get_data(as_text=True)   # shown once


def test_api_keys(env):
    app, _, _ = env
    c = app.test_client()
    invite_and_join(app, c)
    page = c.get("/api-access").get_data(as_text=True)
    page = c.post("/api-access", data={"csrf": csrf_of(page), "action": "create", "name": "checker"}).get_data(as_text=True)
    key = re.search(r"(nk_live_[\w-]+)", page).group(1)
    api = app.test_client()
    h = {"Authorization": f"Bearer {key}"}
    s = api.get("/api/v1/status", headers=h).get_json()
    assert s["can_decide"] is True and "s3" in s["services"]
    m = api.get("/api/v1/minutes?from=2026-11-10T10:40Z&to=2026-11-10T10:45Z", headers=h).get_json()
    assert [x["services"]["s3"] for x in m["minutes"]] == ["down"] * 5
    u = api.get("/api/v1/uptime?from=2026-11-10&to=2026-11-10", headers=h).get_json()
    assert u["summary"]["s3"]["down_minutes"] > 0 and "daily" not in u
    o = api.get("/api/v1/outages?from=2026-11-10&to=2026-11-10", headers=h).get_json()
    assert len(o["outages"]) == 1
    assert api.get(f"/api/v1/records/github/{DAY}", headers=h).status_code == 200
    assert "github" in api.get("/api/v1/keys", headers=h).get_json()["keys"]
    assert api.get("/api/v1/uptime?from=2026-01-01&to=2026-11-10", headers=h).status_code == 400
    page = c.get("/api-access").get_data(as_text=True)
    assert key not in page                                       # shown only once
    kid = re.search(r'name="key_id" value="(\d+)"', page).group(1)
    c.post("/api-access", data={"csrf": csrf_of(page), "action": "revoke", "key_id": kid})
    assert api.get("/api/v1/status", headers=h).status_code == 401


def test_history_matches_the_minute_rule(env):
    app, recs, _ = env
    from nimbus_app import history
    from nimbus_app.db import connect
    db = connect(app.config["DB_PATH"])
    d = datetime(2026, 11, 10).date()
    assert db.execute("SELECT COUNT(*) FROM daily_states WHERE day = ? AND definition = 'degraded'", (DAY,)).fetchone()[0] == 6
    assert db.execute("SELECT COUNT(DISTINCT definition) FROM daily_states WHERE day = ?", (DAY,)).fetchone()[0] == 2
    ov = history.overview(db, CFG, d, d)
    direct = detect(recs, CFG)["region"]
    assert len(ov["outages"]) == 1
    for k in ("start", "end", "duration_min", "services", "down_minutes", "meets_waiting_period"):
        assert ov["outages"][0][k] == direct[0][k]
    s3 = ov["summary"]["s3"]
    assert s3["days"][0]["cls"] == "minor" and s3["down_minutes"] == direct[0]["down_minutes"]
    assert ov["summary"]["dynamodb"]["down_minutes"] == 0
    assert ov["summary"]["*"]["undecided_minutes"] == 1440 - ov["summary"]["*"]["judged_minutes"]   # no data = undecided
    assert ov["networks"]["aws"]["counted"] is False


def test_events_from_runs_edge_cases():
    """Stretches split at midnight, undecided minutes inside an outage, and a short recovery that doesn't end it."""
    from nimbus_app.history import events_from_runs
    from probe.detect import events
    cfg = dict(CFG, services=["s3"])
    states = {}
    t = datetime(2026, 7, 1, 23, 0)
    pattern = ["up"] * 5 + ["down"] * 70 + ["up"] * 2 + ["unknown"] * 4 + ["down"] * 10 + ["up"] * 3 + ["down"] * 5 + ["up"] * 20
    for st in pattern:
        states[t.strftime("%Y-%m-%dT%H:%MZ")] = {"s3": st}
        t += timedelta(minutes=1)
    mins = sorted(states)
    runs, cur = [], None
    for m in mins:
        st = states[m]["s3"]
        if cur and cur[0] == st and m[:10] == cur[1][:10]:
            cur[2] = m
        else:
            if cur and cur[0] != "up":
                runs.append(tuple(cur))
            cur = [st, m, m]
    if cur[0] != "up":
        runs.append(tuple(cur))
    got = events_from_runs(runs, [("s3", a, b) for s, a, b in runs if s == "down"], cfg, mins[0], mins[-1])
    want = events(states, cfg)
    assert [(e["start"], e["end"], e["down_minutes"], e["unknown_minutes"], e["duration_min"]) for e in got] == \
           [(e["start"], e["end"], e["down_minutes"], e["unknown_minutes"], e["duration_min"]) for e in want]
    assert len(got) == 2


def test_history_page(env):
    app, _, _ = env
    c = app.test_client()
    assert c.get("/history").status_code == 302
    invite_and_join(app, c)
    r = c.get("/history?from=2026-11-01&to=2026-11-10")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Trigger ladder" in html and "1 h not met" in html
    assert "Example data" not in html
    page = c.get("/api-access").get_data(as_text=True)
    page = c.post("/api-access", data={"csrf": csrf_of(page), "action": "create", "name": "h"}).get_data(as_text=True)
    key = re.search(r"(nk_live_[\w-]+)", page).group(1)
    h = app.test_client().get("/api/v1/history?from=2026-11-10&to=2026-11-10", headers={"Authorization": f"Bearer {key}"}).get_json()
    assert len(h["outages"]) == 1 and h["uptime"]["s3"]["down_minutes"] > 0 and len(h["daily"]) == 5



def test_hard_down_and_degraded_differ(env):
    """The fixture's S3 fails 100% on two companies for 30 minutes: both definitions call it, hard-down tighter."""
    app, recs, _ = env
    from nimbus_app import history, reports
    from nimbus_app.db import connect
    db = connect(app.config["DB_PATH"])
    d = datetime(2026, 11, 10).date()
    deg = history.overview(db, CFG, d, d, "degraded")["outages"]
    hard = history.overview(db, CFG, d, d, "hard_down")["outages"]
    assert len(deg) == 1 and len(hard) == 1
    assert hard[0]["duration_min"] <= deg[0]["duration_min"]
    direct = detect(recs, reports.definition_cfg(CFG, "hard_down"))["region"]       # same rule, straight from records
    assert (hard[0]["start"], hard[0]["end"]) == (direct[0]["start"], direct[0]["end"])
    assert reports.report(db, CFG, d, d, definition="hard_down")["outages"][0]["start"] == direct[0]["start"]


def test_replay_terms():
    """Merge window, rounding, waiting period and limits, on hand-made stretches."""
    import sqlite3
    from nimbus_app import db as dbm, history
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(dbm.SCHEMA)
    rows = [("2026-07-01", "hard_down", "*", "down", "2026-07-01T10:00Z", "2026-07-01T10:52Z"),   # 53 min
            ("2026-07-01", "hard_down", "s3", "down", "2026-07-01T10:00Z", "2026-07-01T10:52Z"),
            ("2026-07-01", "hard_down", "*", "down", "2026-07-01T11:10Z", "2026-07-01T12:11Z"),   # 62 min, 17 min gap
            ("2026-07-01", "hard_down", "s3", "down", "2026-07-01T11:10Z", "2026-07-01T12:11Z"),
            ("2026-07-01", "hard_down", "*", "down", "2026-07-01T18:00Z", "2026-07-01T21:59Z"),   # 240 min, separate
            ("2026-07-01", "hard_down", "dynamodb", "down", "2026-07-01T18:00Z", "2026-07-01T21:59Z")]
    con.executemany("INSERT INTO state_runs (day, definition, service, state, start, end) VALUES (?, ?, ?, ?, ?, ?)", rows)
    d = datetime(2026, 7, 1).date()
    r = history.replay(con, CFG, d, d, {"definition": "hard_down", "waiting_min": 60, "hourly": 6000, "merge_gap_min": 30,
                                        "rounding_min": 5, "event_limit": 15000, "aggregate_limit": 20000})
    a, b = r["events"]
    assert len(a["parts"]) == 2 and a["minutes"] == 55 + 65          # rounded up to 5 min each, gap not counted
    assert a["indemnity_min"] == 60 and a["payout"] == 6000          # one waiting period for the merged event
    assert b["indemnity_min"] == 180 and b["payout"] == 14000 and b["capped"]   # 18,000 capped by what's left of 20,000
    only_s3 = history.replay(con, CFG, d, d, {"definition": "hard_down", "services": ["s3"], "waiting_min": 60})
    assert len(only_s3["events"]) == 1                               # the DynamoDB outage is not insured
    split = history.replay(con, CFG, d, d, {"definition": "hard_down", "merge_gap_min": 10, "waiting_min": 0})
    assert len(split["events"]) == 3


def test_certificate_signed_and_checkable(env):
    app, _, tmp = env
    c = app.test_client()
    invite_and_join(app, c)
    page = c.get("/policy?from=2026-11-10&to=2026-11-10&def=degraded&waiting_min=0").get_data(as_text=True)
    assert "Would have paid" in page
    link = html_unescape(re.search(r'href="(/certificate\?[^"]+)"', page).group(1))
    assert "Signed by Nimbus Index" in c.get(link).get_data(as_text=True)
    cert = json.loads(c.get(link + "&format=json").get_data(as_text=True))
    from nimbus_app import certificates
    assert certificates.verify(cert) and cert["policy"]["payout"] > 0
    assert set(cert["evidence"]) == {"github", "cloudflare", "aws"}
    tampered = dict(cert, outage=dict(cert["outage"], minutes=cert["outage"]["minutes"] + 60))
    assert not certificates.verify(tampered)
