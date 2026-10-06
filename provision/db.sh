#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
: "${DB_NAME:?}" "${DB_USER:?}" "${DB_PASSWORD:?}" "${DB_PORT:?}" "${ALLOWED_CIDR:?}"

cd /tmp

apt-get update && apt-get install -y postgresql

PG_DIR=$(ls -d /etc/postgresql/*/main)

cat > "${PG_DIR}/conf.d/citybikes.conf" <<CONF
listen_addresses = '*'
port = ${DB_PORT}
CONF

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

echo "db is up on port ${DB_PORT}, open to ${ALLOWED_CIDR}"