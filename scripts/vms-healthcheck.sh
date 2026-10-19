#!/usr/bin/env bash

set -uo pipefail

VHOST="${RABBITMQ_VHOST:-citybikes}"
EXPECT_QUEUE="${QUEUE_BACKEND:-rabbitmq}"
VMS="db fetcher history ui"
fails=0
ok()   { printf '  OK    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fails=$((fails + 1)); }
remote() { local vm="$1"; shift; ssh -o BatchMode=yes -o ConnectTimeout=8 "$vm" "$@" 2>/dev/null; }

echo "== 1. ssh from the bastion"
for vm in ${VMS}; do
  if [ "$(remote "$vm" hostname)" = "citybikes-${vm}" ]; then ok "ssh ${vm}"; else bad "ssh ${vm} (no answer: key, network or ufw?)"; fi
done

echo "== 2. containers (Up and healthy)"
for vm in ${VMS} bastion; do
  if [ "$vm" = bastion ]; then out=$(docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null)
  else out=$(remote "$vm" "docker ps -a --format '{{.Names}}|{{.Status}}'"); fi
  [ -n "$out" ] || { bad "${vm}: no containers listed"; continue; }
  while IFS='|' read -r name status; do
    case "$status" in
      Up*"(healthy)"*) ok "${vm}/${name}: ${status}" ;;
      *)               bad "${vm}/${name}: ${status}" ;;
    esac
  done <<< "$out"
done

echo "== 3. RabbitMQ (queue backend = ${EXPECT_QUEUE})"
if [ "$EXPECT_QUEUE" = rabbitmq ]; then
  q=$(remote db "docker exec rabbitmq rabbitmqctl -q list_queues -p ${VHOST} name consumers messages")
  if grep -q '^fetch.requests' <<< "$q"; then
    consumers=$(awk '$1=="fetch.requests"{print $2}' <<< "$q")
    if [ "${consumers:-0}" -ge 1 ]; then ok "queue fetch.requests, consumers=${consumers} (the fetcher is connected)"
    else bad "queue fetch.requests has no consumer (fetcher not connected)"; fi
  else bad "queue fetch.requests not found in vhost ${VHOST}: ${q:-no answer}"; fi
else
  echo "  skipped (QUEUE_BACKEND=${EXPECT_QUEUE})"
fi

echo "== 4. active backends reported by History"
st=$(remote history "curl -s localhost:8002/api/status")
if [ -n "$st" ]; then
  printf '  %s\n' "$st"
  grep -q "\"queue_backend\": *\"${EXPECT_QUEUE}\"" <<< "$st" && ok "queue_backend=${EXPECT_QUEUE}" || bad "queue_backend is not ${EXPECT_QUEUE}"
else bad "History /api/status gave no answer"; fi

echo "== 5. logs in Loki"
if [ "$(remote db "curl -s localhost:3100/ready")" = "ready" ]; then ok "Loki is ready"; else bad "Loki is not ready"; fi
hosts=$(remote db "curl -s localhost:3100/loki/api/v1/label/host/values")
for h in db fetcher history ui bastion; do
  if grep -q "\"${h}\"" <<< "$hosts"; then ok "logs from ${h}"; else bad "no logs from ${h} yet (log agent running there?)"; fi
done

echo
if [ "$fails" -eq 0 ]; then echo "ALL OK"; else echo "${fails} check(s) FAILED"; fi
exit $((fails > 0))
