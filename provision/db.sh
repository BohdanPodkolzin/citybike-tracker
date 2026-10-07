#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

: "${DB_NAME:?}" "${DB_USER:?}" "${DB_PASSWORD:?}" "${DB_PORT:?}" "${ALLOWED_CIDR:?}"
: "${REDIS_PORT:?}" "${REDIS_PASSWORD:?}"

cd /tmp

apt-get update && apt-get install -y postgresql redis-server

PG_DIR=$(ls -d /etc/postgresql/*/main)

cat > "${PG_DIR}/conf.d/citybikes.conf" <<CONF
listen_addresses = '*'
port = ${DB_PORT}
CONF

# Only ALLOWED_CIDR may log in to our database.
sed -i '/# citybikes$/d' "${PG_DIR}/pg_hba.conf"
echo "host ${DB_NAME} ${DB_USER} ${ALLOWED_CIDR} scram-sha-256 # citybikes" >> "${PG_DIR}/pg_hba.conf"

mkdir -p /etc/systemd/system/postgresql@.service.d
cat > /etc/systemd/system/postgresql@.service.d/restart.conf <<UNIT
[Unit]
StartLimitIntervalSec=0

[Service]
Restart=always
RestartSec=3
UNIT

systemctl daemon-reload
systemctl enable postgresql
systemctl restart postgresql

# psql as the postgres user: -t -A = plain output without headers
psql_() { sudo -u postgres psql -p "${DB_PORT}" -tA "$@"; }

for _ in $(seq 30); do psql_ -c "select 1" >/dev/null 2>&1 && break; sleep 1; done

# Create the role and the database only if they are missing; always set the password.
[ "$(psql_ -c "select 1 from pg_roles where rolname='${DB_USER}'")" = 1 ] || psql_ -c "create role ${DB_USER} login"
psql_ -c "alter role ${DB_USER} password '${DB_PASSWORD}'"
[ "$(psql_ -c "select 1 from pg_database where datname='${DB_NAME}'")" = 1 ] || psql_ -c "create database ${DB_NAME} owner ${DB_USER}"

# --- Redis ---
# Listen on the network (not only on localhost) and require a password.
sed -i "s/^bind .*/bind 0.0.0.0/; s/^port .*/port ${REDIS_PORT}/; /^requirepass /d" /etc/redis/redis.conf
echo "requirepass ${REDIS_PASSWORD}" >> /etc/redis/redis.conf
 
systemctl enable redis-server      # start on boot (the package unit also restarts it after a crash)
systemctl restart redis-server
 
# wait for it, then fail the script if it still does not answer
for _ in $(seq 20); do
  REDISCLI_AUTH="${REDIS_PASSWORD}" redis-cli -p "${REDIS_PORT}" ping 2>/dev/null | grep -q PONG && break
  sleep 1
done
REDISCLI_AUTH="${REDIS_PASSWORD}" redis-cli -p "${REDIS_PORT}" ping | grep -q PONG
 
echo "db is up: postgres on ${DB_PORT} (open to ${ALLOWED_CIDR}), redis on ${REDIS_PORT}"
