#!/usr/bin/env bash
# Install CPU diffusion deps and enable the local image worker.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Create the venv first: python -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements-image.txt"
mkdir -p "$ROOT/data/hf-cache"

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
sed "s|@ROOT@|${ROOT}|g" "$ROOT/deploy/arkann-image.service" > "$UNIT_DIR/arkann-image.service"
systemctl --user daemon-reload
systemctl --user enable --now arkann-image.service

echo "Image worker: systemctl --user status arkann-image.service"
echo "First start downloads the model into $ROOT/data/hf-cache (a few GB)."
echo "Until it is ready, ;image falls back to Pollinations (image_provider=auto)."
