"""The Cloudflare Worker (JavaScript) and the Python probe must sign identically: Python verifies JS output."""
import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from probe.chain import GENESIS, load_private, load_public, public_b64, verify

ROOT = Path(__file__).parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_verifies_records_signed_by_the_worker_code():
    seed = base64.b64encode(bytes(range(32))).decode()
    out = subprocess.run(["node", "test/chain_sample.mjs", seed], cwd=ROOT / "workers", capture_output=True, text=True, check=True)
    recs = [json.loads(line) for line in out.stdout.splitlines()]
    assert len(recs) == 2
    assert verify(recs, load_public(public_b64(load_private(seed))), expect_prev=GENESIS) == []
