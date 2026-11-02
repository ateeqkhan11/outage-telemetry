import base64

import pytest

from probe.chain import GENESIS, ChainError, canonical, load_private, load_public, public_b64, seal, verify

SEED = base64.b64encode(bytes(range(32))).decode()


def chain(n=3):
    key = load_private(SEED)
    prev, out = GENESIS, []
    for i in range(n):
        r = seal({"service": "s3", "ok": True, "latency_ms": 80 + i, "minute": f"2026-11-03T14:0{i}Z"}, prev, i + 1, key)
        prev = r["hash"]
        out.append(r)
    return out, load_public(public_b64(key))


def test_valid_chain_verifies():
    recs, pub = chain()
    assert verify(recs, pub, expect_prev=GENESIS) == []


def test_any_change_is_caught():
    recs, pub = chain()
    recs[1]["ok"] = False                                   # someone flips a result
    assert any("does not match its hash" in p for p in verify(recs, pub))


def test_removed_record_is_caught():
    recs, pub = chain()
    del recs[1]
    problems = verify(recs, pub)
    assert any("does not link" in p for p in problems) and any("sequence jumps" in p for p in problems)


def test_resigned_with_another_key_is_caught():
    recs, pub = chain()
    other = load_private(base64.b64encode(bytes(32)).decode())
    forged = seal({k: v for k, v in recs[2].items() if k not in ("hash", "sig", "prev", "seq")}, recs[1]["hash"], 3, other)
    assert any("signature is not valid" in p for p in verify(recs[:2] + [forged], pub))


def test_floats_and_non_ascii_are_refused():
    with pytest.raises(ChainError):
        canonical({"latency_ms": 80.5})
    with pytest.raises(ChainError):
        canonical({"error": "délai"})
