# AWS probe account setup (Sprint 1, steps 1–2)

Everything here lives in a **new AWS account used only for probing**. Nothing in it touches an employer's or a personal
account. Cost should be close to $0 a month.

## 1. The account

1. Create the account, then sign in as the root user and turn on **MFA** (IAM → Security credentials).
2. Billing → Budgets: create a **$5 monthly cost budget** that emails you at 80% and 100%.
3. Don't use root again after this. Create an admin IAM user for yourself, with MFA, and use that for the steps below.

## 2. The five test resources (us-east-1)

Run these with the AWS CLI, signed in as your admin user. Pick a globally unique bucket name and replace
`REPLACE-probe-bucket-name` everywhere, including `probe-policy.json` and `workers/wrangler.toml`.

```bash
export AWS_REGION=us-east-1
BUCKET=REPLACE-probe-bucket-name
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

# S3: one tiny file
aws s3api create-bucket --bucket "$BUCKET"
echo "probe" > probe.txt && aws s3 cp probe.txt "s3://$BUCKET/probe.txt"

# DynamoDB: on-demand table with one item
aws dynamodb create-table --table-name outage-probe --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=pk,AttributeType=S --key-schema AttributeName=pk,KeyType=HASH
aws dynamodb wait table-exists --table-name outage-probe
aws dynamodb put-item --table-name outage-probe --item '{"pk": {"S": "probe"}}'

# Lambda: a do-nothing function (needs an execution role)
aws iam create-role --role-name outage-probe-lambda --assume-role-policy-document \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name outage-probe-lambda \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
printf 'def handler(event, context):\n    return {"ok": True}\n' > hello.py && zip -q hello.zip hello.py
sleep 10   # give the new role a moment to become usable
aws lambda create-function --function-name outage-probe-hello --runtime python3.12 --handler hello.handler \
  --role "arn:aws:iam::$ACCOUNT:role/outage-probe-lambda" --zip-file fileb://hello.zip --memory-size 128 --timeout 3

# EC2 and STS: nothing to create. DescribeInstances works on an empty account, and GetCallerIdentity needs no permission.
```

## 3. The probe user

```bash
sed -e "s/REPLACE_ACCOUNT_ID/$ACCOUNT/g" -e "s/REPLACE-probe-bucket-name/$BUCKET/g" probe-policy.json > /tmp/policy.json
aws iam create-user --user-name outage-probe
aws iam put-user-policy --user-name outage-probe --policy-name probe-only --policy-document file:///tmp/policy.json
aws iam create-access-key --user-name outage-probe     # shown once: put it straight into the secrets below
```

The policy allows exactly the five checks and nothing else:
- S3 `GetObject` on the one file;
- DynamoDB `GetItem` on the one table;
- Lambda `InvokeFunction` on the one function;
- EC2 `DescribeInstances`, limited to us-east-1, because AWS doesn't allow narrowing it to a resource;
- STS `GetCallerIdentity`, which never needs permission.

Store the keys as **secrets only**: GitHub (`PROBE_AWS_ACCESS_KEY_ID`, `PROBE_AWS_SECRET_ACCESS_KEY`), Azure app
settings, and `wrangler secret put` for the Worker. Never put them in the repo or a local `.env` you might commit.
Using one probe user for all networks is fine. Give each network its own key pair if you want to be able to cut off
one network without affecting the others.

## Rough monthly cost

Per network, about 43,000 calls a month to each service:

| Service | Cost |
|---|---|
| Lambda invocations | Within the always-free allowance |
| S3 GETs | About $0.02 |
| DynamoDB on-demand reads | A few cents |
| EC2 and STS calls | Free |
