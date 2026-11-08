#!/usr/bin/env bash
# One-shot AWS setup for the outage probe. Run in AWS CloudShell (us-east-1) while signed in as an admin:
#
#   curl -sL https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/setup.sh | bash
#   ... | NO_KEY=1 bash      to skip creating the probe user's access key (create it in the console instead)
#
# Creates, all tagged project=outage-probe and safe to run again:
#   S3 bucket outage-probe-<account> with probe.txt, DynamoDB table outage-probe with one item,
#   Lambda outage-probe-hello (and its execution role), and IAM user outage-probe limited to the five checks.
# At the end it creates an access key for the probe user and prints it ONCE: put it straight into GitHub secrets.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="outage-probe-$ACCOUNT"
TAG="Key=project,Value=outage-probe"
echo "Account $ACCOUNT, region us-east-1, bucket $BUCKET"

say() { printf '\n== %s\n' "$*"; }
exists() { "$@" >/dev/null 2>&1; }

say "S3 bucket and probe.txt"
exists aws s3api head-bucket --bucket "$BUCKET" || aws s3api create-bucket --bucket "$BUCKET" >/dev/null
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging "TagSet=[{$TAG}]"
echo probe | aws s3 cp - "s3://$BUCKET/probe.txt" >/dev/null

say "DynamoDB table and one item"
if ! exists aws dynamodb describe-table --table-name outage-probe; then
  aws dynamodb create-table --table-name outage-probe --billing-mode PAY_PER_REQUEST \
    --attribute-definitions AttributeName=pk,AttributeType=S --key-schema AttributeName=pk,KeyType=HASH \
    --tags "$TAG" >/dev/null
  aws dynamodb wait table-exists --table-name outage-probe
fi
aws dynamodb put-item --table-name outage-probe --item '{"pk": {"S": "probe"}}'

say "Lambda execution role and hello function"
if ! exists aws iam get-role --role-name outage-probe-lambda; then
  aws iam create-role --role-name outage-probe-lambda --tags "$TAG" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name outage-probe-lambda \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "waiting 15 s for the new role to become usable"; sleep 15
fi
if ! exists aws lambda get-function --function-name outage-probe-hello; then
  tmp=$(mktemp -d)
  printf 'def handler(event, context):\n    return {"ok": True}\n' > "$tmp/hello.py"
  (cd "$tmp" && zip -q hello.zip hello.py)
  aws lambda create-function --function-name outage-probe-hello --runtime python3.12 --handler hello.handler \
    --role "arn:aws:iam::$ACCOUNT:role/outage-probe-lambda" --zip-file "fileb://$tmp/hello.zip" \
    --memory-size 128 --timeout 3 --tags project=outage-probe >/dev/null
  aws lambda wait function-active-v2 --function-name outage-probe-hello
fi

say "Probe user, limited to the five checks"
exists aws iam get-user --user-name outage-probe || aws iam create-user --user-name outage-probe --tags "$TAG" >/dev/null
cat > /tmp/probe-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "ReadProbeObject", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::$BUCKET/probe.txt"},
    {"Sid": "ReadProbeItem", "Effect": "Allow", "Action": "dynamodb:GetItem", "Resource": "arn:aws:dynamodb:us-east-1:$ACCOUNT:table/outage-probe"},
    {"Sid": "InvokeHello", "Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": "arn:aws:lambda:us-east-1:$ACCOUNT:function:outage-probe-hello"},
    {"Sid": "DescribeInstancesCannotBeScopedToAResource", "Effect": "Allow", "Action": "ec2:DescribeInstances", "Resource": "*",
     "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}}
  ]
}
EOF
aws iam put-user-policy --user-name outage-probe --policy-name probe-only --policy-document file:///tmp/probe-policy.json

say "Access key for the probe user"
if [ "${NO_KEY:-0}" = "1" ]; then
  echo "Skipped (NO_KEY=1). Create it in IAM -> Users -> outage-probe -> Security credentials -> Create access key."
else
n=$(aws iam list-access-keys --user-name outage-probe --query 'length(AccessKeyMetadata)' --output text)
if [ "$n" -ge 1 ]; then
  echo "The probe user already has $n access key(s); not creating another."
  echo "If you lost the secret, delete the old key in IAM -> Users -> outage-probe and run this again."
else
  aws iam create-access-key --user-name outage-probe \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text | {
      read -r id secret
      echo
      echo "Shown once. Put these in GitHub -> outage-telemetry -> Settings -> Secrets and variables -> Actions -> Secrets:"
      echo "  PROBE_AWS_ACCESS_KEY_ID      $id"
      echo "  PROBE_AWS_SECRET_ACCESS_KEY  $secret"
    }
fi
fi

say "Done. GitHub variable to set"
echo "  PROBE_BUCKET  $BUCKET"
echo
echo "Optional: a \$5 budget. Billing -> Budgets -> Create (monthly cost). Expected cost is cents a month."
