#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
: "${PORT:?}" "${DB_HOST:?}" "${DB_PORT:?}" "${DB_NAME:?}" "${DB_USER:?}" "${DB_PASSWORD:?}" "${FETCHER_URL:?}" "${POLL_INTERVAL:?}"

apt-get update && apt-get install -y --no-install-recommends python3-venv
id -u history >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin history

python3 -m venv /opt/citybikes/venv
/opt/citybikes/venv/bin/pip install -q -r /opt/citybikes/app/requirements.txt

# umask 077 = only root can read this file, because it holds the password.
(umask 077; cat > /etc/history.env <<ENV
PORT=${PORT}
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT}
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
FETCHER_URL=${FETCHER_URL}
POLL_INTERVAL=${POLL_INTERVAL}
ENV
)

cat > /etc/systemd/system/history.service <<UNIT
[Unit]
Description=CityBikes History
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User=history
WorkingDirectory=/opt/citybikes/app
EnvironmentFile=/etc/history.env
# ONE worker on purpose: the poller runs inside the process, so more workers
# would each poll and store duplicate snapshots. Threads serve the API.
ExecStart=/opt/citybikes/venv/bin/gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT} "app:create_app()"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable history
systemctl restart history

# fail loudly if it does not come up
curl -fsS --retry 15 --retry-connrefused --retry-delay 1 -o /dev/null "http://127.0.0.1:${PORT}/health" \
  || { journalctl -u history -n 30 --no-pager; exit 1; }
echo "history is up on port ${PORT}"