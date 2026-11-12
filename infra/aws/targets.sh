#!/usr/bin/env bash
# One AWS test account per counted probe network, so a problem in one account (billing, permissions, throttling,
# suspension) can never look like an AWS outage: an outage needs two companies' probes, and now two accounts, to fail.
#
# Run in AWS CloudShell, signed in to the main (Ciyahi) account as an admin:
#
#   curl -sLO https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/targets.sh
#   EMAIL='you+{net}@example.com' bash targets.sh
#
# EMAIL is the sign-in email for each new account; {net} is replaced by the network name (github, cloudflare), so
# with Gmail-style "+" addresses they all reach one inbox. Every AWS account needs an email no other account uses.
#
# What it does (safe to run again; it reuses what already exists):
#   1. Turns on AWS Organizations for this account if it isn't already (asks first). The new accounts are billed to,
#      and share the credits of, this account.
#   2. Creates member accounts nimbus-target-github and nimbus-target-cloudflare (NETWORKS='github cloudflare gcp' adds more).
#   3. In each, runs setup.sh: S3 bucket + probe.txt, DynamoDB table + item, Lambda hello function, and an IAM user
#      allowed only those five checks. Its access key is printed ONCE.
#   4. Lets the github account's probe user read the reference probe's results bucket (the Oregon Lambda's output),
#      which the GitHub workflow copies into the public data.
# Then, on your Mac: bash infra/aws/use_target.sh github   (and cloudflare) to paste each key into GitHub / Cloudflare.
set -euo pipefail
export AWS_PAGER=""
: "${EMAIL:?Set EMAIL, e.g. EMAIL='you+{net}@example.com' bash targets.sh}"
case "$EMAIL" in *"{net}"*) ;; *) echo "EMAIL must contain {net} so each account gets its own address"; exit 1;; esac
NETWORKS=${NETWORKS:-"github cloudflare"}
SETUP_URL=${SETUP_URL:-https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/setup.sh}
MAIN=$(aws sts get-caller-identity --query Account --output text)
ME=$(aws sts get-caller-identity --query Arn --output text)
case "$ME" in *":root")
  echo "You are signed in as the account's root user, and AWS does not let root step into other accounts."
  echo "Sign in to the console as an IAM user or role with admin rights (IAM -> Users -> create one with"
  echo "AdministratorAccess if needed), open CloudShell again, and rerun this script."
  exit 1;;
esac
REF_BUCKET=${REF_BUCKET:-outage-probe-ref-$MAIN}
say() { printf '\n== %s\n' "$*"; }

say "AWS Organizations in account $MAIN"
if ! aws organizations describe-organization >/dev/null 2>&1; then
  echo "This account is not in an organization yet. Creating one makes it the management (paying) account;"
  echo "the test accounts below become members billed to it. Nothing about this account's own resources changes."
  read -r -p "Create the organization now? Type yes: " ok
  [ "$ok" = "yes" ] || { echo "Stopped."; exit 1; }
  aws organizations create-organization --feature-set ALL >/dev/null
fi
MGMT=$(aws organizations describe-organization --query Organization.MasterAccountId --output text)
[ "$MGMT" = "$MAIN" ] || { echo "This account belongs to another organization ($MGMT); run this from its management account."; exit 1; }

curl -sfL "$SETUP_URL" -o /tmp/nimbus-setup.sh

for net in $NETWORKS; do
  name="nimbus-target-$net"
  say "$name"
  id=$(aws organizations list-accounts --query "Accounts[?Name=='$name' && Status=='ACTIVE'].Id | [0]" --output text)
  if [ "$id" = "None" ] || [ -z "$id" ]; then
    email=${EMAIL//\{net\}/$net}
    echo "Creating account $name ($email); this usually takes 1-4 minutes"
    req=$(aws organizations create-account --email "$email" --account-name "$name" \
          --role-name OrganizationAccountAccessRole --iam-user-access-to-billing DENY \
          --tags Key=project,Value=outage-probe Key=network,Value="$net" --query CreateAccountStatus.Id --output text)
    for i in $(seq 1 60); do
      read -r state id reason < <(aws organizations describe-create-account-status --create-account-request-id "$req" \
        --query 'CreateAccountStatus.[State,AccountId,FailureReason]' --output text)
      [ "$state" = "SUCCEEDED" ] && break
      [ "$state" = "FAILED" ] && { echo "Account creation failed: $reason"; exit 1; }
      sleep 10
    done
    [ "$state" = "SUCCEEDED" ] || { echo "Still creating; run this script again in a few minutes."; exit 1; }
  fi
  echo "Account id $id"

  # act inside the new account through the role Organizations created there. Never fall back to this account.
  role="arn:aws:iam::$id:role/OrganizationAccountAccessRole"
  creds() {
    aws sts assume-role --role-arn "$role" --role-session-name nimbus-setup \
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text
  }
  c=""
  for i in $(seq 1 30); do
    if c=$(creds 2>/tmp/assume.err); then break; fi
    c=""; echo "waiting for the new account's role ($i/30): $(tail -1 /tmp/assume.err)"; sleep 10
  done
  [ -n "$c" ] || { echo "Could not step into $name ($id). Last error above. Nothing was changed in it; rerun later."; exit 1; }
  read -r AK SK ST <<<"$c"
  inside() { AWS_ACCESS_KEY_ID=$AK AWS_SECRET_ACCESS_KEY=$SK AWS_SESSION_TOKEN=$ST "$@"; }
  got=$(inside aws sts get-caller-identity --query Account --output text)
  [ "$got" = "$id" ] || { echo "Safety stop: expected account $id but credentials are for $got."; exit 1; }
  # new accounts can take a few minutes before every service accepts calls; setup.sh is safe to repeat
  for i in 1 2 3 4 5; do
    if inside bash /tmp/nimbus-setup.sh; then break; fi
    [ "$i" = 5 ] && { echo "setup.sh kept failing in $name; run this script again later."; exit 1; }
    echo "retrying in 60 s (new accounts need a few minutes to activate S3 and Lambda)"; sleep 60
    c=$(creds) && read -r AK SK ST <<<"$c"
  done

  if [ "$net" = "github" ] && aws s3api head-bucket --bucket "$REF_BUCKET" >/dev/null 2>&1; then
    say "Let $name's probe user read the reference results ($REF_BUCKET)"
    inside aws iam put-user-policy --user-name outage-probe \
      --policy-name read-reference --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
        {\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::$REF_BUCKET\"},
        {\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$REF_BUCKET/*\"}]}"
    current=$(aws s3api get-bucket-policy --bucket "$REF_BUCKET" --query Policy --output text 2>/dev/null || echo '')
    python3 - "$REF_BUCKET" "$id" "$current" > /tmp/ref-policy.json <<'PY'
import json, sys
bucket, acct, cur = sys.argv[1], sys.argv[2], sys.argv[3]
pol = json.loads(cur) if cur.strip() else {"Version": "2012-10-17", "Statement": []}
pol["Statement"] = [s for s in pol["Statement"] if s.get("Sid") != "NimbusTargetGithubRead"]
pol["Statement"].append({"Sid": "NimbusTargetGithubRead", "Effect": "Allow",
                         "Principal": {"AWS": f"arn:aws:iam::{acct}:user/outage-probe"},
                         "Action": ["s3:GetObject", "s3:ListBucket"],
                         "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]})
print(json.dumps(pol))
PY
    aws s3api put-bucket-policy --bucket "$REF_BUCKET" --policy file:///tmp/ref-policy.json
  fi
  echo
  echo ">>> $name done. On your Mac run:  bash infra/aws/use_target.sh $net"
  echo ">>> and give it: the access key above, bucket outage-probe-$id, test account name $name"
done

say "All done"
echo "Each test account costs cents a month. Optional: Billing -> Budgets in the main account, \$5/month per account."
echo "Once both networks run on their own accounts, the old probe user in $MAIN (outage-probe) can have its keys deleted."
