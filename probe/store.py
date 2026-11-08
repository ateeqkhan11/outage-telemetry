"""Where results go: Cloudflare R2 in production, a local folder for testing.

Layout (identical in both):
  chains/<network>/head.json                 last seq and hash on that network's chain
  runs/<network>/<YYYY-MM-DD>/<HHMM>.jsonl   one object per probed minute (R2 can't append to an object)
  daily/<YYYY-MM-DD>/<network>.jsonl         the day's records in order, built by probe.daily
  daily/<YYYY-MM-DD>/manifest.json           counts, gaps, chain check and file hashes for the day
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional


class LocalStore:
    def __init__(self, root: str):
        self.root = Path(root)

    def get(self, key: str) -> Optional[bytes]:
        p = self.root / key
        return p.read_bytes() if p.exists() else None

    def put(self, key: str, data: bytes) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def list(self, prefix: str) -> List[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file() and not p.name.endswith(".tmp"))


class R2Store:
    """R2 speaks the S3 API. Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET."""

    def __init__(self, env=os.environ):
        import boto3
        from botocore.config import Config
        self.bucket = env["R2_BUCKET"]
        self.s3 = boto3.client("s3", endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                               aws_access_key_id=env["R2_ACCESS_KEY_ID"], aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
                               region_name="auto", config=Config(retries={"max_attempts": 5, "mode": "standard"}))

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def list(self, prefix: str) -> List[str]:
        keys, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            keys += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return sorted(keys)
            token = r["NextContinuationToken"]


class S3Store(R2Store):
    """Plain AWS S3 with the caller's own credentials. Used only by the reference probe inside AWS (aws_lambda/)."""

    def __init__(self, bucket: str, region: Optional[str] = None):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)


def open_store(local: Optional[str] = None, env=os.environ):
    if local:
        return LocalStore(local)
    if env.get("R2_BUCKET"):
        return R2Store(env)
    raise SystemExit("No storage set: pass --local DIR, or set the R2_* environment variables")


def read_jsonl(data: Optional[bytes]) -> List[dict]:
    return [json.loads(line) for line in (data or b"").decode().splitlines() if line.strip()]


def to_jsonl(records: List[dict]) -> bytes:
    return ("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records)).encode()
