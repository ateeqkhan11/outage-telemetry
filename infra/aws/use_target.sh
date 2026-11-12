#!/usr/bin/env bash
# Point one probe network at its own AWS test account (made by targets.sh in CloudShell). Run on your Mac, in the repo:
#
#   bash infra/aws/use_target.sh github        GitHub Actions probe: sets repo secrets and variables with gh
#   bash infra/aws/use_target.sh cloudflare    Cloudflare Worker: sets Worker secrets and vars with wrangler, redeploys
#
# It asks for the access key (typed or pasted; the secret is not shown), the bucket name, and the account name.
# Nothing is written to disk except, for cloudflare, the non-secret bucket and account name in workers/wrangler.toml.
set -euo pipefail
net=${1:?Usage: bash infra/aws/use_target.sh github|cloudflare}
cd "$(dirname "$0")/../.."
read -r -p "Access key id for nimbus-target-$net: " AK
read -r -s -p "Secret access key (hidden): " SK; echo
read -r -p "Bucket (outage-probe-<account id>): " BUCKET
read -r -p "Test account name [nimbus-target-$net]: " NAME; NAME=${NAME:-nimbus-target-$net}
[ -n "$AK" ] && [ -n "$SK" ] && [ -n "$BUCKET" ] || { echo "Missing a value; nothing changed."; exit 1; }

case "$net" in
  github)
    GH=${GH:-$(command -v gh || echo "$HOME/.local/bin/gh")}
    printf '%s' "$AK" | "$GH" secret set PROBE_AWS_ACCESS_KEY_ID
    printf '%s' "$SK" | "$GH" secret set PROBE_AWS_SECRET_ACCESS_KEY
    "$GH" variable set PROBE_BUCKET --body "$BUCKET"
    "$GH" variable set PROBE_TARGET_ACCOUNT --body "$NAME"
    echo "GitHub updated. The next probe run (within 5 minutes) calls $NAME."
    ;;
  cloudflare)
    cd workers
    printf '%s' "$AK" | npx --yes wrangler secret put AWS_ACCESS_KEY_ID
    printf '%s' "$SK" | npx --yes wrangler secret put AWS_SECRET_ACCESS_KEY
    python3 - "$BUCKET" "$NAME" <<'PY'
import re, sys
bucket, name = sys.argv[1], sys.argv[2]
p = "wrangler.toml"; s = open(p).read()
s = re.sub(r'(?m)^PROBE_BUCKET\s*=.*$', f'PROBE_BUCKET = "{bucket}"', s)
if re.search(r'(?m)^TARGET_ACCOUNT\s*=', s):
    s = re.sub(r'(?m)^TARGET_ACCOUNT\s*=.*$', f'TARGET_ACCOUNT = "{name}"', s)
else:
    s = s.replace("[vars]\n", f'[vars]\nTARGET_ACCOUNT = "{name}"\n', 1)
open(p, "w").write(s)
PY
    npx --yes wrangler deploy
    echo "Cloudflare Worker redeployed against $NAME. Commit workers/wrangler.toml (bucket and account name only)."
    ;;
  *) echo "Unknown network $net (github or cloudflare)"; exit 1;;
esac
unset AK SK
