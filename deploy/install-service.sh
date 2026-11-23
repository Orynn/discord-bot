#!/usr/bin/env bash
# Install user systemd units: auto-restart the bot and back up arkann.db daily.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

render() {
  local src="$1" dest="$2"
  sed "s|@ROOT@|${ROOT}|g" "$src" > "$dest"
}

render "$ROOT/deploy/arkann.service" "$UNIT_DIR/arkann.service"
render "$ROOT/deploy/arkann-backup.service" "$UNIT_DIR/arkann-backup.service"
cp "$ROOT/deploy/arkann-backup.timer" "$UNIT_DIR/arkann-backup.timer"

systemctl --user daemon-reload
if command -v loginctl >/dev/null 2>&1; then
  loginctl enable-linger "$(id -un)" >/dev/null 2>&1 || true
fi
systemctl --user enable --now arkann.service
systemctl --user enable --now arkann-backup.timer
systemctl --user start arkann-backup.service

echo "Arkann service: systemctl --user status arkann.service"
echo "Backups:        $ROOT/data/backups/"
