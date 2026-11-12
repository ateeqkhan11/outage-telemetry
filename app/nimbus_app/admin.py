"""Admin: access requests, invites, people, and who is using what (the interest tracking Mike asked for)."""
from __future__ import annotations

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for

from . import auth
from .db import get_db, log, now

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _invite_url(tok: str) -> str:
    return request.host_url.rstrip("/") + url_for("web.accept_invite", token=tok)


@bp.get("/")
@auth.admin_required
def index():
    db = get_db()
    requests_ = db.execute("SELECT * FROM access_requests ORDER BY status = 'new' DESC, id DESC LIMIT 200").fetchall()
    people = db.execute("""
        SELECT u.*,
          (SELECT COUNT(*) FROM activity a WHERE a.user_id = u.id AND a.kind = 'sign_in' AND a.at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 days')) AS sign_ins_30d,
          (SELECT COUNT(*) FROM activity a WHERE a.user_id = u.id AND a.kind IN ('report', 'download') AND a.at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 days')) AS reports_30d,
          (SELECT COUNT(*) FROM activity a WHERE a.user_id = u.id AND a.kind = 'api' AND a.at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-7 days')) AS api_7d,
          (SELECT MAX(at) FROM activity a WHERE a.user_id = u.id) AS last_active,
          (SELECT COUNT(*) FROM api_keys k WHERE k.user_id = u.id AND k.revoked_at IS NULL) AS key_count
        FROM users u ORDER BY last_active IS NULL, last_active DESC""").fetchall()
    invites = db.execute("SELECT i.*, u.name AS by_name FROM invites i LEFT JOIN users u ON u.id = i.created_by"
                         " WHERE i.used_at IS NULL AND i.expires_at > ? ORDER BY i.created_at DESC", (now(),)).fetchall()
    recent = db.execute("SELECT a.*, u.name, u.company FROM activity a LEFT JOIN users u ON u.id = a.user_id"
                        " WHERE a.kind != 'api' ORDER BY a.id DESC LIMIT 60").fetchall()
    return render_template("admin.html", requests=requests_, people=people, invites=invites, recent=recent,
                           new_invite=session.pop("new_invite", None))


@bp.post("/invite")
@auth.admin_required
def invite():
    db = get_db()
    req_id = request.form.get("request_id", type=int)
    if req_id:
        r = db.execute("SELECT * FROM access_requests WHERE id = ?", (req_id,)).fetchone()
        if r is None:
            abort(404)
        email, name, company = r["email"], r["name"], r["company"]
    else:
        email = request.form.get("email", "").strip()
        name, company = request.form.get("name", "").strip(), request.form.get("company", "").strip()
        if "@" not in email:
            abort(400, "Add an email address for the invite.")
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        abort(400, f"{email} already has an account.")
    role = "admin" if request.form.get("role") == "admin" else "member"
    tok = auth.create_invite(email, name, company, role, created_by=g.user["id"], request_id=req_id)
    if req_id:
        db.execute("UPDATE access_requests SET status = 'invited', handled_by = ?, handled_at = ? WHERE id = ?",
                   (g.user["id"], now(), req_id))
    log("admin", f"invited {email}", user_id=g.user["id"])
    session["new_invite"] = {"email": email, "link": _invite_url(tok)}   # shown once, never put in a URL
    return redirect(url_for("admin.index"))


@bp.post("/request/<int:req_id>/decline")
@auth.admin_required
def decline(req_id):
    get_db().execute("UPDATE access_requests SET status = 'declined', handled_by = ?, handled_at = ? WHERE id = ?",
                     (g.user["id"], now(), req_id))
    return redirect(url_for("admin.index"))


@bp.post("/invite/<token_hash>/cancel")
@auth.admin_required
def cancel_invite(token_hash):
    get_db().execute("UPDATE invites SET expires_at = ? WHERE token_hash = ? AND used_at IS NULL", (now(), token_hash))
    return redirect(url_for("admin.index"))


@bp.post("/user/<int:user_id>/active")
@auth.admin_required
def set_active(user_id):
    if user_id == g.user["id"]:
        abort(400, "You can't switch off your own account.")
    on = 1 if request.form.get("active") == "1" else 0
    db = get_db()
    db.execute("UPDATE users SET active = ? WHERE id = ?", (on, user_id))
    if not on:
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        db.execute("UPDATE api_keys SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now(), user_id))
    log("admin", f"user {user_id} {'on' if on else 'off'}", user_id=g.user["id"])
    return redirect(url_for("admin.index"))
