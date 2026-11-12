"""The data feed for pilot firms: /api/v1, authenticated with personal API keys.

  GET /api/v1/status                          latest official state, per service and per probe network
  GET /api/v1/minutes?from=...&to=...         official state of each service, minute by minute (at most 24 hours)
  GET /api/v1/uptime?from=YYYY-MM-DD&to=...   official uptime, outages and per-network numbers (at most 31 days)
  GET /api/v1/outages?from=...&to=...         outage events under the trigger rules (at most 31 days)
  GET /api/v1/records/<network>/<day>         the day's signed records for one network (JSON lines)
  GET /api/v1/keys                            public keys to verify the signatures
"""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, Response, current_app, jsonify, request

from probe.detect import FMT

from . import data, reports
from .auth import api_key_required
from .db import get_db

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _rules():
    cfg = current_app.config["RULES"]
    return {"version": cfg["version"], "operators_required": cfg["operators_required"],
            "window_minutes": cfg.get("window_minutes", 1), "window_fail_share": cfg.get("window_fail_share", 1.0),
            "fail_kinds": cfg["fail_kinds"], "reference_networks": cfg.get("reference_networks", [])}


@bp.get("/status")
@api_key_required
def status():
    s = data.status()
    if s is None:
        return jsonify(error="No data yet."), 503
    return jsonify({
        "generated_at": s["generated_at"], "region": s["region"], "last_minute": s["last_minute"],
        "can_decide": s["can_decide"], "overall": s["overall"], "independent_operators": s["independent_operators"],
        "rules": _rules(),
        "services": {k: {"state": v["state"], "uptime_pct_24h": v["uptime_pct"], "checks_24h": v["checks"],
                         "failed_24h": v["failed"], "latency_ms_p50_last_hour": v["latency_ms_p50_last_hour"]}
                     for k, v in s["services"].items()},
        "networks": {k: {f: v[f] for f in ("operator", "counted", "last_minute", "minutes_covered", "longest_gap_min",
                                            "records", "chain_valid")} for k, v in s["networks"].items()},
        "outages_24h": s["outages"],
    })


def _minute(v, name):
    try:
        if len(v) == 10:
            return datetime.strptime(v, "%Y-%m-%d")
        return datetime.strptime(v.rstrip("Z")[:16], "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError):
        raise reports.BadRange(f"'{name}' must look like 2026-11-11T14:05Z or 2026-11-11.")


@bp.get("/minutes")
@api_key_required
def minutes():
    try:
        end = _minute(request.args["to"], "to") if request.args.get("to") else datetime.utcnow().replace(second=0, microsecond=0)
        start = _minute(request.args["from"], "from") if request.args.get("from") else end - timedelta(hours=1)
        if start >= end or end - start > timedelta(hours=24):
            raise reports.BadRange("Choose a range of up to 24 hours, with 'from' before 'to'.")
    except reports.BadRange as e:
        return jsonify(error=str(e)), 400
    rows = reports.minutes(get_db(), current_app.config["RULES"], start, end)
    return jsonify({"from": start.strftime(FMT), "to": end.strftime(FMT), "rules": _rules(), "minutes": rows})


@bp.get("/uptime")
@api_key_required
def uptime():
    try:
        d_from, d_to = reports.parse_days(request.args.get("from"), request.args.get("to"))
    except reports.BadRange as e:
        return jsonify(error=str(e)), 400
    rep = reports.report(get_db(), current_app.config["RULES"], d_from, d_to,
                         request.args.getlist("service") or None, request.args.getlist("network") or None)
    rep["rules"] = _rules()
    if request.args.get("daily") != "1":
        rep.pop("daily")
    return jsonify(rep)


@bp.get("/outages")
@api_key_required
def outages():
    try:
        d_from, d_to = reports.parse_days(request.args.get("from"), request.args.get("to"))
    except reports.BadRange as e:
        return jsonify(error=str(e)), 400
    rep = reports.report(get_db(), current_app.config["RULES"], d_from, d_to)
    return jsonify({"from": rep["from"], "to": rep["to"], "rules": _rules(), "outages": rep["outages"]})


@bp.get("/records/<network>/<day>")
@api_key_required
def records(network, day):
    body = data.records_for_day(network, day)
    if body is None:
        return jsonify(error="No signed records for that network and day."), 404
    return Response(body, mimetype="application/x-ndjson")


@bp.get("/keys")
@api_key_required
def keys():
    return jsonify({"algorithm": "Ed25519", "encoding": "base64, raw 32-byte public key",
                    "signed_message": "the record's hash field, as bytes (SHA-256 of its canonical JSON)",
                    "keys": data.public_keys()})
