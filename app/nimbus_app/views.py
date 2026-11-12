"""Pages for pilot users: landing, request access, sign in, invites, dashboard, reports, API access, account."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from flask import (Blueprint, Response, abort, current_app, g, make_response, redirect, render_template, request,
                   send_from_directory, url_for)

from . import auth, data, reports
from .db import get_db, log, now

bp = Blueprint("web", __name__)
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-zA-Z]{2,24}$")
SHARED = {"dashboard.js", "dashboard.css"}


def safe_next(target: str) -> str:
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("web.dashboard")


@bp.get("/healthz")
def healthz():
    return {"ok": True, "last_sync": data.last_sync(get_db())}


@bp.get("/shared/<name>")
def shared(name):
    """dashboard.js and dashboard.css, served from docs/ so the app and the public page use the same code."""
    if name not in SHARED:
        abort(404)
    return send_from_directory(Path(current_app.config["REPO_DIR"]) / "docs", name, max_age=300)


@bp.get("/")
def home():
    if g.user:
        return redirect(url_for("web.dashboard"))
    return render_template("home.html", public=current_app.config["PUBLIC_DASHBOARD"])


@bp.route("/request-access", methods=["GET", "POST"])
def request_access():
    form, err = {}, None
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "email", "company", "title", "use_case")}
        if request.form.get("website"):                     # honeypot field, invisible to people
            return render_template("request_done.html")
        if not form["name"] or not form["company"]:
            err = "Please add your name and company."
        elif not EMAIL_RE.match(form["email"]):
            err = "Please check the email address."
        elif not auth.ip_allowed("request_access", limit=5, window=3600):
            err = "Too many requests from this network. Try again in an hour."
        else:
            get_db().execute("INSERT INTO access_requests (name, email, company, title, use_case, created_at, ip)"
                             " VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (form["name"][:120], form["email"][:200], form["company"][:120], form["title"][:120],
                              form["use_case"][:2000], now(), auth.client_ip()))
            return render_template("request_done.html")
    return render_template("request_access.html", form=form, err=err)


@bp.route("/sign-in", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("web.dashboard"))
    err, email = None, ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not auth.ip_allowed():
            err = "Too many attempts from this network. Try again in 15 minutes."
        else:
            user, err = auth.check_login(email, request.form.get("password", ""))
            if user:
                return auth.start_session(redirect(safe_next(request.form.get("next", ""))), user["id"])
    return render_template("login.html", err=err, email=email, next=request.args.get("next", request.form.get("next", "")))


@bp.post("/sign-out")
def logout():
    return auth.end_session(redirect(url_for("web.home")))


@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token):
    inv = auth.find_invite(token)
    if inv is None:
        return render_template("error.html", code=410, message="This invite link has expired or was already used. "
                               "Ask Nimbus Index for a new one."), 410
    err = None
    db = get_db()
    exists = db.execute("SELECT 1 FROM users WHERE email = ?", (inv["email"],)).fetchone()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        err = (("Please add your name." if not name else None) or auth.password_problem(pw)
               or ("The two passwords don't match." if pw != pw2 else None)
               or ("An account with this email already exists. Sign in instead." if exists else None))
        if not err:
            db.execute("BEGIN")
            cur = db.execute("INSERT INTO users (email, name, company, role, pw_hash, created_at, last_login_at)"
                             " VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (inv["email"], name[:120], (request.form.get("company") or inv["company"]).strip()[:120],
                              inv["role"], auth.hash_password(pw), now(), now()))
            db.execute("UPDATE invites SET used_at = ? WHERE token_hash = ?", (now(), inv["token_hash"]))
            db.execute("COMMIT")
            log("joined", inv["company"], user_id=cur.lastrowid)
            return auth.start_session(redirect(url_for("web.dashboard", welcome=1)), cur.lastrowid)
    return render_template("invite.html", inv=inv, err=err, min_pw=auth.MIN_PASSWORD)


@bp.get("/dashboard")
@auth.login_required
def dashboard():
    log("dashboard", user_id=g.user["id"])
    return render_template("dashboard.html", welcome=request.args.get("welcome"))


@bp.get("/dashboard/status.json")
@auth.login_required
def status_json():
    s = data.status()
    if s is None:
        return {"error": "No data yet. The first copy of the data is still being made."}, 503
    return s


def _report_args():
    cfg = current_app.config["RULES"]
    d_from, d_to = reports.parse_days(request.args.get("from"), request.args.get("to"))
    services = request.args.getlist("service") or None
    nets = request.args.getlist("network") or None
    return cfg, d_from, d_to, services, nets


@bp.get("/reports")
@auth.login_required
def reports_page():
    cfg = current_app.config["RULES"]
    err, rep = None, None
    try:
        cfg, d_from, d_to, services, nets = _report_args()
        rep = reports.report(get_db(), cfg, d_from, d_to, services, nets)
        if request.args:
            log("report", f"{d_from}..{d_to}", user_id=g.user["id"])
    except reports.BadRange as e:
        err = str(e)
    return render_template("reports.html", rep=rep, err=err, cfg=cfg, all_networks=data.networks(),
                           args=request.args, max_days=reports.MAX_REPORT_DAYS)


@bp.get("/reports.csv")
@auth.login_required
def reports_csv():
    try:
        cfg, d_from, d_to, services, nets = _report_args()
    except reports.BadRange as e:
        abort(400, str(e))
    rep = reports.report(get_db(), cfg, d_from, d_to, services, nets)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=reports.CSV_FIELDS)
    w.writeheader()
    for row in rep["daily"]:
        w.writerow({k: ("" if row[k] is None else row[k]) for k in reports.CSV_FIELDS})
    log("download", f"csv {d_from}..{d_to}", user_id=g.user["id"])
    name = f"nimbus-index-us-east-1-{d_from}-to-{d_to}.csv"
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.get("/records/<network>/<day>.jsonl")
@auth.login_required
def records(network, day):
    body = data.records_for_day(network, day)
    if body is None:
        abort(404, "No signed records for that network and day.")
    log("download", f"records {network} {day}", user_id=g.user["id"])
    return Response(body, mimetype="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="nimbus-{network}-{day}.jsonl"'})


@bp.route("/api-access", methods=["GET", "POST"])
@auth.login_required
def api_access():
    db = get_db()
    new_key = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            live = db.execute("SELECT COUNT(*) FROM api_keys WHERE user_id = ? AND revoked_at IS NULL", (g.user["id"],)).fetchone()[0]
            if live >= 5:
                abort(400, "You already have 5 active keys. Revoke one first.")
            new_key = auth.create_api_key(g.user["id"], request.form.get("name", ""))
            log("api_key", "created", user_id=g.user["id"])
        elif action == "revoke":
            db.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                       (now(), request.form.get("key_id", type=int), g.user["id"]))
            log("api_key", "revoked", user_id=g.user["id"])
            return redirect(url_for("web.api_access"))
    keys = db.execute("SELECT * FROM api_keys WHERE user_id = ? ORDER BY revoked_at IS NOT NULL, id DESC", (g.user["id"],)).fetchall()
    base = request.host_url.rstrip("/")
    return render_template("api_access.html", keys=keys, new_key=new_key, base=base)


@bp.route("/account", methods=["GET", "POST"])
@auth.login_required
def account():
    msg = err = None
    if request.method == "POST":
        from werkzeug.security import check_password_hash
        cur, pw, pw2 = request.form.get("current", ""), request.form.get("password", ""), request.form.get("password2", "")
        if not check_password_hash(g.user["pw_hash"], cur):
            err = "Your current password isn't right."
        else:
            err = auth.password_problem(pw) or ("The two new passwords don't match." if pw != pw2 else None)
        if not err:
            db = get_db()
            db.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (auth.hash_password(pw), g.user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id = ? AND id_hash != ?", (g.user["id"], g.session_hash))
            msg = "Password changed. Any other signed-in browsers were signed out."
    return render_template("account.html", msg=msg, err=err, min_pw=auth.MIN_PASSWORD)


@bp.app_template_filter("when")
def when(iso):
    return (iso or "").replace("T", " ").replace("Z", " UTC")[:20] if iso else "never"


@bp.app_template_filter("pct")
def pct(v, nd=3):
    return "—" if v is None else f"{v:.{nd}f}%"
