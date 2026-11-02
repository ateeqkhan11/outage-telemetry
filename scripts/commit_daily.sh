#!/usr/bin/env bash
# Commit built daily folders to the `data` branch (created on first use). Usage: commit_daily.sh <folder of YYYY-MM-DD dirs>
set -euo pipefail
src="$1"
git config user.name "outage-telemetry bot"
git config user.email "actions@users.noreply.github.com"
if git ls-remote --exit-code --heads origin data >/dev/null; then
  git fetch --depth 1 origin data
  git worktree add /tmp/data origin/data -B data
else
  git worktree add --orphan -b data /tmp/data
fi
mkdir -p /tmp/data/daily
cp -R "$src"/. /tmp/data/daily/
cd /tmp/data
git add daily
if git diff --cached --quiet; then echo "nothing new"; exit 0; fi
days=$(ls "$src" | tr '\n' ' ')
git commit -m "Daily signed results: ${days}"
git push origin data
