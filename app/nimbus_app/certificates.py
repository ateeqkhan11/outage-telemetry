"""Signed outage certificates: one outage, the rule that called it, the evidence behind it, and (optionally) what a
policy on given terms would pay. Signed by Nimbus Index with Ed25519 exactly like a probe record (probe.chain), so
the same tools check it:

  hash = SHA-256 of the canonical JSON of every field except "hash" and "sig";  sig = Ed25519 over the hash bytes.

Evidence: for every probe network, the first and last signed record in the outage window (plus the window before it
that the rule looks back over), with their sequence numbers and hashes. Anyone can download that network's records for
the day, check each signature with the network's public key, and walk the hash chain from the first to the last.

The signing key comes from NIMBUS_CERT_KEY (base64 32-byte seed) or, failing that, instance/cert_key (created once,
readable only by the app's user).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from probe.chain import canonical, load_private, load_public, public_b64
from probe.detect import FMT

from .reports import definition_cfg, definitions

CERT_VERSION = 1


def signing_key(instance_dir: str):
    seed = os.environ.get("NIMBUS_CERT_KEY")
    if not seed:
        p = Path(instance_dir) / "cert_key"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            k = Ed25519PrivateKey.generate()
            from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
            raw = k.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(base64.b64encode(raw).decode())
        seed = p.read_text().strip()
    return load_private(seed)


def evidence(data_dir: str, start: str, end: str, lookback_min: int) -> dict:
    """First and last signed record per network between start - lookback and end (inclusive), from the data mirror."""
    t0 = datetime.strptime(start, FMT) - timedelta(minutes=lookback_min)
    t1 = datetime.strptime(end, FMT)
    root = Path(data_dir) / "runs"
    out = {}
    if not root.exists():
        return out
    for net_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        first = last = None
        n = 0
        t = t0
        while t <= t1:
            f = net_dir / t.strftime("%Y-%m-%d") / f"{t:%H%M}.jsonl"
            if f.exists():
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    n += 1
                    if first is None or r["seq"] < first["seq"]:
                        first = r
                    if last is None or r["seq"] > last["seq"]:
                        last = r
            t += timedelta(minutes=1)
        if n:
            out[net_dir.name] = {"records": n, "first": {"seq": first["seq"], "hash": first["hash"], "at": first["at"]},
                                 "last": {"seq": last["seq"], "hash": last["hash"], "at": last["at"]},
                                 "days": sorted({t0.strftime("%Y-%m-%d"), t1.strftime("%Y-%m-%d")})}
    return out


def build(cfg: dict, data_dir: str, instance_dir: str, outage: dict, definition: str, services: list,
          terms: Optional[dict] = None, payout: Optional[dict] = None, demo: bool = False) -> dict:
    d = definitions(cfg)[definition]
    dcfg = definition_cfg(cfg, definition)
    ev = evidence(data_dir, outage["start"], outage["end"], int(dcfg["window_minutes"]))
    cert = {
        "v": CERT_VERSION, "kind": "nimbus-outage-certificate", "issuer": "Nimbus Index",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "example_data": bool(demo),
        "region": cfg["region"], "services": services,
        "rules": {"version": cfg["version"], "definition": definition, "label": d["label"],
                  "description": d.get("description", ""), "operators_required": cfg["operators_required"],
                  "window_minutes": int(dcfg["window_minutes"]),
                  "window_fail_share_pct": int(round(100 * float(dcfg["window_fail_share"]))),
                  "recovery_minutes": cfg["recovery_minutes"], "reference_networks": cfg.get("reference_networks", [])},
        "outage": {"start": outage["start"], "end": outage["end"], "ongoing": bool(outage.get("ongoing")),
                   "minutes": outage.get("minutes", outage.get("duration_min")),
                   "services_down": outage["services"],
                   "parts": [{"start": p["start"], "end": p["end"], "duration_min": p["duration_min"]}
                             for p in outage.get("parts", [outage])]},
        "evidence": ev,
        "evidence_note": ("Records are signed by each probe network; check them with the public keys at /api/v1/keys and "
                          "walk each chain from 'first' to 'last'.") if ev else
                         "Signed records for this period are not available in this copy of the data.",
    }
    if terms is not None and payout is not None:
        cert["policy"] = {"terms": terms, "indemnity_min": payout["indemnity_min"], "payout": payout["payout"],
                          "capped": payout["capped"], "currency": "USD"}
    key = signing_key(instance_dir)
    digest = hashlib.sha256(canonical(cert)).hexdigest()       # certificates stand alone: no chain fields
    cert["hash"] = digest
    cert["sig"] = base64.b64encode(key.sign(bytes.fromhex(digest))).decode()
    cert["public_key"] = public_b64(key)
    return cert


def verify(cert: dict) -> bool:
    body = {k: v for k, v in cert.items() if k not in ("hash", "sig", "public_key")}
    digest = hashlib.sha256(canonical(body)).hexdigest()
    if digest != cert.get("hash"):
        return False
    try:
        load_public(cert["public_key"]).verify(base64.b64decode(cert["sig"]), bytes.fromhex(digest))
        return True
    except Exception:
        return False
