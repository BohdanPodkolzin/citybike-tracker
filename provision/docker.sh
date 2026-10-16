#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive


apt-get update && apt-get install -y --no-install-recommends docker.io ca-certificates curl


# Container logs rotate, so a long-running VM never fills its disk
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON

# Start Docker only when the network (our static LAN address) is up
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/network.conf <<'UNIT'
[Unit]
After=network-online.target
Wants=network-online.target
UNIT

systemctl daemon-reload
systemctl enable docker     
systemctl restart docker

usermod -aG docker vagrant 2>/dev/null || true

docker --version
