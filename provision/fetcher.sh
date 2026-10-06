#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
: "${PORT:?}" "${CITYBIKES_NETWORK_ID:?}"


apt-get update && apt-get install -y --no-install-recommends python3-venv curl
id -u fetcher >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin fetcher

python3 -m venv /opt/citybikes/venv
/opt/citybikes/venv/bin/pip install -q -r /opt/citybikes/app/requirements.txt

cat > /etc/fetcher.env <<ENV
PORT=${PORT}
CITYBIKES_NETWORK_ID=${CITYBIKES_NETWORK_ID}
ENV

cat > /etc/systemd/system/fetcher.service <<UNIT
[Unit]
Description=CityBikes Fetcher
After=network-online.target
Wants=network-online.target
# keep retrying forever, however many times it crashes
StartLimitIntervalSec=0

[Service]
User=fetcher
WorkingDirectory=/opt/citybikes/app
EnvironmentFile=/etc/fetcher.env
ExecStart=/opt/citybikes/venv/bin/gunicorn --bind 0.0.0.0:${PORT} app:app
# self-healing: restart 3 seconds after any exit or crash
Restart=always
RestartSec=3

[Install]
# start on boot
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable fetcher
systemctl restart fetcher

# fail loudly if it does not come up
curl -fsS --retry 15 --retry-connrefused --retry-delay 1 -o /dev/null "http://127.0.0.1:${PORT}/health" \
  || { journalctl -u fetcher -n 30 --no-pager; exit 1; }
echo "fetcher is up on port ${PORT}"