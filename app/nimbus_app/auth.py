"""Sign-in sessions, CSRF protection, invites and API keys.

- Passwords: Werkzeug's scrypt hashes (PBKDF2-SHA256, 600,000 rounds, where Python lacks scrypt). At least 12 characters.
- Sessions: a random id in an HttpOnly cookie; only its SHA-256 is stored, so a copied database can't sign anyone in.
  Sessions end after 14 days, or 12 hours without use.
- Lockout: 5 wrong passwords lock the account for 15 minutes; each address is also limited to 20 tries per 15 minutes.
- Invites and API keys: random tokens shown once; only their SHA-256 is stored.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional

from flask import abort, current_app, g, redirect, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, log, now

COOKIE = "nimbus_session"
SESSION_MAX = timedelta(days=14)
SESSION_IDLE = timedelta(hours=12)
LOCK_AFTER, LOCK_FOR = 5, timedelta(minutes=15)
MIN_PASSWORD = 12
INVITE_DAYS = 7
KEY_PREFIX = "nk_live_"

_ip_attempts = defaultdict(deque)                         # in-process rate limit for sign-in attempts
_api_calls = defaultdict(deque)                           # in-process rate limit per API key


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def ts(s: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if s else None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


PW_METHOD = "scrypt" if hasattr(hashlib, "scrypt") else "pbkdf2:sha256:600000"   # scrypt needs OpenSSL


def hash_password(pw: str) -> str:
    return generate_password_hash(pw, method=PW_METHOD)


def password_problem(pw: str) -> Optional[str]:
    if len(pw) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if pw.lower() in {"password1234", "nimbusindex1", "123456789012"}:
        return "Choose a less common password."
    return None


# ---- sessions -----------------------------------------------------------------------------------------------------

def load_session() -> None:
    """Runs before every request: sets g.user and g.csrf when a valid session cookie is present."""
    g.user, g.csrf, g.session_hash = None, None, None
    sid = request.cookies.get(COOKIE)
    if not sid:
        return
    db = get_db()
    row = db.execute("SELECT s.*, u.active FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id_hash = ?",
                     (sha(sid),)).fetchone()
    if row is None:
        return
    t = utcnow()
    if not row["active"] or t - ts(row["created_at"]) > SESSION_MAX or t - ts(row["last_seen_at"]) > SESSION_IDLE:
        db.execute("DELETE FROM sessions WHERE id_hash = ?", (row["id_hash"],))
        return
    if t - ts(row["last_seen_at"]) > timedelta(minutes=5):
        db.execute("UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?", (now(), row["id_hash"]))
    g.user = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    g.csrf, g.session_hash = row["csrf"], row["id_hash"]


def start_session(resp, user_id: int):
    sid = secrets.token_urlsafe(32)
    get_db().execute("INSERT INTO sessions (id_hash, user_id, csrf, created_at, last_seen_at, ip, user_agent)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (sha(sid), user_id, secrets.token_urlsafe(24), now(), now(), client_ip(),
                      (request.user_agent.string or "")[:200]))
    resp.set_cookie(COOKIE, sid, max_age=int(SESSION_MAX.total_seconds()), httponly=True, samesite="Lax",
                    secure=current_app.config["SECURE_COOKIES"], path="/")
    return resp


def end_session(resp):
    if g.get("session_hash"):
        get_db().execute("DELETE FROM sessions WHERE id_hash = ?", (g.session_hash,))
    resp.delete_cookie(COOKIE, path="/")
    return resp


def client_ip() -> str:
    # Behind our own reverse proxy (Caddy) the client address is the last X-Forwarded-For entry it added.
    if current_app.config["BEHIND_PROXY"] and request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[-1].strip()
    return request.remote_addr or ""


def ip_allowed(bucket: str = "sign_in", limit: int = 20, window: int = 900) -> bool:
    q, t = _ip_attempts[(bucket, client_ip())], time.time()
    while q and q[0] < t - window:
        q.popleft()
    q.append(t)
    return len(q) <= limit


def check_login(email: str, password: str):
    """Returns (user, error)."""
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()
    if u is None:
        check_password_hash(hash_password("x" * 12), password)   # same work either way, so timing reveals nothing
        return None, "That email and password don't match an account."
    if u["locked_until"] and ts(u["locked_until"]) > utcnow():
        return None, "Too many wrong passwords. Try again in 15 minutes."
    if not check_password_hash(u["pw_hash"], password):
        fails = u["failed_logins"] + 1
        locked = fmt(utcnow() + LOCK_FOR) if fails >= LOCK_AFTER else None
        db.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                   (0 if locked else fails, locked, u["id"]))
        return None, "That email and password don't match an account."
    if not u["active"]:
        return None, "This account is switched off. Contact Nimbus Index to turn it back on."
    db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = ? WHERE id = ?", (now(), u["id"]))
    log("sign_in", "", user_id=u["id"])
    return u, None


# ---- CSRF and access decorators -----------------------------------------------------------------------------------

def check_csrf() -> None:
    if request.method != "POST":
        return
    if request.path.startswith("/api/"):
        return                                                # API: bearer keys, no cookies
    sent = request.form.get("csrf", "")
    if g.get("csrf"):
        if not hmac.compare_digest(sent, g.csrf):
            abort(400, "This form expired. Reload the page and try again.")
    else:
        # Signed-out forms (sign in, request access, accept invite): double-submit cookie
        if not sent or not hmac.compare_digest(sent, request.cookies.get("nimbus_csrf", "")):
            abort(400, "This form expired. Reload the page and try again.")


def anon_csrf() -> str:
    tok = request.cookies.get("nimbus_csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        g.set_anon_csrf = tok
    return tok


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if g.user is None:
            return redirect(url_for("web.login", next=request.full_path if request.query_string else request.path))
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if g.user["role"] != "admin":
            abort(403)
        return fn(*a, **kw)
    return wrapper


# ---- invites ------------------------------------------------------------------------------------------------------

def create_invite(email: str, name: str = "", company: str = "", role: str = "member", created_by=None,
                  request_id=None) -> str:
    tok = secrets.token_urlsafe(24)
    get_db().execute("INSERT INTO invites (token_hash, email, name, company, role, created_by, created_at, expires_at, request_id)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (sha(tok), email.strip(), name.strip(), company.strip(), role, created_by, now(),
                      fmt(utcnow() + timedelta(days=INVITE_DAYS)), request_id))
    return tok


def find_invite(tok: str):
    row = get_db().execute("SELECT * FROM invites WHERE token_hash = ?", (sha(tok),)).fetchone()
    if row is None or row["used_at"] or ts(row["expires_at"]) < utcnow():
        return None
    return row


# ---- API keys -----------------------------------------------------------------------------------------------------

def create_api_key(user_id: int, name: str):
    key = KEY_PREFIX + secrets.token_urlsafe(30)
    get_db().execute("INSERT INTO api_keys (user_id, name, prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                     (user_id, name.strip()[:60] or "API key", key[:14], sha(key), now()))
    return key


def api_key_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        from flask import jsonify
        auth = request.headers.get("Authorization", "")
        key = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("X-API-Key", "").strip()
        if not key.startswith(KEY_PREFIX):
            return jsonify(error="Send your API key as 'Authorization: Bearer nk_live_...'. Create one under API access."), 401
        db = get_db()
        row = db.execute("SELECT k.*, u.active FROM api_keys k JOIN users u ON u.id = k.user_id WHERE k.key_hash = ?",
                         (sha(key),)).fetchone()
        if row is None or row["revoked_at"] or not row["active"]:
            return jsonify(error="This API key isn't valid. It may have been revoked."), 401
        q, t = _api_calls[row["id"]], time.time()
        while q and q[0] < t - 60:
            q.popleft()
        if len(q) >= current_app.config["API_PER_MINUTE"]:
            return jsonify(error=f"Slow down: at most {current_app.config['API_PER_MINUTE']} calls a minute per key."), 429
        q.append(t)
        db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now(), row["id"]))
        log("api", request.full_path.rstrip("?")[:300], user_id=row["user_id"], api_key_id=row["id"])
        g.api_user_id = row["user_id"]
        return fn(*a, **kw)
    return wrapper
