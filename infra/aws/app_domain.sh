#!/bin/bash
# Serve the app at a real domain once its DNS record points at the server's address. Run in AWS CloudShell:
#   DOMAIN=app.nimbusindex.com bash app_domain.sh
# The old sslip.io address keeps working, so nothing breaks while DNS spreads.
set -euo pipefail
[[ "${DOMAIN:-}" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] || { echo "Set DOMAIN, e.g. DOMAIN=app.nimbusindex.com"; exit 1; }
source <(curl -sL "${HELPER_URL:-https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/_ssm_run.sh}")
ssm_run "set -e; OLD=\$(head -1 /etc/caddy/Caddyfile | cut -d' ' -f1 | tr -d ,); printf '%s, %s {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8000\n}\n' $DOMAIN \$OLD > /etc/caddy/Caddyfile; sed -i 's#^NIMBUS_BASE_URL=.*#NIMBUS_BASE_URL=https://$DOMAIN#' /etc/nimbus/env; systemctl reload caddy; systemctl restart nimbus-app; cat /etc/caddy/Caddyfile"
