"""Reference probe inside AWS: a Lambda in us-west-2 (Oregon) checking us-east-1 once a minute, 6 rounds per minute.

It's an extra view only. trigger_v1*.json lists the "aws" network under reference_networks, so it's shown on the
dashboard but never counted: a probe running on AWS can't independently judge AWS.
Results go to an S3 bucket in us-west-2; the GitHub workflow copies them into the public data branch.
The signing key lives in SSM Parameter Store (created by infra/aws/oregon.sh, never leaves AWS).

It also starts the GitHub probe every 5 minutes (GitHub's own scheduler is unreliable): if the SSM parameter named by
GITHUB_TOKEN_PARAM holds a fine-grained token allowed only to run this repo's Actions, it asks GitHub to run
probe-github.yml at minutes 3, 8, 13, ... A failure here never stops the probe.
"""
import os

import boto3

from probe import checks as chk
from probe.chain import load_private
from probe.run import run_minutes
from probe.store import S3Store

_key = None
_gh_token = None


def dispatch_github() -> str:
    """Ask GitHub to run the probe workflow (workflow_dispatch). Returns what happened, for the logs."""
    global _gh_token
    import urllib.request
    param, repo = os.environ.get("GITHUB_TOKEN_PARAM"), os.environ.get("DISPATCH_REPO")
    if not param or not repo:
        return "not configured"
    try:                                                     # read every time (once per 5 min): a replaced token takes effect at once
        _gh_token = boto3.client("ssm").get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"].strip()
    except Exception as e:                                   # no token stored yet
        return f"no token: {type(e).__name__}"
    if not _gh_token:
        return "token is empty"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/probe.yml/dispatches", method="POST",
        data=b'{"ref":"main"}', headers={"Authorization": f"Bearer {_gh_token}", "Accept": "application/vnd.github+json",
                                         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "outage-telemetry-dispatch"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"dispatched ({r.status})"
    except Exception as e:
        return f"dispatch failed: {e}"


def handler(event, context):
    global _key
    if _key is None:
        seed = boto3.client("ssm").get_parameter(Name=os.environ["KEY_PARAM"], WithDecryption=True)["Parameter"]["Value"]
        _key = load_private(seed)
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if now.minute % 5 == 3:
        print("github:", dispatch_github())
    store = S3Store(os.environ["RESULTS_BUCKET"])
    head = json.loads(store.get("chains/aws/head.json") or b"null")
    if head and head["at"][:16] == datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"):
        return {"skipped": "this minute is already recorded"}    # EventBridge can deliver an invocation twice
    n = run_minutes("aws", 1, store, _key, chk.aws_checks(), chk.control_check(),
                    wait=False, rounds=int(os.environ.get("PROBE_ROUNDS", "6")))
    return {"records": n}
