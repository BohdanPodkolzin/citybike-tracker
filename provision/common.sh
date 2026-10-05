#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

: "${VM_IP:?VM_IP is required}"

if ! ip -4 -o addr show | grep -qF " ${VM_IP}/"; then
  echo "ERROR: expected address ${VM_IP} is not configured on this VM." >&2
  echo "Addresses it has right now:" >&2
  ip -4 -br addr >&2
  echo "If this VM was created earlier with another network setup: vagrant destroy -f <name>, then vagrant up." >&2
  exit 1
fi

timedatectl set-timezone UTC
apt-get update -y
apt-get install -y --no-install-recommends curl ca-certificates python3
 
echo "==> $(hostname) is at ${VM_IP}"
