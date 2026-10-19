#!/usr/bin/env bash

set -euo pipefail

mkdir -p /var/log/journal /etc/systemd/journald.conf.d

cat > /etc/systemd/journald.conf.d/10-citybikes.conf <<'CONF'
[Journal]
Storage=persistent
SystemMaxUse=200M
CONF

systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald
journalctl --flush || true
echo "journal: persistent, max 200M"
