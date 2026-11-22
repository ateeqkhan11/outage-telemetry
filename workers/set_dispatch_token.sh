#!/usr/bin/env bash
# Let the Cloudflare Worker start the GitHub probe every 5 minutes (fix 3: the scheduler lives outside AWS).
# Run on your Mac, in the repo:   bash workers/set_dispatch_token.sh
#
# First create a token: github.com -> Settings -> Developer settings -> Fine-grained tokens -> Generate new token
#   Repository access: Only select repositories -> outage-telemetry
#   Permissions: Actions -> Read and write   (nothing else)
#   Expiration: up to a year; put a reminder in your calendar to replace it.
# The script asks for it (hidden), checks GitHub accepts it, stores it as a Worker secret, redeploys, and forgets it.
set -euo pipefail
cd "$(dirname "$0")"
REPO=ateeqkhan11/outage-telemetry
echo "Paste the GitHub token when asked. Nothing appears while you paste; that's normal."
read -rsp "GitHub token: " T; echo
case "$T" in github_pat_*) ;; *) unset T; echo "That doesn't look like a fine-grained token (github_pat_...). Nothing stored."; exit 1;; esac
code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $T" "https://api.github.com/repos/$REPO/actions/workflows/probe.yml")
if [ "$code" != 200 ]; then unset T; echo "GitHub refused the token (HTTP $code). It needs Actions: Read and write on outage-telemetry. Nothing stored."; exit 1; fi
printf '%s' "$T" | npx --yes wrangler secret put GITHUB_DISPATCH_TOKEN
unset T
npx --yes wrangler deploy
echo
echo "Done. Within 5 minutes GitHub should show a probe-github run started by workflow_dispatch;"
echo "its 'Log what started this run' step says started_by=cloudflare-cron."
echo "Then stop the old trigger in AWS (CloudShell):  aws ssm delete-parameter --region us-west-2 --name /outage-probe/github-token"
echo "and revoke the old token on GitHub."
