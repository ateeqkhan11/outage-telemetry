#!/bin/bash
# Deploy the latest main branch (app and website) to the app server, keep Caddy on its pinned version, and restart. Run in AWS CloudShell: bash app_update.sh
set -euo pipefail
source <(curl -sL "${HELPER_URL:-https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/_ssm_run.sh}")
ssm_run "set -e; cd /opt/nimbus/src; runuser -u nimbus -- git fetch --quiet --depth 1 origin main; runuser -u nimbus -- git reset --quiet --hard FETCH_HEAD; runuser -u nimbus -- /opt/nimbus/venv/bin/pip install --quiet -r app/requirements.txt; bash /opt/nimbus/src/infra/aws/publish_site.sh; bash /opt/nimbus/src/infra/aws/caddy_upgrade.sh; systemctl restart nimbus-app; sleep 2; systemctl is-active nimbus-app; runuser -u nimbus -- git -C /opt/nimbus/src log --oneline -1; /usr/local/bin/caddy version"
