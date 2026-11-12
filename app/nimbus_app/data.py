"""Read-only access to the app's copy of the data branch (status file, signed records, public keys)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from flask import current_app

NET_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def data_dir() -> Path:
    return Path(current_app.config["DATA_DIR"])


def status() -> Optional[dict]:
    p = data_dir() / "status" / "latest.json"
    return json.loads(p.read_text()) if p.exists() else None


def networks() -> list:
    root = data_dir() / "runs"
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def public_keys() -> dict:
    keys = Path(current_app.config["KEYS_DIR"])
    return {p.stem: p.read_text().strip() for p in sorted(keys.glob("*.pub"))}


def records_for_day(network: str, day: str) -> Optional[bytes]:
    """The day's signed records for one network, in chain order, as JSON lines (exactly as signed)."""
    if not NET_RE.match(network) or not DAY_RE.match(day):
        return None
    folder = data_dir() / "runs" / network / day
    if not folder.is_dir():
        return None
    lines = []
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                lines.append((json.loads(line)["seq"], line))
    lines.sort()
    return ("\n".join(line for _, line in lines) + "\n").encode() if lines else None


def manifest(day: str) -> Optional[dict]:
    if not DAY_RE.match(day):
        return None
    p = data_dir() / "daily" / day / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else None


def last_sync(db) -> Optional[str]:
    row = db.execute("SELECT v FROM meta WHERE k = 'last_sync'").fetchone()
    return row["v"] if row else None
