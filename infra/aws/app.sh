#!/bin/bash
# Nimbus Index app server in AWS Oregon (us-west-2), never us-east-1: the app must stay up during the outages it reports.
# Run in AWS CloudShell:   bash <(curl -sL https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/<commit>/infra/aws/app.sh)
# Safe to run again: it reuses whatever already exists.
#
# Creates (all tagged project=nimbus-app):
#   - an Elastic IP, so the address never changes (point app.nimbusindex.com at it later)
#   - a t4g.small Amazon Linux 2023 server: Caddy (HTTPS) -> gunicorn -> the Flask app, SQLite on its disk
#   - an IAM role: AWS Systems Manager access (no SSH, no open port 22) and write access to the backup bucket only
#   - a security group with ports 80 and 443 open
#   - an S3 bucket for nightly database backups (kept 90 days)
# Until DNS is set up the app is served at https://<ip-with-dashes>.sslip.io with a real certificate.
# Later: DOMAIN=app.nimbusindex.com bash app_domain.sh
set -euo pipefail
REGION=us-west-2
export AWS_DEFAULT_REGION=$REGION
NAME=nimbus-app
REPO=https://github.com/ateeqkhan11/outage-telemetry.git
ACCT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=nimbus-app-backups-$ACCT
TAGS="ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=project,Value=nimbus-app}]"
echo "Account $ACCT, region $REGION"

# --- backup bucket -----------------------------------------------------------------------------------------------
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint=$REGION >/dev/null
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
    '{"Rules":[{"ID":"expire-90d","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":90}}]}'
  aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=project,Value=nimbus-app}]'
  echo "Created backup bucket $BUCKET"
fi

# --- IAM role and instance profile -------------------------------------------------------------------------------
if ! aws iam get-role --role-name $NAME >/dev/null 2>&1; then
  aws iam create-role --role-name $NAME --tags Key=project,Value=nimbus-app --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name $NAME --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  echo "Created role $NAME"
fi
aws iam put-role-policy --role-name $NAME --policy-name backups-only --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
  {\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\"],\"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}"
if ! aws iam get-instance-profile --instance-profile-name $NAME >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name $NAME >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name $NAME --role-name $NAME
  echo "Created instance profile; waiting for IAM to catch up"; sleep 15
fi

# --- network -----------------------------------------------------------------------------------------------------
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=$NAME Name=vpc-id,Values=$VPC --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name $NAME --description "Nimbus Index app: HTTP and HTTPS only" --vpc-id $VPC \
       --tag-specifications "ResourceType=security-group,Tags=[{Key=project,Value=nimbus-app}]" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions \
    'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]' \
    'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]' >/dev/null
  echo "Created security group $SG"
fi
ALLOC=$(aws ec2 describe-addresses --filters Name=tag:project,Values=nimbus-app --query 'Addresses[0].AllocationId' --output text)
if [ "$ALLOC" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc --tag-specifications \
          "ResourceType=elastic-ip,Tags=[{Key=project,Value=nimbus-app},{Key=Name,Value=$NAME}]" --query AllocationId --output text)
fi
IP=$(aws ec2 describe-addresses --allocation-ids $ALLOC --query 'Addresses[0].PublicIp' --output text)
HOST="${IP//./-}.sslip.io"
echo "Address $IP  ->  https://$HOST"

# --- server ------------------------------------------------------------------------------------------------------
IID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$NAME Name=instance-state-name,Values=pending,running,stopping,stopped \
      --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$IID" = "None" ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 --query Parameter.Value --output text)
  UD=$(mktemp)
  cat > "$UD" <<USERDATA
#!/bin/bash
set -euxo pipefail
HOST="$HOST"
BUCKET="$BUCKET"
REPO="$REPO"
dnf install -y python3.11 python3.11-pip git tar
id nimbus >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/nimbus --shell /sbin/nologin nimbus
mkdir -p /var/lib/nimbus /etc/nimbus && chown nimbus:nimbus /var/lib/nimbus && chmod 750 /var/lib/nimbus
[ -d /opt/nimbus/src ] || runuser -u nimbus -- git clone --depth 1 --branch main "\$REPO" /opt/nimbus/src
[ -d /opt/nimbus/venv ] || runuser -u nimbus -- python3.11 -m venv /opt/nimbus/venv
runuser -u nimbus -- /opt/nimbus/venv/bin/pip install --quiet -r /opt/nimbus/src/app/requirements.txt
if [ ! -f /etc/nimbus/env ]; then
  umask 077
  cat > /etc/nimbus/env <<ENV
NIMBUS_SECRET_KEY=\$(openssl rand -hex 32)
NIMBUS_INSTANCE=/var/lib/nimbus
NIMBUS_DB=/var/lib/nimbus/nimbus.db
NIMBUS_DATA=/var/lib/nimbus/data
NIMBUS_REPO=/opt/nimbus/src
NIMBUS_BASE_URL=https://\$HOST
NIMBUS_BEHIND_PROXY=1
NIMBUS_SECURE_COOKIES=1
NIMBUS_BACKUP_BUCKET=\$BUCKET
PYTHONPATH=/opt/nimbus/src:/opt/nimbus/src/app
ENV
  chgrp nimbus /etc/nimbus/env && chmod 640 /etc/nimbus/env
fi
cat > /usr/local/bin/nimbus-manage <<'SH'
#!/bin/sh
# Run the app's command line as the nimbus user with the app's settings. Example: nimbus-manage invite you@example.com --admin
set -a; . /etc/nimbus/env; set +a
cd /opt/nimbus/src/app
exec runuser -u nimbus -- /opt/nimbus/venv/bin/python -m nimbus_app.manage "\$@"
SH
cat > /usr/local/bin/nimbus-backup <<'SH'
#!/bin/sh
set -e
. /etc/nimbus/env
nimbus-manage backup /var/lib/nimbus/backup.db
aws s3 cp --only-show-errors /var/lib/nimbus/backup.db "s3://\$NIMBUS_BACKUP_BUCKET/db/\$(date -u +%F).db"
SH
chmod 755 /usr/local/bin/nimbus-manage /usr/local/bin/nimbus-backup

cat > /etc/systemd/system/nimbus-app.service <<'UNIT'
[Unit]
Description=Nimbus Index app (gunicorn)
After=network-online.target
[Service]
User=nimbus
EnvironmentFile=/etc/nimbus/env
WorkingDirectory=/opt/nimbus/src/app
ExecStart=/opt/nimbus/venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 3 --timeout 60 --access-logfile - nimbus_app.wsgi:app
Restart=always
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/nimbus
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/nimbus-sync.service <<'UNIT'
[Unit]
Description=Copy the latest signed data into the app
[Service]
Type=oneshot
ExecStart=/usr/local/bin/nimbus-manage sync
UNIT
cat > /etc/systemd/system/nimbus-sync.timer <<'UNIT'
[Unit]
Description=Copy the latest signed data every 2 minutes
[Timer]
OnBootSec=30
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
UNIT
cat > /etc/systemd/system/nimbus-backup.service <<'UNIT'
[Unit]
Description=Back up the app database to S3
[Service]
Type=oneshot
ExecStart=/usr/local/bin/nimbus-backup
UNIT
cat > /etc/systemd/system/nimbus-backup.timer <<'UNIT'
[Unit]
Description=Nightly database backup
[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT

# Caddy: HTTPS with automatic certificates (pinned release, checksum verified)
if [ ! -x /usr/local/bin/caddy ]; then
  V=2.8.4
  cd /tmp
  curl -fsSLO "https://github.com/caddyserver/caddy/releases/download/v\$V/caddy_\${V}_linux_arm64.tar.gz"
  curl -fsSLO "https://github.com/caddyserver/caddy/releases/download/v\$V/caddy_\${V}_checksums.txt"
  grep " caddy_\${V}_linux_arm64.tar.gz\$" caddy_\${V}_checksums.txt | sha512sum -c -
  tar -xzf caddy_\${V}_linux_arm64.tar.gz caddy && install -m 755 caddy /usr/local/bin/caddy
  id caddy >/dev/null 2>&1 || useradd --system --home-dir /var/lib/caddy --create-home --shell /sbin/nologin caddy
fi
mkdir -p /etc/caddy
[ -f /etc/caddy/Caddyfile ] || cat > /etc/caddy/Caddyfile <<CADDY
\$HOST {
	encode gzip
	reverse_proxy 127.0.0.1:8000
}
CADDY
cat > /etc/systemd/system/caddy.service <<'UNIT'
[Unit]
Description=Caddy (HTTPS in front of the Nimbus Index app)
After=network-online.target
[Service]
User=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
/usr/local/bin/nimbus-manage sync || true
systemctl enable --now nimbus-app nimbus-sync.timer nimbus-backup.timer caddy
USERDATA
  SUBNET=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC Name=default-for-az,Values=true --query 'Subnets[0].SubnetId' --output text)
  IID=$(aws ec2 run-instances --image-id $AMI --instance-type t4g.small --subnet-id $SUBNET --security-group-ids $SG \
        --iam-instance-profile Name=$NAME --user-data file://$UD --metadata-options HttpTokens=required,HttpEndpoint=enabled \
        --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3,Encrypted=true}' \
        --tag-specifications "$TAGS" "ResourceType=volume,Tags=[{Key=project,Value=nimbus-app}]" \
        --query 'Instances[0].InstanceId' --output text)
  rm -f "$UD"
  echo "Started server $IID; waiting for it to run"
  aws ec2 wait instance-running --instance-ids $IID
fi
aws ec2 associate-address --allocation-id $ALLOC --instance-id $IID >/dev/null
echo
echo "Server $IID is starting at https://$HOST"
echo "It takes about 5 minutes to install and copy the data. Then make your admin invite with:"
echo "  bash app_admin.sh you@example.com"
