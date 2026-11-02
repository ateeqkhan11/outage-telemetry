"""Tamper-evident records.

Every record carries `prev` (the hash of the record before it on the same probe network), `hash` (SHA-256 of the
record's canonical JSON, which includes `prev` and `seq`) and `sig` (an Ed25519 signature over the hash bytes).
Changing, removing or reordering any record breaks the chain from that point on, and nobody without the network's
private key can produce a valid signature.

Canonical JSON is shared with the Cloudflare Worker (workers/src/chain.js), so both must stay identical:
keys sorted, no spaces, ASCII only, and only strings, integers, booleans and null as values (no floats: JavaScript
and Python print them differently).
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Iterable, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

GENESIS = "0" * 64
UNSIGNED = ("hash", "sig")


class ChainError(ValueError):
    pass


def canonical(rec: dict) -> bytes:
    body = {k: v for k, v in rec.items() if k not in UNSIGNED}
    for k, v in body.items():
        if isinstance(v, float):
            raise ChainError(f"field {k!r} is a float; records hold integers only")
        if isinstance(v, str) and not v.isascii():
            raise ChainError(f"field {k!r} is not ASCII")
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def load_private(seed_b64: str) -> Ed25519PrivateKey:
    seed = base64.b64decode(seed_b64.strip())
    if len(seed) != 32:
        raise ChainError("the signing key must be a base64-encoded 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(seed)


def load_public(pub_b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64.strip()))


def public_b64(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def seal(rec: dict, prev_hash: str, seq: int, key: Ed25519PrivateKey) -> dict:
    """Link `rec` to the chain and sign it. Returns a new dict."""
    out = dict(rec, prev=prev_hash, seq=seq)
    digest = hashlib.sha256(canonical(out)).hexdigest()
    out["hash"] = digest
    out["sig"] = base64.b64encode(key.sign(bytes.fromhex(digest))).decode()
    return out


def verify(records: Iterable[dict], pub: Ed25519PublicKey, expect_prev: Optional[str] = None) -> List[str]:
    """Check hashes, signatures, sequence and links. Returns a list of problems (empty = valid)."""
    problems: List[str] = []
    prev, last_seq = expect_prev, None
    for i, r in enumerate(records):
        where = f"record {i} (seq {r.get('seq')})"
        try:
            digest = hashlib.sha256(canonical(r)).hexdigest()
        except ChainError as e:
            problems.append(f"{where}: {e}")
            continue
        if digest != r.get("hash"):
            problems.append(f"{where}: content does not match its hash")
        try:
            pub.verify(base64.b64decode(r.get("sig", "")), bytes.fromhex(r.get("hash", "")))
        except Exception:
            problems.append(f"{where}: signature is not valid for this network's key")
        if prev is not None and r.get("prev") != prev:
            problems.append(f"{where}: does not link to the record before it")
        if last_seq is not None and r.get("seq") != last_seq + 1:
            problems.append(f"{where}: sequence jumps from {last_seq} to {r.get('seq')}")
        prev, last_seq = r.get("hash"), r.get("seq")
    return problems
