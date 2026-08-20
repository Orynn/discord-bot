#!/usr/bin/env bash
# Restart loop if you are not using the systemd user service.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Create the venv first: python -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

while true; do
  "$ROOT/.venv/bin/python" -u "$ROOT/main.py" && status=0 || status=$?
  echo "Arkann exited with ${status}; restarting in 5s." >&2
  sleep 5
done
