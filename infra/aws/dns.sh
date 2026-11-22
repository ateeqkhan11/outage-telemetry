#!/usr/bin/env bash
# Move the DNS for nimbusindex.com and getnimbusindex.com to AWS Route 53, and point the website and app at the server.
# Only the DNS moves: both domains stay registered (and billed) at GoDaddy, so there is no transfer fee, no 60-day lock,
# and moving back is just switching the name servers again. Each hosted zone costs $0.50 a month.
#
# Run in AWS CloudShell after app.sh (without the app server it keeps today's website addresses):
#   bash <(curl -sL https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/<commit>/infra/aws/dns.sh)
# Safe to run again. DOMAINS='nimbusindex.com' limits it to one domain.
#
# nimbusindex.com      @ A -> app server (website)   www CNAME -> @   app A -> app server   _dmarc TXT (as at GoDaddy)
# getnimbusindex.com   @ A -> app server (redirects to nimbusindex.com)   www CNAME -> @
#                      and its Google Workspace email records, copied exactly: MX, SPF, site verification, DKIM, DMARC.
#                      Mike's cold email goes out from this domain, so check every record (step printed at the end)
#                      BEFORE switching its name servers at GoDaddy.
set -euo pipefail
export AWS_PAGER=""
DOMAINS=${DOMAINS:-"nimbusindex.com getnimbusindex.com"}
TTL=${TTL:-300}
IP=${APP_IP:-$(aws ec2 describe-addresses --region us-west-2 --filters Name=tag:project,Values=nimbus-app \
                 --query 'Addresses[0].PublicIp' --output text 2>/dev/null || echo None)}
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { IP=""; echo "No app server address yet: keeping today's website addresses (rerun after app.sh)."; }

zone_id() {
  local z
  z=$(aws route53 list-hosted-zones-by-name --dns-name "$1." \
       --query "HostedZones[?Name=='$1.' && Config.PrivateZone==\`false\`].Id | [0]" --output text)
  if [ "$z" = "None" ] || [ -z "$z" ]; then
    z=$(aws route53 create-hosted-zone --name "$1" --caller-reference "nimbus-$1-$(date +%s)" \
         --hosted-zone-config Comment="Nimbus Index (DNS only; registrar is GoDaddy)" --query HostedZone.Id --output text)
    echo "Created hosted zone for $1" >&2
  fi
  z=${z#/hostedzone/}
  aws route53 change-tags-for-resource --resource-type hostedzone --resource-id "$z" --add-tags Key=project,Value=nimbus-app
  echo "$z"
}

# records as lines: name|type|value[|value...]; TXT values are written exactly as Route 53 wants them (quoted)
records() {
  case "$1" in
    nimbusindex.com) cat <<EOF
nimbusindex.com|A|${IP:-172.66.0.70}
www.nimbusindex.com|CNAME|nimbusindex.com
_dmarc.nimbusindex.com|TXT|"v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;"
EOF
      [ -n "$IP" ] && echo "app.nimbusindex.com|A|$IP"
      ;;
    getnimbusindex.com) cat <<'EOF'
getnimbusindex.com|MX|1 smtp.google.com.
getnimbusindex.com|TXT|"v=spf1 include:_spf.google.com ~all"|"google-site-verification=7zHfZtniEFoREFbYz1qI23ECinTMzjNIgpBaxoGiB-g"
www.getnimbusindex.com|CNAME|getnimbusindex.com
_dmarc.getnimbusindex.com|TXT|"v=DMARC1; p=none; rua=mailto:michael@getnimbusindex.com"
dc-bdaca08905._spfm.getnimbusindex.com|TXT|"v=spf1 include:_spf.google.com ~all"
google._domainkey.getnimbusindex.com|TXT|"v=DKIM1;k=rsa;p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4oXOfXWrjTzhV3pXbqjXCuqpfMAWs+8fEFF5U+3QDw6JmWQf8Pnm0rgCvCzarbTYljf6wxRGnCm6ww4pW5BFdwUBKKhVHEpgMs+tCpug6aDrPIfAB0C8+wBrSej9Gg2eWXssOvxwfhF03uaOehIxUeNnKGSsIlw5oMCrwk81YgINhEnQS3HCz3Jx1fZLGUmswnq" "e22X63YwvD0L0eaejrgM9ZqYBnhgo1A0CtwZPh5MKUlZIR/elkg7/ZivgJ3BP/vD9gSo6YhKsQYW6AamKI0SpoXNG4JETuMMa6McDic0m4h+tFOu1WItIL/2OVOidS1NEx99HatICc+3MFK5ldQIDAQAB"
EOF
      if [ -n "$IP" ]; then echo "getnimbusindex.com|A|$IP"            # our server redirects it to nimbusindex.com
      else echo "getnimbusindex.com|A|15.197.225.128|3.33.251.168"; fi  # GoDaddy's forwarding, as today
      ;;
    *) echo "No record list for $1" >&2; return 1 ;;
  esac
}

for d in $DOMAINS; do
  echo; echo "== $d"
  z=$(zone_id "$d")
  records "$d" | python3 -c '
import json, sys
ttl = int(sys.argv[1]); changes = []
for line in sys.stdin.read().splitlines():
    name, typ, *vals = line.split("|")
    changes.append({"Action": "UPSERT", "ResourceRecordSet": {"Name": name, "Type": typ, "TTL": ttl,
                    "ResourceRecords": [{"Value": v} for v in vals]}})
print(json.dumps({"Comment": "Nimbus Index", "Changes": changes}))' "$TTL" > /tmp/nimbus-dns.json
  aws route53 change-resource-record-sets --hosted-zone-id "$z" --change-batch file:///tmp/nimbus-dns.json >/dev/null
  aws route53 list-resource-record-sets --hosted-zone-id "$z" \
    --query 'ResourceRecordSets[?Type!=`SOA`].[Name,Type,join(`, `,ResourceRecords[].Value)]' --output text | cut -c1-110
  echo "Name servers for $d (enter these at GoDaddy, replacing the domaincontrol.com ones):"
  aws route53 get-hosted-zone --id "$z" --query 'DelegationSet.NameServers' --output text | tr '\t' '\n' | sed 's/^/    /'
done
echo
echo "Before switching name servers, check Route 53 gives the same answers as GoDaddy, for example:"
echo "  dig +short TXT google._domainkey.getnimbusindex.com @<one of the name servers above>"
echo "Then at GoDaddy: Domain -> DNS -> Nameservers -> Change -> 'I'll use my own'. Then: bash app_domain.sh"
