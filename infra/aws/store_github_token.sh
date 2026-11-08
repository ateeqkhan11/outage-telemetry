#!/usr/bin/env bash
# Store the GitHub token that lets the Oregon Lambda start the GitHub probe. Run in CloudShell with:
#   bash <(curl -sL https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/store_github_token.sh)
# It asks for the token (hidden), checks it can see the repo, stores it in SSM (us-west-2), and forgets it.
set -euo pipefail
echo "Paste the GitHub token when asked. Nothing appears while you paste; that's normal."
read -rsp "GitHub token: " T; echo
case "$T" in github_pat_*|ghp_*) ;; *) echo "That doesn't look like a GitHub token (it should start with github_pat_). Nothing stored."; exit 1;; esac
code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $T" https://api.github.com/repos/ateeqkhan11/outage-telemetry/actions/workflows)
if [ "$code" != 200 ]; then unset T; echo "GitHub refused the token (HTTP $code). Check it has Actions: Read and write on outage-telemetry. Nothing stored."; exit 1; fi
aws ssm put-parameter --region us-west-2 --name /outage-probe/github-token --type SecureString --value "$T" --overwrite >/dev/null
unset T
echo "Stored and checked. The Lambda starts the GitHub probe at minutes 3, 8, 13, ... (within 5 minutes)."
