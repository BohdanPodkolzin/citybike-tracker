#!/bin/sh

set -eu
: "${POSTGRES_DB:?}" "${POSTGRES_USER:?}" "${POSTGRES_PASSWORD:?}" "${ALLOWED_CIDR:?}"

cat > /tmp/pg_hba.conf <<RULES
# inside the container only (initdb scripts, healthcheck, psql via docker exec)
local all all trust
# the network: only ALLOWED_CIDR, only our role and database, password (scram) required
host ${POSTGRES_DB} ${POSTGRES_USER} ${ALLOWED_CIDR} scram-sha-256
RULES
chmod 644 /tmp/pg_hba.conf

exec docker-entrypoint.sh "$@"
