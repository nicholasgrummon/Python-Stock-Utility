#!/usr/bin/env bash
# Install Python Stock Utility as a systemd user service so it survives
# terminal closes and restarts automatically on failure or reboot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR"
cp "$SCRIPT_DIR/psu.service" "$UNIT_DIR/psu.service"

systemctl --user daemon-reload
systemctl --user enable --now psu.service

cat <<EOF
Installed and started psu.service.

  Status:  systemctl --user status psu.service
  Logs:    journalctl --user -u psu.service -f
  Stop:    systemctl --user stop psu.service
  Restart: systemctl --user restart psu.service

To keep the service running after you log out (e.g. on a headless server),
enable lingering for your user:
  loginctl enable-linger $USER
EOF
