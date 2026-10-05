#!/usr/bin/env bash

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required (set it in .env)}"
: "${DB_PORT:?DB_PORT is required}"
: "${ALLOWED_CIDR:?ALLOWED_CIDR is required}"

echo "==> Installing PostgreSQL"
apt-get install -y postgresql postgresql-contrib

PG_VER="$(ls /etc/postgresql | sort -V | tail -n 1)"
PG_DIR="/etc/postgresql/${PG_VER}/main"
HBA="${PG_DIR}/pg_hba.conf"

echo "==> Configuring PostgreSQL ${PG_VER} (port ${DB_PORT})"
mkdir -p "${PG_DIR}/conf.d"
cat > "${PG_DIR}/conf.d/citybikes.conf" <<CONF
listen_addresses = '*'
port = ${DB_PORT}
password_encryption = scram-sha-256
CONF


echo "==> Allowing clients: ${ALLOWED_CIDR}"
# Rebuild our block on every run so re-provisioning never duplicates rules.
sed -i '/# BEGIN citybikes/,/# END citybikes/d' "${HBA}"
{
  echo "# BEGIN citybikes"
  echo "host    ${DB_NAME}    ${DB_USER}    ${ALLOWED_CIDR}    scram-sha-256"
  echo "# END citybikes"
} >> "${HBA}"


echo "==> Making the service restart itself if it dies"
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

echo "==> Waiting for PostgreSQL"
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q -p "${DB_PORT}"; then break; fi
  sleep 1
done
sudo -u postgres pg_isready -p "${DB_PORT}"

echo "==> Creating role and database"
# psql variables (:'name') quote values safely, so odd characters in the
# password cannot break the SQL. \gexec runs the generated statement.
sudo -u postgres psql -p "${DB_PORT}" -v ON_ERROR_STOP=1 \
  -v db_user="${DB_USER}" -v db_pass="${DB_PASSWORD}" -v db_name="${DB_NAME}" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_pass')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db_user') \gexec
 
SELECT format('ALTER ROLE %I PASSWORD %L', :'db_user', :'db_pass') \gexec
 
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name') \gexec
SQL
 
echo "==> DB VM ready: ${DB_NAME} on port ${DB_PORT}, clients allowed from ${ALLOWED_CIDR}"
