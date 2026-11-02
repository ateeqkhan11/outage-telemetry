"""Azure Functions probe network: a timer that runs once a minute and probes once.

Deploy this folder together with the `probe` package (copy ../probe next to this file, or let the deploy script do it).
App settings: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, PROBE_SIGNING_KEY (the azure network's own key),
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, PROBE_BUCKET, PROBE_TABLE, PROBE_FUNCTION.
Note: Azure and GitHub Actions are both Microsoft infrastructure, so trigger_v1.json counts them as one operator.
"""
import os

import azure.functions as func

from probe import checks as chk
from probe.chain import load_private
from probe.run import run_minutes
from probe.store import R2Store

app = func.FunctionApp()


@app.timer_trigger(schedule="0 * * * * *", arg_name="timer", run_on_startup=False, use_monitor=False)
def probe_minute(timer: func.TimerRequest) -> None:
    run_minutes("azure", 1, R2Store(), load_private(os.environ["PROBE_SIGNING_KEY"]), chk.aws_checks(), chk.control_check(),
                wait=False, rounds=int(os.environ.get("PROBE_ROUNDS", "6")))
