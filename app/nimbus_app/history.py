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

from .reports import BadRange, _rows, definition_cfg, definitions, official_states, pick_definition

REGION = "*"
MAX_HISTORY_DAYS = 400


def _now_minute() -> datetime:
    return datetime.utcnow().replace(second=0, microsecond=0)


def _judge_day(states: dict, services: List[str], day: str, start: datetime, end: datetime, definition: str):
    """Minute states for one definition -> (stretches that were not up, counts per service and region)."""
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
                    runs.append((day, definition, k, run[0], run[1], run[2]))
                open_[k] = [st, m, m]
        t += timedelta(minutes=1)
    for k, run in open_.items():
        if run[0] != "up":
            runs.append((day, definition, k, run[0], run[1], run[2]))
    return runs, counts


def rollup_day(con, cfg: dict, day: str, now: Optional[datetime] = None) -> None:
    """Judge every minute of one day under each outage definition and store the roll-ups (replacing that day's)."""
    services = cfg["services"]
    start = datetime.strptime(day, "%Y-%m-%d")
    end = min(start + timedelta(days=1), now or _now_minute())        # only finished minutes
    if end <= start:
        return
    s, e = start.strftime(FMT), (start + timedelta(days=1)).strftime(FMT)
    longest = max(int(d["window_minutes"]) for d in definitions(cfg).values())
    rows = _rows(con, (start - timedelta(minutes=2 * longest)).strftime(FMT), e)

    all_runs, all_counts = [], []
    for name in definitions(cfg):
        states = official_states(rows, definition_cfg(cfg, name), s)
        runs, counts = _judge_day(states, services, day, start, end, name)
        all_runs += runs
        all_counts += [(day, name, k, c["up"], c["down"], c["unknown"]) for k, c in counts.items()]

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
    con.executemany("INSERT INTO state_runs (day, definition, service, state, start, end) VALUES (?, ?, ?, ?, ?, ?)", all_runs)
    con.executemany("INSERT INTO daily_states (day, definition, service, up, down, unknown) VALUES (?, ?, ?, ?, ?, ?)", all_counts)
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


def _to_min(m: str) -> int:
    return int(datetime.strptime(m, FMT).timestamp() // 60)


def _from_min(n: int) -> str:
    return datetime.utcfromtimestamp(n * 60).strftime(FMT)


def _union(intervals: List[tuple]) -> List[list]:
    out: List[list] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _subtract(base: List[list], cut: List[list]) -> List[tuple]:
    out = []
    for a, b in base:
        pieces = [(a, b)]
        for c, d in cut:
            nxt = []
            for x, y in pieces:
                if d < x or c > y:
                    nxt.append((x, y)); continue
                if x < c: nxt.append((x, c - 1))
                if d < y: nxt.append((d + 1, y))
            pieces = nxt
        out += pieces
    return out


def _runs(con, definition: str, services: Optional[List[str]], start: str, last: str):
    """(region-style runs [(state, start, end)], service down runs [(service, start, end)]) for a set of services.

    services=None means all of them (the stored region row). For a subset, a minute is down when any of those services
    is down, otherwise undecided when any is undecided, which is how the region row is built for all services."""
    q = ("SELECT service, state, start, end FROM state_runs WHERE definition = ? AND end >= ? AND start <= ?"
         " ORDER BY start")
    rows = [tuple(r) for r in con.execute(q, (definition, start, last))]
    service_down = [(sv, a, b) for sv, st, a, b in rows if sv != REGION and st == "down"]
    if services is None:
        return [(st, a, b) for sv, st, a, b in rows if sv == REGION], service_down
    picked = [r for r in rows if r[0] in services]
    down = _union([(_to_min(a), _to_min(b)) for sv, st, a, b in picked if st == "down"])
    unk = _union([(_to_min(a), _to_min(b)) for sv, st, a, b in picked if st == "unknown"])
    runs = [("down", a, b) for a, b in down] + [("unknown", a, b) for a, b in _subtract(unk, down)]
    runs.sort(key=lambda r: r[1])
    return ([(st, _from_min(a), _from_min(b)) for st, a, b in runs],
            [r for r in service_down if r[0] in services])


# ---- policy replay: what a parametric policy written on these terms would have paid -------------------------------

TERM_DEFAULTS = {"waiting_min": 120, "hourly": 25000, "merge_gap_min": 30, "rounding_min": 5,
                 "event_limit": 1000000, "aggregate_limit": 3000000}


def replay(con, cfg: dict, d_from: date, d_to: date, terms: dict) -> dict:
    """Apply policy terms to the outages a definition called in a period.

    terms: definition, services (list), waiting_min, hourly (dollars per hour), merge_gap_min (outages starting within
    this many minutes of the last one's end are one event, gap not counted, one waiting period), rounding_min (each
    outage's length rounded up to this step), event_limit and aggregate_limit (dollars).
    Payout per event = hourly x (length - waiting period), capped by the event limit, then by what is left of the
    aggregate. Money is whole dollars; time is whole minutes.
    """
    definition = pick_definition(cfg, terms.get("definition"))
    services = [x for x in (terms.get("services") or cfg["services"]) if x in cfg["services"]] or list(cfg["services"])
    t = dict(TERM_DEFAULTS, **{k: int(v) for k, v in terms.items() if k in TERM_DEFAULTS and v is not None})
    start = f"{d_from.isoformat()}T00:00Z"
    until = min(datetime.combine(d_to + timedelta(days=1), datetime.min.time()), _now_minute())
    last = (until - timedelta(minutes=1)).strftime(FMT)
    region_runs, service_down = _runs(con, definition, None if len(services) == len(cfg["services"]) else services, start, last)
    outages = events_from_runs(region_runs, service_down, cfg, start, last) if region_runs else []

    step = max(1, t["rounding_min"])
    rounded = lambda m: -(-m // step) * step
    events: List[dict] = []
    for o in outages:
        prev = events[-1] if events else None
        if prev and _minutes_between(prev["end"], o["start"]) - 1 <= t["merge_gap_min"] and not prev.get("ongoing"):
            prev["parts"].append(o)
            prev["end"] = o["end"]
            prev["minutes"] += rounded(o["duration_min"])
            prev["services"] = sorted(set(prev["services"]) | set(o["services"]))
            prev["ongoing"] = bool(o.get("ongoing"))
        else:
            events.append({"start": o["start"], "end": o["end"], "parts": [o], "minutes": rounded(o["duration_min"]),
                           "services": list(o["services"]), "ongoing": bool(o.get("ongoing"))})
    left = t["aggregate_limit"]
    for e in events:
        e["indemnity_min"] = max(0, e["minutes"] - t["waiting_min"])
        raw = t["hourly"] * e["indemnity_min"] // 60
        e["payout"] = min(raw, t["event_limit"], left)
        e["capped"] = e["payout"] < raw
        left -= e["payout"]
        e["id"] = f"{definition}-{e['start']}"
    return {"from": d_from.isoformat(), "to": d_to.isoformat(), "definition": definition, "services": services,
            "terms": t, "events": events, "total": sum(e["payout"] for e in events),
            "paying_events": sum(1 for e in events if e["payout"] > 0), "rules": cfg["version"]}


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


def overview(con, cfg: dict, d_from: date, d_to: date, definition: Optional[str] = None) -> dict:
    definition = pick_definition(cfg, definition)
    services = cfg["services"]
    reference = set(cfg.get("reference_networks", []))
    f, t = d_from.isoformat(), d_to.isoformat()
    start = f"{f}T00:00Z"
    until = min(datetime.combine(d_to + timedelta(days=1), datetime.min.time()), _now_minute())
    last = (until - timedelta(minutes=1)).strftime(FMT)
    minutes_in_range = max(0, int((until - datetime.strptime(start, FMT)).total_seconds() // 60))

    daily = defaultdict(dict)                                   # day -> service -> {up, down, unknown}
    for r in con.execute("SELECT * FROM daily_states WHERE definition = ? AND day BETWEEN ? AND ?", (definition, f, t)):
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

    region_runs, service_down = _runs(con, definition, None, start, last)
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
    return {"from": f, "to": t, "rules": cfg["version"], "definition": definition, "services": services, "days": days, "summary": summary,
            "months": months, "outages": outages, "networks": networks, "minutes_in_range": minutes_in_range,
            "waiting_periods_met": waits,
            "longest_outage_min": max((o["duration_min"] for o in outages), default=0),
            "first_judged_day": next((c["day"] for c in summary[REGION]["days"] if c["judged"]), None)}
