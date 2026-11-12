"""Long periods (months) at a glance, from small daily roll-ups instead of every minute.

  rollup_days(con, cfg, days)   judge each minute of those days with the outage rule (reports.official_states) and keep
                                only what long views need: minutes up/down/undecided per service and day, every stretch
                                that was not up (state_runs), and per-network coverage. Re-running a day replaces it.
  overview(con, cfg, d_from, d_to)
                                uptime per service, a cell per day, months, outages (same rule as probe.detect.events,
                                rebuilt from the stretches), and probe-network coverage.

A minute with no data counts as undecided, exactly as probe.detect.events treats a gap.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from probe.detect import FMT

from .reports import BadRange, _rows, official_states

REGION = "*"
MAX_HISTORY_DAYS = 400


def _now_minute() -> datetime:
    return datetime.utcnow().replace(second=0, microsecond=0)


def rollup_day(con, cfg: dict, day: str, now: Optional[datetime] = None) -> None:
    services = cfg["services"]
    start = datetime.strptime(day, "%Y-%m-%d")
    end = min(start + timedelta(days=1), now or _now_minute())        # only finished minutes
    if end <= start:
        return
    s, e = start.strftime(FMT), (start + timedelta(days=1)).strftime(FMT)
    warm = (start - timedelta(minutes=2 * int(cfg.get("window_minutes", 1)))).strftime(FMT)
    rows = _rows(con, warm, e)
    states = official_states(rows, cfg, s)

    counts = {k: {"up": 0, "down": 0, "unknown": 0} for k in services + [REGION]}
    runs: List[tuple] = []
    open_: Dict[str, list] = {}
    t = start
    while t < end:
        m = t.strftime(FMT)
        sv = states.get(m, {})
        cur = {k: sv.get(k, "unknown") for k in services}
        vals = list(cur.values())
        cur[REGION] = "down" if "down" in vals else ("up" if all(v == "up" for v in vals) else "unknown")
        for k, st in cur.items():
            counts[k][st] += 1
            run = open_.get(k)
            if run and run[0] == st:
                run[2] = m
            else:
                if run and run[0] != "up":
                    runs.append((day, k, run[0], run[1], run[2]))
                open_[k] = [st, m, m]
        t += timedelta(minutes=1)
    for k, run in open_.items():
        if run[0] != "up":
            runs.append((day, k, run[0], run[1], run[2]))

    nets = defaultdict(lambda: [set(), 0, 0, 0, 0])
    for r in rows:
        if r["minute"] < s:
            continue
        n = nets[r["network"]]
        n[0].add(r["minute"])
        if r["service"] in services:
            n[1] += r["checks"]; n[2] += r["ok"]; n[3] += r["lat_sum"]; n[4] += r["lat_n"]

    con.execute("BEGIN")
    for table in ("state_runs", "daily_states", "daily_networks"):
        con.execute(f"DELETE FROM {table} WHERE day = ?", (day,))
    con.executemany("INSERT INTO state_runs (day, service, state, start, end) VALUES (?, ?, ?, ?, ?)", runs)
    con.executemany("INSERT INTO daily_states (day, service, up, down, unknown) VALUES (?, ?, ?, ?, ?)",
                    [(day, k, c["up"], c["down"], c["unknown"]) for k, c in counts.items()])
    con.executemany("INSERT INTO daily_networks (day, network, minutes, checks, ok, lat_sum, lat_n) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(day, net, len(v[0]), v[1], v[2], v[3], v[4]) for net, v in nets.items()])
    con.execute("COMMIT")


def rollup_days(con, cfg: dict, days: Iterable[str], now: Optional[datetime] = None) -> int:
    done = 0
    for d in sorted(set(days)):
        rollup_day(con, cfg, d, now)
        done += 1
    return done


def days_to_refresh(con, changed_days: Iterable[str] = ()) -> List[str]:
    """Days whose data changed, days never rolled up, and always yesterday and today (late files, today still running)."""
    have = {r[0] for r in con.execute("SELECT DISTINCT day FROM daily_states")}
    present = {r[0] for r in con.execute("SELECT DISTINCT day FROM ingested_files")}
    today = datetime.utcnow().date()
    recent = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    return sorted((present - have) | (set(changed_days) & present) | (recent & present))


# ---- reading -----------------------------------------------------------------------------------------------------

def _minutes_between(a: str, b: str) -> int:
    return int((datetime.strptime(b, FMT) - datetime.strptime(a, FMT)).total_seconds() // 60)


def events_from_runs(region_runs: List[tuple], service_down: List[tuple], cfg: dict, start: str, last: str) -> List[dict]:
    """Outage events between minutes `start` and `last` (inclusive), identical to probe.detect.events(states, cfg) over
    the same minutes. region_runs: (state, start, end) sorted, non-up only; service_down: (service, start, end)."""
    rec = cfg["recovery_minutes"]
    out, cur, clear, prev = [], None, 0, None

    def close(e):
        e["duration_min"] = _minutes_between(e["start"], e["end"]) + 1
        e["services"] = sorted({svc for svc, a, b in service_down if a <= e["end"] and b >= e["start"]})
        e["meets_waiting_period"] = {str(w): e["duration_min"] >= w for w in cfg["waiting_periods_min"]}
        out.append(e)

    for state, a, b in region_runs:
        a, b = max(a, start), min(b, last)
        if a > b:
            continue
        gap = _minutes_between(prev, a) - 1 if prev else 0             # 'up' minutes since the last stretch
        if cur is not None and gap > 0:
            clear += gap
            if clear >= rec:
                close(cur); cur, clear = None, 0
        n = _minutes_between(a, b) + 1
        if state == "down":
            if cur is None:
                cur = {"start": a, "end": b, "down_minutes": 0, "unknown_minutes": 0}
            cur["end"], clear = b, 0
            cur["down_minutes"] += n
        elif cur is not None:
            cur["unknown_minutes"] += n
        prev = b
    if cur is not None:
        tail = _minutes_between(prev, last) if prev else 0
        if clear + tail >= rec:
            close(cur)
        else:
            cur["ongoing"] = True
            close(cur)
    return out


def parse_period(frm: Optional[str], to: Optional[str], days: int = 180):
    try:
        d_to = date.fromisoformat(to) if to else datetime.utcnow().date()
        d_from = date.fromisoformat(frm) if frm else d_to - timedelta(days=days - 1)
    except ValueError:
        raise BadRange("Dates must look like 2026-11-11.")
    if d_from > d_to:
        raise BadRange("The start date is after the end date.")
    if (d_to - d_from).days + 1 > MAX_HISTORY_DAYS:
        raise BadRange(f"Choose at most {MAX_HISTORY_DAYS} days at a time.")
    return d_from, d_to


def _pct(a, b, nd=3):
    return round(100 * a / b, nd) if b else None


def overview(con, cfg: dict, d_from: date, d_to: date) -> dict:
    services = cfg["services"]
    reference = set(cfg.get("reference_networks", []))
    f, t = d_from.isoformat(), d_to.isoformat()
    start = f"{f}T00:00Z"
    until = min(datetime.combine(d_to + timedelta(days=1), datetime.min.time()), _now_minute())
    last = (until - timedelta(minutes=1)).strftime(FMT)
    minutes_in_range = max(0, int((until - datetime.strptime(start, FMT)).total_seconds() // 60))

    daily = defaultdict(dict)                                   # day -> service -> {up, down, unknown}
    for r in con.execute("SELECT * FROM daily_states WHERE day BETWEEN ? AND ?", (f, t)):
        daily[r["day"]][r["service"]] = {"up": r["up"], "down": r["down"], "unknown": r["unknown"]}

    days, d = [], d_from
    while d <= d_to:
        days.append(d.isoformat())
        d += timedelta(days=1)

    def cell(day, k):
        c = daily.get(day, {}).get(k)
        if not c:
            return {"day": day, "cls": "none", "down": 0, "judged": 0, "unknown": 0}
        judged = c["up"] + c["down"]
        cls = "unk" if judged == 0 else ("up" if c["down"] == 0 else ("major" if c["down"] >= 60 else "minor"))
        return {"day": day, "cls": cls, "down": c["down"], "judged": judged, "unknown": c["unknown"],
                "uptime": _pct(c["up"], judged)}

    def total(k, ds):
        tot = {"up": 0, "down": 0, "unknown": 0}
        for day in ds:
            for x in tot:
                tot[x] += daily.get(day, {}).get(k, {}).get(x, 0)
        return tot

    q = "SELECT state, start, end FROM state_runs WHERE service = ? AND end >= ? AND start <= ? ORDER BY start"
    region_runs = [tuple(r) for r in con.execute(q, (REGION, start, last))]
    service_down = [tuple(r) for r in con.execute(
        "SELECT service, start, end FROM state_runs WHERE service != ? AND state = 'down' AND end >= ? AND start <= ?",
        (REGION, start, last))]
    outages = events_from_runs(region_runs, service_down, cfg, start, last) if region_runs else []

    summary = {}
    for k in services + [REGION]:
        tot = total(k, days)
        judged = tot["up"] + tot["down"]
        summary[k] = {"official_uptime_pct": _pct(tot["up"], judged), "down_minutes": tot["down"],
                      "judged_minutes": judged, "undecided_minutes": tot["unknown"],
                      "days": [cell(day, k) for day in days]}

    months = []
    for ym in sorted({day[:7] for day in days}):
        md = [day for day in days if day.startswith(ym)]
        row = {"month": ym, "services": {}, "outages": sum(1 for o in outages if o["start"].startswith(ym))}
        for k in services + [REGION]:
            tot = total(k, md)
            row["services"][k] = {"uptime": _pct(tot["up"], tot["up"] + tot["down"]), "down": tot["down"],
                                  "judged": tot["up"] + tot["down"]}
        months.append(row)

    nets = defaultdict(lambda: [0, 0, 0, 0, 0])
    for r in con.execute("SELECT * FROM daily_networks WHERE day BETWEEN ? AND ?", (f, t)):
        n = nets[r["network"]]
        n[0] += r["minutes"]; n[1] += r["checks"]; n[2] += r["ok"]; n[3] += r["lat_sum"]; n[4] += r["lat_n"]
    networks = {net: {"operator": cfg["operators"].get(net, net), "counted": net not in reference,
                      "coverage_pct": _pct(v[0], minutes_in_range, 1), "checks": v[1], "ok_pct": _pct(v[2], v[1]),
                      "avg_latency_ms": round(v[3] / v[4]) if v[4] else None}
                for net, v in sorted(nets.items())}

    waits = {str(w): sum(1 for o in outages if o["meets_waiting_period"][str(w)]) for w in cfg["waiting_periods_min"]}
    return {"from": f, "to": t, "rules": cfg["version"], "services": services, "days": days, "summary": summary,
            "months": months, "outages": outages, "networks": networks, "minutes_in_range": minutes_in_range,
            "waiting_periods_met": waits,
            "longest_outage_min": max((o["duration_min"] for o in outages), default=0),
            "first_judged_day": next((c["day"] for c in summary[REGION]["days"] if c["judged"]), None)}
