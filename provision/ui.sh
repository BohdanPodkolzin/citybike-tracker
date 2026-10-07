#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

: "${HISTORY_URL:?}"

curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get update && apt-get install -y nodejs

id -u ui >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin ui

cd /opt/citybikes/app
npm install --no-audit --no-fund
npm run build

cat > /etc/systemd/system/ui.service <<UNIT
[Unit]
Description=CityBikes UI (Vite preview server)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User=ui
WorkingDirectory=/opt/citybikes/app
# the only setting it needs: where History is
Environment=HISTORY_URL=${HISTORY_URL}
# lets a non-root user listen on port 80
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/usr/bin/node node_modules/vite/bin/vite.js preview --configLoader native --host 0.0.0.0 --port 80 --strictPort
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable ui
systemctl restart ui

curl -fsS --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1/ \
  || { journalctl -u ui -n 30 --no-pager; exit 1; }
echo "ui is up on port 80"