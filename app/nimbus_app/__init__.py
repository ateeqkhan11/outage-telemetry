"""Nimbus Index app: invite-only access to the outage data for pilot firms.

  Dashboard   the live status (same page as the public dashboard, from the app's own copy of the data)
  Reports     official uptime, outages and per-network numbers for a date range; CSV and signed-record downloads
  API access  personal API keys and the /api/v1 endpoints
  Admin       access requests, invites, people, and who is using what

Configuration (environment variables):
  NIMBUS_SECRET_KEY      required in production
  NIMBUS_DB              SQLite file                         default instance/nimbus.db
  NIMBUS_DATA            local copy of the data branch       default instance/data
  NIMBUS_REPO            repository root (keys/, trigger rules, docs/)   default: two folders up from this package
  NIMBUS_DATA_REMOTE     git URL of the repository           default the public GitHub repo
  NIMBUS_BASE_URL        e.g. https://app.nimbusindex.com (used in invite links made from the command line)
  NIMBUS_SECURE_COOKIES  1 behind HTTPS (default 1)
  NIMBUS_BEHIND_PROXY    1 when Caddy forwards requests (default 0)
  NIMBUS_KEYS            folder of probe public keys          default <repo>/keys
  NIMBUS_DEMO            1 = example-data copy (see demo.py): every page says the numbers are simulated
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, g, render_template, request

from . import auth, db

PKG = Path(__file__).resolve().parent
DEFAULT_REPO = PKG.parent.parent


def create_app(overrides: dict = None) -> Flask:
    app = Flask(__name__, instance_path=os.environ.get("NIMBUS_INSTANCE", str(PKG.parent / "instance")))
    repo = Path(os.environ.get("NIMBUS_REPO", DEFAULT_REPO))
    app.config.update(
        SECRET_KEY=os.environ.get("NIMBUS_SECRET_KEY", "dev-only-not-secret"),
        DB_PATH=os.environ.get("NIMBUS_DB", os.path.join(app.instance_path, "nimbus.db")),
        DATA_DIR=os.environ.get("NIMBUS_DATA", os.path.join(app.instance_path, "data")),
        REPO_DIR=str(repo),
        KEYS_DIR=os.environ.get("NIMBUS_KEYS", str(repo / "keys")),
        DEMO=os.environ.get("NIMBUS_DEMO", "0") == "1",
        DATA_REMOTE=os.environ.get("NIMBUS_DATA_REMOTE", "https://github.com/ateeqkhan11/outage-telemetry.git"),
        BASE_URL=os.environ.get("NIMBUS_BASE_URL", "http://localhost:8080"),
        SECURE_COOKIES=os.environ.get("NIMBUS_SECURE_COOKIES", "1") == "1",
        BEHIND_PROXY=os.environ.get("NIMBUS_BEHIND_PROXY", "0") == "1",
        RULES_FILE=str(repo / "trigger_v1_rolling.json"),
        API_PER_MINUTE=120,
        MAX_CONTENT_LENGTH=64 * 1024,
        SESSION_COOKIE_NAME="nimbus_flash",
        SESSION_COOKIE_SAMESITE="Lax",
        PUBLIC_DASHBOARD="https://ateeqkhan11.github.io/outage-telemetry/",
        SOURCE_URL="https://github.com/ateeqkhan11/outage-telemetry",
    )
    if overrides:
        app.config.update(overrides)
    app.config["SESSION_COOKIE_SECURE"] = app.config["SECURE_COOKIES"]
    if app.config["SECRET_KEY"] == "dev-only-not-secret" and app.config["SECURE_COOKIES"]:
        raise RuntimeError("Set NIMBUS_SECRET_KEY (or NIMBUS_SECURE_COOKIES=0 for local development).")
    Path(app.config["DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    db.init(app.config["DB_PATH"])
    app.config["RULES"] = json.loads(Path(app.config["RULES_FILE"]).read_text())

    app.teardown_appcontext(db.close_db)

    @app.before_request
    def _before():
        auth.load_session()
        auth.check_csrf()

    @app.after_request
    def _after(resp):
        tok = g.pop("set_anon_csrf", None)
        if tok:
            resp.set_cookie("nimbus_csrf", tok, httponly=True, samesite="Strict", secure=app.config["SECURE_COOKIES"])
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                "font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if app.config["SECURE_COOKIES"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if g.get("user") is not None and not request.path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.context_processor
    def _ctx():
        return {"me": g.get("user"), "csrf": g.get("csrf") or auth.anon_csrf(), "demo": app.config["DEMO"]}

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def _err(e):
        if request.path.startswith("/api/"):
            return {"error": e.description}, e.code
        return render_template("error.html", code=e.code, message=e.description), e.code

    from .views import bp as web
    from .api import bp as api
    from .admin import bp as admin
    app.register_blueprint(web)
    app.register_blueprint(api)
    app.register_blueprint(admin)
    return app
