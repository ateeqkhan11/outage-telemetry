# Shared helper: run a shell command on the app server through AWS Systems Manager and print its output.
ssm_run() {
  local IID CID STATUS
  IID=$(aws ec2 describe-instances --region us-west-2 --filters Name=tag:Name,Values=nimbus-app Name=instance-state-name,Values=running \
        --query 'Reservations[0].Instances[0].InstanceId' --output text)
  [ "$IID" != "None" ] || { echo "The nimbus-app server isn't running."; return 1; }
  CID=$(aws ssm send-command --region us-west-2 --instance-ids "$IID" --document-name AWS-RunShellScript \
        --parameters "$(python3 -c 'import json,sys;print(json.dumps({"commands":[sys.argv[1]]}))' "$1")" \
        --query Command.CommandId --output text)
  for _ in $(seq 1 60); do
    STATUS=$(aws ssm get-command-invocation --region us-west-2 --command-id "$CID" --instance-id "$IID" --query Status --output text 2>/dev/null || echo Pending)
    case "$STATUS" in Success|Failed|Cancelled|TimedOut) break ;; esac
    sleep 3
  done
  aws ssm get-command-invocation --region us-west-2 --command-id "$CID" --instance-id "$IID" --query StandardOutputContent --output text
  [ "$STATUS" = "Success" ] || { echo "($STATUS)"; aws ssm get-command-invocation --region us-west-2 --command-id "$CID" --instance-id "$IID" --query StandardErrorContent --output text; return 1; }
}
