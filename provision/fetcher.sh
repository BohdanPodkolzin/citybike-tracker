#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

: "${REDIS_HOST:?}" "${REDIS_PORT:?}" "${REDIS_PASSWORD:?}" "${CITYBIKES_NETWORK_ID:?}"


apt-get update && apt-get install -y --no-install-recommends python3-venv
id -u fetcher >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin fetcher

python3 -m venv /opt/citybikes/venv
/opt/citybikes/venv/bin/pip install -q -r /opt/citybikes/app/requirements.txt

# umask 077 = only root can read this file, because it holds the password.
(umask 077; cat > /etc/fetcher.env <<ENV
REDIS_HOST=${REDIS_HOST}
REDIS_PORT=${REDIS_PORT}
REDIS_PASSWORD=${REDIS_PASSWORD}
CITYBIKES_NETWORK_ID=${CITYBIKES_NETWORK_ID}
ENV
)

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
ExecStart=/opt/citybikes/venv/bin/python worker.py
# self-healing: restart 3 seconds after any exit or crash
Restart=always
RestartSec=3

[Install]
# start on boot
WantedBy=multi-user.target
UNIT

# try to reach redis from this VM with this passw
/opt/citybikes/venv/bin/python -c "
import os, redis
redis.Redis(host=os.environ['REDIS_HOST'], port=int(os.environ['REDIS_PORT']),
            password=os.environ['REDIS_PASSWORD'], socket_connect_timeout=3).ping()
print('redis reachable')"

systemctl daemon-reload
systemctl enable fetcher
systemctl restart fetcher

#  fetcher working on;y with redis broker and do not open the ports; check the status in systemd
sleep 5
systemctl is-active --quiet fetcher || { journalctl -u fetcher -n 30 --no-pager; exit 1; }
echo "fetcher is up and waiting for requests"
