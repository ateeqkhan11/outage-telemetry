#!/usr/bin/env bash
# Use the `data` branch as storage.
#   data_branch.sh open <dir>             check out the data branch into <dir> (created on first use)
#   data_branch.sh save <dir> <message>   commit everything in <dir> and push, retrying if the branch moved
set -euo pipefail
cmd="$1"; dir="$2"
git config --global user.name "outage-telemetry bot"
git config --global user.email "actions@users.noreply.github.com"
if [ "$cmd" = open ]; then
  if git ls-remote --exit-code --heads origin data >/dev/null 2>&1; then
    git fetch --depth 1 origin data
    git worktree add "$dir" FETCH_HEAD -B data
  else
    git worktree add --orphan -b data "$dir"
  fi
elif [ "$cmd" = save ]; then
  cd "$dir"
  git add -A
  if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
  git commit -q -m "$3"
  for i in 1 2 3 4 5; do
    if git push -q origin HEAD:data; then echo "pushed"; exit 0; fi
    echo "push rejected, rebasing (try $i)"; git pull -q --rebase --depth 50 origin data || git rebase --abort || true; sleep $((i * 3))
  done
  echo "could not push"; exit 1
fi
