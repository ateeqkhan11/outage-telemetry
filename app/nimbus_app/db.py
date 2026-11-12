"""SQLite storage for the app: people, sign-in sessions, invites, API keys, activity, and per-minute check counts.

The signed records themselves are never stored here. They stay in the public data branch (mirrored to disk by
mirror.py); this database only keeps counts derived from them, so reports over weeks stay fast.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  company TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'member',            -- member | admin
  pw_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login_at TEXT,
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ip TEXT, user_agent TEXT
);
CREATE TABLE IF NOT EXISTS access_requests (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, email TEXT NOT NULL, company TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
  use_case TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, ip TEXT,
  status TEXT NOT NULL DEFAULT 'new',             -- new | invited | declined
  handled_by INTEGER REFERENCES users(id), handled_at TEXT
);
CREATE TABLE IF NOT EXISTS invites (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', company TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'member',
  created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  used_at TEXT, request_id INTEGER REFERENCES access_requests(id)
);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  prefix TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  api_key_id INTEGER REFERENCES api_keys(id),
  kind TEXT NOT NULL,                              -- sign_in | dashboard | report | download | api | admin | ...
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS activity_user ON activity (user_id, at);
CREATE INDEX IF NOT EXISTS activity_at ON activity (at);

-- one row per file in runs/<network>/<day>/ that has been counted
CREATE TABLE IF NOT EXISTS ingested_files (
  src TEXT PRIMARY KEY, network TEXT NOT NULL, day TEXT NOT NULL, size INTEGER NOT NULL, ingested_at TEXT NOT NULL
);
-- per minute, network and service: raw call counts, plus the counts the outage rule uses
--   failed/usable: only rounds whose control call worked, only failures whose kind means "down" (probe.detect)
CREATE TABLE IF NOT EXISTS minute_counts (
  src TEXT NOT NULL, network TEXT NOT NULL, minute TEXT NOT NULL, service TEXT NOT NULL,
  checks INTEGER NOT NULL, ok INTEGER NOT NULL, failed INTEGER NOT NULL, usable INTEGER NOT NULL,
  lat_sum INTEGER NOT NULL, lat_n INTEGER NOT NULL,
  PRIMARY KEY (src, network, minute, service)
);
CREATE INDEX IF NOT EXISTS minute_counts_minute ON minute_counts (minute);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30, isolation_level=None)   # autocommit; explicit BEGIN where needed
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def init(path: str) -> None:
    con = connect(path)
    con.executescript(SCHEMA)
    con.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def log(kind: str, detail: str = "", user_id=None, api_key_id=None) -> None:
    get_db().execute("INSERT INTO activity (at, user_id, api_key_id, kind, detail) VALUES (?, ?, ?, ?, ?)",
                     (now(), user_id, api_key_id, kind, detail[:500]))
