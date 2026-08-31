#!/usr/bin/env bash
# Run discord-bot tests on agent stop; loop once if they fail.
set -euo pipefail

input=$(cat)
loop_count=$(echo "$input" | jq -r '.loop_count // 0')

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ ! -f "$repo_root/main.py" || ! -d "$repo_root/tests" ]]; then
  exit 0
fi

cd "$repo_root"

if [[ -x "$repo_root/.venv/bin/python" ]]; then
  py="$repo_root/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  py="python3"
else
  exit 0
fi

export DISCORD_TOKEN="${DISCORD_TOKEN:-ci-test-token}"

if "$py" -m unittest discover -s tests -v >/tmp/arkann-test.log 2>&1; then
  exit 0
fi

if [[ "$loop_count" -ge 1 ]]; then
  exit 0
fi

summary=$(tail -n 20 /tmp/arkann-test.log | sed 's/"/\\"/g')
jq -n \
  --arg summary "$summary" \
  '{
    followup_message: ("discord-bot tests failed. Fix the failures, then rerun: python -m unittest discover -s tests -v\n\nRecent output:\n" + $summary)
  }'
exit 0
