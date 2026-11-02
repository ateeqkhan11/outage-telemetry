"""The checks one probe network runs every minute: five AWS us-east-1 API calls plus one control check.

The control check calls a site outside AWS (and outside the probe's own host where possible). If it fails too,
the probe's own connection is the problem, so that minute is marked "probe down" rather than counted as an AWS
failure.

Each check is a plain function that raises on failure. To use SRE's probe script instead, replace `aws_checks`
with its calls; `run_check` and the record format stay the same.

Settings come from environment variables (see README):
  PROBE_BUCKET, PROBE_OBJECT_KEY   S3 object to read (default probe.txt)
  PROBE_TABLE, PROBE_TABLE_KEY     DynamoDB table and the item key as JSON, e.g. {"pk": {"S": "probe"}}
  PROBE_FUNCTION                   Lambda function name
  PROBE_CONTROL_URL                control site (default Google's 204 endpoint)
AWS credentials come from the usual AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Callable, Dict, List, Tuple

TARGET_REGION = "us-east-1"
CONTROL_URL = "https://www.google.com/generate_204"
TIMEOUT_S = 5

Check = Tuple[str, str, Callable[[], None]]          # (service, operation, function that raises on failure)


def aws_checks(env: Dict[str, str] = os.environ) -> List[Check]:
    import boto3
    from botocore.config import Config

    # one attempt, short timeouts: retries would hide exactly the failures we are here to record
    cfg = Config(region_name=TARGET_REGION, connect_timeout=3, read_timeout=TIMEOUT_S,
                 retries={"max_attempts": 1, "mode": "standard"})
    s3 = boto3.client("s3", config=cfg)
    ddb = boto3.client("dynamodb", config=cfg)
    lam = boto3.client("lambda", config=cfg)
    ec2 = boto3.client("ec2", config=cfg)
    sts = boto3.client("sts", config=cfg, endpoint_url=f"https://sts.{TARGET_REGION}.amazonaws.com")
    key = json.loads(env.get("PROBE_TABLE_KEY", '{"pk": {"S": "probe"}}'))

    def s3_get():
        s3.get_object(Bucket=env["PROBE_BUCKET"], Key=env.get("PROBE_OBJECT_KEY", "probe.txt"))["Body"].read()

    def ddb_get():
        ddb.get_item(TableName=env["PROBE_TABLE"], Key=key)

    def lambda_invoke():
        r = lam.invoke(FunctionName=env["PROBE_FUNCTION"], Payload=b"{}")
        if r.get("FunctionError"):
            raise RuntimeError("FunctionError:" + r["FunctionError"])

    def ec2_describe():
        ec2.describe_instances(MaxResults=5)

    def sts_identity():
        sts.get_caller_identity()

    return [("s3", "GetObject", s3_get), ("dynamodb", "GetItem", ddb_get), ("lambda", "Invoke", lambda_invoke),
            ("ec2", "DescribeInstances", ec2_describe), ("sts", "GetCallerIdentity", sts_identity)]


def control_check(env: Dict[str, str] = os.environ) -> Check:
    url = env.get("PROBE_CONTROL_URL", CONTROL_URL)

    def get():
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
            if r.status >= 400:
                raise RuntimeError(f"HTTP {r.status}")

    return ("control", "HTTPS GET", get)


def _ascii(text: str, limit: int = 160) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)[:limit]


THROTTLE_CODES = {"Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded",
                  "SlowDown", "ProvisionedThroughputExceededException", "RequestThrottled"}
TIMEOUTS = {"ReadTimeoutError", "ConnectTimeoutError", "TimeoutError", "timeout"}
NETWORK = {"EndpointConnectionError", "ConnectionClosedError", "ConnectionError", "URLError", "ProxyConnectionError",
           "SSLError", "gaierror", "ConnectionResetError", "ConnectionRefusedError"}


def classify(code: str, status, exc_name: str) -> str:
    """What kind of failure this was. Only some kinds mean the service was down (see fail_kinds in trigger_v1.json):
    AWS answering "your credentials are wrong" (client_error) proves the service was up."""
    if code in THROTTLE_CODES or status == 429:
        return "throttled"
    if status is not None and status >= 500:
        return "server_error"
    if status is not None and 400 <= status < 500:
        return "client_error"
    if exc_name in TIMEOUTS:
        return "timeout"
    if exc_name in NETWORK:
        return "network"
    return "other"


def run_check(fn: Callable[[], None]) -> dict:
    """Run one check and describe the outcome with integers and ASCII strings only."""
    t0 = time.perf_counter()
    try:
        fn()
        return {"ok": True, "kind": "ok", "latency_ms": int(round((time.perf_counter() - t0) * 1000)), "error": None, "status": None}
    except Exception as e:                                   # every failure is data
        name = type(e).__name__
        status, code = getattr(e, "status", None), name
        resp = getattr(e, "response", None)
        if isinstance(resp, dict):                           # botocore ClientError
            code = resp.get("Error", {}).get("Code") or code
            status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status is None and getattr(e, "code", None) and isinstance(getattr(e, "code"), int):
            status = e.code                                  # urllib HTTPError
        status = int(status) if status is not None else None
        return {"ok": False, "kind": classify(code, status, name), "latency_ms": int(round((time.perf_counter() - t0) * 1000)),
                "error": _ascii(f"{code}: {e}"), "status": status}
