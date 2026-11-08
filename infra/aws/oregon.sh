#!/usr/bin/env bash
# Reference probe inside AWS: Lambda in us-west-2 (Oregon) checking us-east-1 every minute. Run in AWS CloudShell
# AFTER setup.sh, as an admin:
#
#   curl -sL https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/oregon.sh | bash
#
# Creates (tagged project=outage-probe, safe to re-run): results bucket outage-probe-ref-<account> in us-west-2,
# an Ed25519 signing key generated here and stored only in SSM Parameter Store, the Lambda outage-probe-reference with
# its role, a once-a-minute schedule, and read access for the outage-probe user so GitHub can copy the results.
# Prints the PUBLIC key at the end (safe to share; it goes in keys/aws.pub).
set -euo pipefail
export AWS_PAGER=""
REGION=us-west-2
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="outage-probe-ref-$ACCOUNT"
PROBE_BUCKET="outage-probe-$ACCOUNT"
PARAM=/outage-probe/signing-key-aws
FN=outage-probe-reference
ROLE=outage-probe-reference
TAG="Key=project,Value=outage-probe"
say() { printf '\n== %s\n' "$*"; }
exists() { "$@" >/dev/null 2>&1; }
work=$(mktemp -d); cd "$work"

say "Results bucket in $REGION"
exists aws s3api head-bucket --bucket "$BUCKET" || aws s3api create-bucket --bucket "$BUCKET" --region $REGION \
  --create-bucket-configuration LocationConstraint=$REGION >/dev/null
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging "TagSet=[{$TAG}]"

say "Signing key (made here, stored only in SSM)"
if exists aws ssm get-parameter --region $REGION --name "$PARAM"; then
  echo "Key already exists; keeping it."
  PUB=$(aws ssm get-parameter --region $REGION --name "$PARAM-public" --query Parameter.Value --output text)
else
  openssl genpkey -algorithm ed25519 -out key.pem 2>/dev/null
  SEED=$(openssl pkey -in key.pem -outform DER | tail -c 32 | base64)
  PUB=$(openssl pkey -in key.pem -pubout -outform DER | tail -c 32 | base64)
  aws ssm put-parameter --region $REGION --name "$PARAM" --type SecureString --value "$SEED" --tags "$TAG" >/dev/null
  aws ssm put-parameter --region $REGION --name "$PARAM-public" --type String --value "$PUB" --tags "$TAG" >/dev/null
  unset SEED; rm -f key.pem
fi

say "Lambda role"
if ! exists aws iam get-role --role-name $ROLE; then
  aws iam create-role --role-name $ROLE --tags "$TAG" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name $ROLE --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  NEW_ROLE=1
fi
cat > role.json <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::$PROBE_BUCKET/probe.txt"},
  {"Effect": "Allow", "Action": "dynamodb:GetItem", "Resource": "arn:aws:dynamodb:us-east-1:$ACCOUNT:table/outage-probe"},
  {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": "arn:aws:lambda:us-east-1:$ACCOUNT:function:outage-probe-hello"},
  {"Effect": "Allow", "Action": "ec2:DescribeInstances", "Resource": "*", "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}},
  {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": "arn:aws:s3:::$BUCKET/*"},
  {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::$BUCKET"},
  {"Effect": "Allow", "Action": "ssm:GetParameter", "Resource": "arn:aws:ssm:$REGION:$ACCOUNT:parameter$PARAM"}
]}
JSON
aws iam put-role-policy --role-name $ROLE --policy-name probe-reference --policy-document file://role.json
[ "${NEW_ROLE:-0}" = 1 ] && { echo "waiting 15 s for the new role"; sleep 15; }

say "Lambda package (probe code from GitHub + cryptography for Python 3.12)"
curl -sL https://github.com/ateeqkhan11/outage-telemetry/archive/refs/heads/main.tar.gz | tar xz
mkdir pkg
cp -R outage-telemetry-main/probe pkg/probe
cp outage-telemetry-main/aws_lambda/handler.py pkg/handler.py
pip3 install -q --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: \
  --target pkg "cryptography>=42" 2>&1 | grep -v "WARNING" || true
(cd pkg && zip -qr ../fn.zip .)
ENV="Variables={RESULTS_BUCKET=$BUCKET,KEY_PARAM=$PARAM,PROBE_BUCKET=$PROBE_BUCKET,PROBE_TABLE=outage-probe,PROBE_FUNCTION=outage-probe-hello,PROBE_ROUNDS=6}"
if exists aws lambda get-function --region $REGION --function-name $FN; then
  aws lambda update-function-code --region $REGION --function-name $FN --zip-file fileb://fn.zip >/dev/null
  aws lambda wait function-updated-v2 --region $REGION --function-name $FN
  aws lambda update-function-configuration --region $REGION --function-name $FN --environment "$ENV" --timeout 58 >/dev/null
  aws lambda wait function-updated-v2 --region $REGION --function-name $FN
else
  aws lambda create-function --region $REGION --function-name $FN --runtime python3.12 --handler handler.handler \
    --role "arn:aws:iam::$ACCOUNT:role/$ROLE" --zip-file fileb://fn.zip --memory-size 256 --timeout 58 \
    --environment "$ENV" --tags project=outage-probe >/dev/null
  aws lambda wait function-active-v2 --region $REGION --function-name $FN
fi
aws lambda put-function-concurrency --region $REGION --function-name $FN --reserved-concurrent-executions 1 >/dev/null 2>&1 \
  || echo "(This account can't reserve concurrency; the handler skips a minute it has already recorded, and the 58 s timeout ends each run before the next.)"

say "Test run (about a minute)"
aws lambda invoke --region $REGION --function-name $FN --cli-read-timeout 120 out.json >/dev/null && cat out.json; echo

say "Every-minute schedule"
RULE_ARN=$(aws events put-rule --region $REGION --name $FN-every-minute --schedule-expression "rate(1 minute)" --query RuleArn --output text)
exists aws lambda add-permission --region $REGION --function-name $FN --statement-id every-minute \
  --action lambda:InvokeFunction --principal events.amazonaws.com --source-arn "$RULE_ARN" || true
aws events put-targets --region $REGION --rule $FN-every-minute --targets "Id=1,Arn=arn:aws:lambda:$REGION:$ACCOUNT:function:$FN" >/dev/null

say "Read access for GitHub (the outage-probe user) to copy these results"
cat > read.json <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::$BUCKET"},
  {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::$BUCKET/*"}
]}
JSON
aws iam put-user-policy --user-name outage-probe --policy-name read-reference-results --policy-document file://read.json

say "Done"
echo "GitHub variable REF_BUCKET = $BUCKET"
echo "Public key for keys/aws.pub = $PUB"
