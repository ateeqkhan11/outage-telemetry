"""Reference probe inside AWS: a Lambda in us-west-2 (Oregon) checking us-east-1 once a minute, 6 rounds per minute.

It's an extra view only. trigger_v1*.json lists the "aws" network under reference_networks, so it's shown on the
dashboard but never counted: a probe running on AWS can't independently judge AWS.
Results go to an S3 bucket in us-west-2; the GitHub workflow copies them into the public data branch.
The signing key lives in SSM Parameter Store (created by infra/aws/oregon.sh, never leaves AWS).

It no longer starts the GitHub probe: a scheduler inside AWS could be silenced by the very outage being measured, so
the Cloudflare Worker's timer does that now (fix 3).
"""
import os

import boto3

from probe import checks as chk
from probe.chain import load_private
from probe.run import run_minutes
from probe.store import S3Store

_key = None


def handler(event, context):
    global _key
    os.environ.setdefault("PROBE_STARTED_BY", "eventbridge")   # recorded in every record (what started the run)
    if _key is None:
        seed = boto3.client("ssm").get_parameter(Name=os.environ["KEY_PARAM"], WithDecryption=True)["Parameter"]["Value"]
        _key = load_private(seed)
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    store = S3Store(os.environ["RESULTS_BUCKET"])
    # EventBridge delivers "at least once": two copies can start in the same minute and both extend the chain from the
    # same head (a fork). Claim the minute first with a write that only succeeds if nobody else has made it.
    try:
        store.s3.put_object(Bucket=store.bucket, Key=f"claims/aws/{now.strftime('%Y-%m-%d/%H%M')}", Body=b"",
                            IfNoneMatch="*")
    except store.s3.exceptions.ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("PreconditionFailed", "ConditionalRequestConflict"):
            return {"skipped": "another copy already claimed this minute"}
        raise
    head = json.loads(store.get("chains/aws/head.json") or b"null")
    if head and head["at"][:16] == now.strftime("%Y-%m-%dT%H:%M"):
        return {"skipped": "this minute is already recorded"}
    n = run_minutes("aws", 1, store, _key, chk.aws_checks(), chk.control_check(),
                    wait=False, rounds=int(os.environ.get("PROBE_ROUNDS", "6")))
    return {"records": n}
