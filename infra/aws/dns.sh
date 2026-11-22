#!/usr/bin/env bash
# Move nimbusindex.com's DNS to AWS Route 53 and point app.nimbusindex.com at the app server.
# Only the DNS moves: the domain stays registered (and billed) at GoDaddy, so there is no transfer fee, no 60-day lock,
# and moving back is just switching the name servers again.
#
# Run in AWS CloudShell AFTER app.sh (it needs the app server's Elastic IP):
#   bash <(curl -sL https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/<commit>/infra/aws/dns.sh)
# Safe to run again.
#
# It copies the records the domain has today, so nothing visible changes when the name servers switch:
#   nimbusindex.com      A      172.66.0.70  (the current site, on Carrd; replaced later by the real landing page)
#   www.nimbusindex.com  CNAME  nimbusindex.com
# and adds
#   app.nimbusindex.com  A      <app server's Elastic IP>
# Before switching name servers, open GoDaddy -> nimbusindex.com -> DNS and check there is nothing else worth keeping
# (email MX, TXT verification records). Add any with ROOT_A=... or by hand in Route 53. getnimbusindex.com (Mike's
# Google email) is a different domain and is not touched.
set -euo pipefail
export AWS_PAGER=""
DOMAIN=${DOMAIN:-nimbusindex.com}
APP_HOST=${APP_HOST:-app.$DOMAIN}
ROOT_A=${ROOT_A:-172.66.0.70}
TTL=${TTL:-300}
IP=${APP_IP:-$(aws ec2 describe-addresses --region us-west-2 --filters Name=tag:project,Values=nimbus-app \
                 --query 'Addresses[0].PublicIp' --output text)}
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "No app server address found. Run app.sh first (or set APP_IP)."; exit 1; }

ZONE=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN." \
        --query "HostedZones[?Name=='$DOMAIN.' && Config.PrivateZone==\`false\`].Id | [0]" --output text)
if [ "$ZONE" = "None" ] || [ -z "$ZONE" ]; then
  ZONE=$(aws route53 create-hosted-zone --name "$DOMAIN" --caller-reference "nimbus-$(date +%s)" \
          --hosted-zone-config Comment="Nimbus Index (DNS only; registrar is GoDaddy)" --query HostedZone.Id --output text)
  echo "Created hosted zone $ZONE (\$0.50/month)"
fi
ZONE=${ZONE#/hostedzone/}
aws route53 change-tags-for-resource --resource-type hostedzone --resource-id "$ZONE" --add-tags Key=project,Value=nimbus-app

rec() { printf '{"Action":"UPSERT","ResourceRecordSet":{"Name":"%s","Type":"%s","TTL":%s,"ResourceRecords":[{"Value":"%s"}]}}' "$1" "$2" "$TTL" "$3"; }
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch "{\"Comment\":\"Nimbus Index\",\"Changes\":[
  $(rec "$DOMAIN" A "$ROOT_A"), $(rec "www.$DOMAIN" CNAME "$DOMAIN"), $(rec "$APP_HOST" A "$IP")]}" >/dev/null

echo
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE" \
  --query 'ResourceRecordSets[].[Name,Type,join(`, `,ResourceRecords[].Value)]' --output table
echo
echo "Last step, at GoDaddy: My Products -> nimbusindex.com -> DNS -> Nameservers -> Change -> 'I'll use my own',"
echo "and enter these four (replacing ns11/ns12.domaincontrol.com):"
aws route53 get-hosted-zone --id "$ZONE" --query 'DelegationSet.NameServers' --output text | tr '\t' '\n' | sed 's/^/    /'
echo
echo "It usually takes effect within an hour (up to 48 h). Check with:  dig +short NS $DOMAIN   and   dig +short $APP_HOST"
echo "Once $APP_HOST shows $IP, run:  DOMAIN=$APP_HOST bash app_domain.sh"
