#!/bin/bash
# Deploy the latest main branch to the app server and restart it. Run in AWS CloudShell: bash app_update.sh
set -euo pipefail
source <(curl -sL "${HELPER_URL:-https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/_ssm_run.sh}")
ssm_run "set -e; cd /opt/nimbus/src; runuser -u nimbus -- git fetch --quiet --depth 1 origin main; runuser -u nimbus -- git reset --quiet --hard FETCH_HEAD; runuser -u nimbus -- /opt/nimbus/venv/bin/pip install --quiet -r app/requirements.txt; systemctl restart nimbus-app; sleep 2; systemctl is-active nimbus-app; git log --oneline -1"
