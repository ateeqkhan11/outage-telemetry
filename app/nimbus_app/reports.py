"""Reports and API answers built from minute_counts, using the same outage rule as the probes (probe.detect)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from probe.detect import FMT, events, states_from_counts

MAX_REPORT_DAYS = 31


class BadRange(ValueError):
    pass


def definitions(cfg: dict) -> Dict[str, dict]:
    """The outage definitions in the trigger rules ('degraded', 'hard_down'); older rule files have just one."""
    return cfg.get("definitions") or {"degraded": {"label": "Degraded", "window_minutes": cfg.get("window_minutes", 1),
                                                   "window_fail_share": cfg.get("window_fail_share", 1.0)}}


def default_definition(cfg: dict) -> str:
    return cfg.get("default_definition") or next(iter(definitions(cfg)))


def definition_cfg(cfg: dict, name: Optional[str]) -> dict:
    """The rules with one definition's window and fail share applied (unknown names fall back to the default)."""
    defs = definitions(cfg)
    d = defs.get(name or "") or defs[default_definition(cfg)]
    return dict(cfg, window_minutes=d["window_minutes"], window_fail_share=d["window_fail_share"])


def pick_definition(cfg: dict, name: Optional[str]) -> str:
    return name if name in definitions(cfg) else default_definition(cfg)


def parse_days(frm: Optional[str], to: Optional[str], default_days: int = 7, max_days: int = MAX_REPORT_DAYS):
    """Inclusive UTC date range from YYYY-MM-DD strings (to defaults to today, from to `default_days` back)."""
    try:
        d_to = date.fromisoformat(to) if to else datetime.utcnow().date()
        d_from = date.fromisoformat(frm) if frm else d_to - timedelta(days=default_days - 1)
    except ValueError:
        raise BadRange("Dates must look like 2026-11-11.")
    if d_from > d_to:
        raise BadRange("The start date is after the end date.")
    if (d_to - d_from).days + 1 > max_days:
        raise BadRange(f"Choose at most {max_days} days at a time.")
    return d_from, d_to


def _rows(db, start: str, end: str):
    """minute_counts rows with start <= minute < end (both 'YYYY-MM-DDTHH:MMZ')."""
    return db.execute("SELECT network, minute, service, checks, ok, failed, usable, lat_sum, lat_n FROM minute_counts"
                      " WHERE minute >= ? AND minute < ?", (start, end)).fetchall()


def official_states(rows, cfg, keep_from: str) -> Dict[str, Dict[str, str]]:
    reference = set(cfg.get("reference_networks", []))
    counts: Dict[str, Dict[str, Dict[str, List[int]]]] = defaultdict(lambda: defaultdict(dict))
    minutes = set()
    for r in rows:
        if r["network"] in reference:
            continue
        minutes.add(r["minute"])
        if r["service"] in cfg["services"] and r["usable"]:
            counts[r["minute"]][r["network"]][r["service"]] = [r["failed"], r["usable"]]
    st = states_from_counts(counts, sorted(minutes), cfg)
    return {m: v for m, v in st.items() if m >= keep_from}


def report(db, cfg: dict, d_from: date, d_to: date, services: Optional[List[str]] = None,
           networks: Optional[List[str]] = None, definition: Optional[str] = None) -> dict:
    definition = pick_definition(cfg, definition)
    cfg = definition_cfg(cfg, definition)
    services = [s for s in (services or cfg["services"]) if s in cfg["services"]] or list(cfg["services"])
    start = d_from.strftime("%Y-%m-%dT00:00Z")
    end = (d_to + timedelta(days=1)).strftime("%Y-%m-%dT00:00Z")
    warm = (datetime.strptime(start, FMT) - timedelta(minutes=2 * int(cfg.get("window_minutes", 1)))).strftime(FMT)
    rows = _rows(db, warm, end)
    states = official_states(rows, cfg, start)
    reference = set(cfg.get("reference_networks", []))
    all_nets = sorted({r["network"] for r in rows})
    nets = [n for n in (networks or all_nets) if n in all_nets] or all_nets
    until = min(datetime.strptime(end, FMT), datetime.utcnow().replace(second=0, microsecond=0))   # today isn't over
    minutes_in_range = max(0, int((until - datetime.strptime(start, FMT)).total_seconds() // 60))

    # official minutes per day and service
    per_day = defaultdict(lambda: defaultdict(lambda: {"up": 0, "down": 0, "unknown": 0}))
    for m, sv in states.items():
        for s in services:
            per_day[m[:10]][s][sv.get(s, "unknown")] += 1

    # raw numbers per day, service and network
    raw = defaultdict(lambda: [0, 0, 0, 0])                    # (day, service, network) -> checks, ok, lat_sum, lat_n
    covered = defaultdict(set)                                 # network -> minutes with data
    for r in rows:
        if r["minute"] < start or r["network"] not in nets:
            continue
        covered[r["network"]].add(r["minute"])
        if r["service"] not in services:
            continue
        c = raw[(r["minute"][:10], r["service"], r["network"])]
        c[0] += r["checks"]; c[1] += r["ok"]; c[2] += r["lat_sum"]; c[3] += r["lat_n"]

    def pct(a, b, nd=3):
        return round(100 * a / b, nd) if b else None

    summary = {}
    for s in services:
        tot = {"up": 0, "down": 0, "unknown": 0}
        for d in per_day.values():
            for k in tot:
                tot[k] += d[s][k]
        by_net = {}
        for n in nets:
            ch = sum(v[0] for (dd, ss, nn), v in raw.items() if ss == s and nn == n)
            ok = sum(v[1] for (dd, ss, nn), v in raw.items() if ss == s and nn == n)
            ls = sum(v[2] for (dd, ss, nn), v in raw.items() if ss == s and nn == n)
            ln = sum(v[3] for (dd, ss, nn), v in raw.items() if ss == s and nn == n)
            by_net[n] = {"checks": ch, "failed": ch - ok, "ok_pct": pct(ok, ch), "avg_latency_ms": round(ls / ln) if ln else None}
        summary[s] = {"official_uptime_pct": pct(tot["up"], tot["up"] + tot["down"]), "up_minutes": tot["up"],
                      "down_minutes": tot["down"], "undecided_minutes": tot["unknown"],
                      "judged_minutes": tot["up"] + tot["down"], "networks": by_net}

    days = []
    d = d_from
    while d <= d_to:
        k = d.isoformat()
        for s in services:
            o = per_day[k][s]
            for n in nets:
                c = raw.get((k, s, n), [0, 0, 0, 0])
                days.append({"date": k, "service": s, "official_uptime_pct": pct(o["up"], o["up"] + o["down"]),
                             "down_minutes": o["down"], "undecided_minutes": o["unknown"], "network": n,
                             "counted": n not in reference, "checks": c[0], "failed": c[0] - c[1],
                             "ok_pct": pct(c[1], c[0]), "avg_latency_ms": round(c[2] / c[3]) if c[3] else None})
        d += timedelta(days=1)

    sub = {m: {s: v.get(s, "unknown") for s in services} for m, v in states.items()}
    cfg_s = dict(cfg, services=services)
    outages = events(sub, cfg_s) if sub else []
    return {
        "from": d_from.isoformat(), "to": d_to.isoformat(), "rules": cfg["version"], "services": services,
        "networks": {n: {"counted": n not in reference, "operator": cfg["operators"].get(n, n),
                         "coverage_pct": pct(len(covered[n]), minutes_in_range, 1)} for n in nets},
        "summary": summary, "outages": outages, "daily": days,
        "minutes_in_range": minutes_in_range, "minutes_judged": len(states), "definition": definition,
    }


def minutes(db, cfg: dict, start: datetime, end: datetime, definition: Optional[str] = None) -> List[dict]:
    """Official state of every service, minute by minute, for start <= minute < end (at most 24 hours)."""
    cfg = definition_cfg(cfg, definition)
    s, e = start.strftime(FMT), end.strftime(FMT)
    warm = (start - timedelta(minutes=2 * int(cfg.get("window_minutes", 1)))).strftime(FMT)
    st = official_states(_rows(db, warm, e), cfg, s)
    return [{"minute": m, "services": st[m]} for m in sorted(st) if m < e]


CSV_FIELDS = ["date", "service", "official_uptime_pct", "down_minutes", "undecided_minutes", "network", "counted",
              "checks", "failed", "ok_pct", "avg_latency_ms"]
