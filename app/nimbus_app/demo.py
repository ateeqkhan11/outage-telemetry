"""Build an example-data copy of the app: six months of SIMULATED measurements, to show firms what the product looks like
with a track record. Nothing here is a real AWS result; the app shows an "Example data" banner on every page.

  python -m nimbus_app.demo --out instance/demo [--days 180]

then run the app with NIMBUS_DEMO=1 NIMBUS_DB=<out>/nimbus.db NIMBUS_DATA=<out>/data NIMBUS_KEYS=<out>/keys
(app/run_demo.sh does this). It writes:
  <out>/nimbus.db          minute counts for the last 31 days, daily roll-ups for the whole period, one demo sign-in
  <out>/data/runs/...      signed per-minute records for the last 25 hours (made with throwaway keys), so the
                           dashboard, downloads and "verify this record" work exactly as with real data
  <out>/data/status/latest.json   built by probe.status from those records
  <out>/keys/*.pub         the throwaway public keys (the private keys are never saved)
  <out>/demo_credentials.local.txt   the demo sign-in

The same simulated "truth" drives both the signed records and the older counts: a background error rate, a set of
outages of different shapes (partial, multi-service, short blips), one probe network seeing a problem alone (never
counted), and gaps when a probe network itself was down.
"""
from __future__ import annotations

import argparse
import json
import random
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from probe.chain import GENESIS, public_b64, seal
from probe.detect import FMT

NETWORKS = {   # network -> (host label, base latency ms)
    "github": ("github-actions eastus (example)", 22),
    "cloudflare": ("cloudflare-workers (example)", 31),
    "gcp": ("gcp cloud-run us-east4 (example)", 14),
    "aws": ("aws-lambda us-west-2 reference (example)", 78),
}
SERVICES = {"s3": ("GetObject", 12), "dynamodb": ("GetItem", 6), "lambda": ("Invoke", 28), "ec2": ("DescribeInstances", 41),
            "sts": ("GetCallerIdentity", 9)}
BASE_FAIL = 0.00025          # chance any single call fails on a normal day
ROUNDS = 6
KEEP_MINUTE_DAYS = 31


def scenario(start: datetime, now: datetime):
    """Simulated incidents. Offsets in days from the start of the period keep the shape whatever the run date."""
    def at(day, hh, mm):
        return start + timedelta(days=day, hours=hh, minutes=mm)
    outages = [  # (when, {service: (fail share, starts after min, lasts min)}, networks affected or None = all)
        (at(19, 14, 12), {"s3": (0.35, 0, 38)}, None),                                         # partial S3 errors
        (at(43, 9, 41), {"sts": (0.9, 0, 12)}, None),                                          # short STS blip
        (at(65, 18, 5), {"dynamodb": (0.8, 0, 167), "lambda": (0.55, 6, 175)}, None),          # DynamoDB, Lambda follows
        (at(98, 3, 30), {"ec2": (0.6, 0, 95)}, None),                                          # EC2 API, night
        (at(123, 22, 48), {"lambda": (0.4, 0, 64)}, None),                                     # Lambda, partial
        (at(152, 11, 20), {"dynamodb": (0.95, 0, 250), "lambda": (0.7, 5, 280), "ec2": (0.5, 40, 200),
                           "sts": (0.3, 20, 90)}, None),                                       # the big one
        (at(171, 16, 20), {"s3": (0.5, 0, 7)}, None),                                          # 7-minute blip
        (now - timedelta(hours=9, minutes=14), {"s3": (0.3, 0, 9)}, None),                     # yesterday-ish, small
        (at(50, 13, 0), {"dynamodb": (0.7, 0, 25)}, {"gcp"}),                                  # one operator alone
    ]
    gaps = [("cloudflare", at(86, 1, 0), 190), ("github", at(134, 7, 15), 42), ("gcp", at(160, 20, 0), 75)]
    return outages, gaps


class Truth:
    def __init__(self, start, now, seed=11):
        self.outages, self.gaps = scenario(start, now)
        self.rng = random.Random(seed)

    def share(self, net, t, svc):
        for when, svcs, nets in self.outages:
            if svc in svcs and (nets is None or net in nets):
                sh, off, mins = svcs[svc]
                a = when + timedelta(minutes=off)
                if a <= t < a + timedelta(minutes=mins):
                    return sh
        return 0.0

    def gap(self, net, t):
        return any(n == net and a <= t < a + timedelta(minutes=m) for n, a, m in self.gaps)

    def latency(self, net, svc, failing):
        base = NETWORKS[net][1] + SERVICES.get(svc, ("HTTPS GET", 4))[1]
        return int(base * (0.75 + 0.5 * self.rng.random()) * (6 if failing else 1))


def _iter_minutes(a, b):
    t = a
    while t < b:
        yield t
        t += timedelta(minutes=1)


def count_rows(truth: Truth, day_start: datetime, day_end: datetime, cfg):
    """minute_counts rows straight from the simulated truth (no records), like mirror.file_counts would make them."""
    reference = set(cfg.get("reference_networks", []))
    rng = truth.rng
    rows = []
    for t in _iter_minutes(day_start, day_end):
        m = t.strftime(FMT)
        for net in NETWORKS:
            if truth.gap(net, t):
                continue
            for svc in SERVICES:
                sh = truth.share(net, t, svc)
                if sh:
                    failed = sum(rng.random() < sh for _ in range(ROUNDS))
                else:
                    failed = 1 if rng.random() < BASE_FAIL * ROUNDS else 0
                ok = ROUNDS - failed
                lat = truth.latency(net, svc, sh > 0) * ok
                counted = net not in reference
                rows.append((f"demo/{net}/{m[:10]}", net, m, svc, ROUNDS, ok, failed if counted else 0,
                             ROUNDS if counted else 0, lat, ok))
    return rows


def signed_files(truth: Truth, a: datetime, b: datetime, data_dir: Path, keys: dict):
    rng = truth.rng
    for net, key in keys.items():
        host = NETWORKS[net][0]
        prev, seq = GENESIS, int((a - datetime(2026, 1, 1)).total_seconds() // 60) * ROUNDS * 6
        for t in _iter_minutes(a, b):
            if truth.gap(net, t):
                continue
            m = t.strftime(FMT)
            lines = []
            for k in range(ROUNDS):
                at = (t + timedelta(seconds=10 * k, milliseconds=rng.randint(40, 900))).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                checks = [("control", "HTTPS GET", 0.0)] + [(s, SERVICES[s][0], truth.share(net, t, s)) for s in SERVICES]
                for svc, op, sh in checks:
                    bad = rng.random() < (sh or BASE_FAIL)
                    kind = rng.choice(["server_error", "timeout"]) if bad else "ok"
                    rec = {"v": 1, "network": net, "host": host, "target": "us-east-1", "service": svc, "op": op,
                           "minute": m, "at": at, "ok": not bad, "kind": kind,
                           "latency_ms": 5000 if kind == "timeout" else truth.latency(net, svc, bad),
                           "error": ("HTTP 503 Service Unavailable" if kind == "server_error" else "timed out after 5 s") if bad else None,
                           "status": 503 if kind == "server_error" else None}
                    seq += 1
                    rec = seal(rec, prev, seq, key)
                    prev = rec["hash"]
                    lines.append(rec)
            f = data_dir / "runs" / net / m[:10] / f"{t:%H%M}.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in lines))


def build(out: Path, days: int = 180, now: datetime = None) -> dict:
    from . import create_app, history, mirror
    from .db import connect
    from probe.status import build as build_status
    from probe.store import open_store

    now = (now or datetime.utcnow()).replace(second=0, microsecond=0)
    start = datetime.combine((now - timedelta(days=days - 1)).date(), datetime.min.time())
    signed_from = now - timedelta(hours=25)
    if out.exists():
        shutil.rmtree(out)
    (out / "keys").mkdir(parents=True)
    data_dir = out / "data"
    keys = {net: Ed25519PrivateKey.generate() for net in NETWORKS}
    for net, k in keys.items():
        (out / "keys" / f"{net}.pub").write_text(public_b64(k) + "\n")

    app = create_app({"DB_PATH": str(out / "nimbus.db"), "DATA_DIR": str(data_dir), "KEYS_DIR": str(out / "keys"),
                      "SECURE_COOKIES": False, "DEMO": True})
    cfg = dict(app.config["RULES"])
    con = connect(app.config["DB_PATH"])
    truth = Truth(start, now)

    # 1. older minutes: counts straight from the simulated truth, rolled up day by day, then trimmed to 31 days
    keep_from = (now - timedelta(days=KEEP_MINUTE_DAYS)).strftime(FMT)
    day = start
    while day < signed_from:
        end = min(day + timedelta(days=1), signed_from)
        rows = count_rows(truth, day, end, cfg)
        con.execute("BEGIN")
        con.executemany("INSERT INTO minute_counts (src, network, minute, service, checks, ok, failed, usable, lat_sum, lat_n)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute("COMMIT")
        if end == day + timedelta(days=1):
            history.rollup_day(con, cfg, day.strftime("%Y-%m-%d"), now)
            con.execute("DELETE FROM minute_counts WHERE minute < ?", (keep_from,))
        day += timedelta(days=1)

    # 2. the last 25 hours as signed records, counted by the app's own ingest (which also rolls up those days)
    signed_files(truth, signed_from, now, data_dir, keys)
    res = mirror.ingest(str(data_dir), app.config["DB_PATH"], cfg)
    history.rollup_days(con, cfg, {signed_from.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")}, now)

    # 3. the dashboard's status file, built by the same code as the real one
    from datetime import timezone
    store = open_store(str(data_dir))
    status = build_status(store, str(out / "keys"), cfg, now=now.replace(tzinfo=timezone.utc))
    store.put("status/latest.json", json.dumps(status, separators=(",", ":")).encode())

    # 4. a demo sign-in
    pw = secrets.token_urlsafe(12)
    with app.test_request_context():
        from .auth import hash_password
        from .db import now as now_iso
        con.execute("INSERT INTO users (email, name, company, role, pw_hash, created_at) VALUES (?, ?, ?, 'admin', ?, ?)",
                    ("demo@nimbusindex.com", "Demo viewer", "Nimbus Index (example)", hash_password(pw), now_iso()))
    con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('last_sync', ?)", (now.strftime("%Y-%m-%dT%H:%M:%SZ"),))
    con.execute("VACUUM")
    con.close()
    (out / "demo_credentials.local.txt").write_text(
        "Example-data app (NOT real measurements)\nURL: http://localhost:8081\nemail: demo@nimbusindex.com\n"
        f"password: {pw}\n")
    return {"from": start.date().isoformat(), "to": now.isoformat(), "signed_files": res["files_added"],
            "overall": status["overall"]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nimbus_app.demo", description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "instance" / "demo"))
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args(argv)
    print(build(Path(a.out), a.days))


if __name__ == "__main__":
    main()
