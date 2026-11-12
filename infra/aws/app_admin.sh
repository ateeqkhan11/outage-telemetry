#!/bin/bash
# Print a single-use admin invite link for the Nimbus Index app (valid 7 days). Run in AWS CloudShell:
#   bash app_admin.sh you@example.com
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: bash app_admin.sh EMAIL"; exit 1; }
[[ "$1" =~ ^[^@[:space:]\'\"\;\$\`]+@[^@[:space:]\'\"\;\$\`]+$ ]] || { echo "That doesn't look like an email address."; exit 1; }
source <(curl -sL "${HELPER_URL:-https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/_ssm_run.sh}")
echo "Open this link to set your password (it works once, for 7 days):"
ssm_run "/usr/local/bin/nimbus-manage invite '$1' --admin"
