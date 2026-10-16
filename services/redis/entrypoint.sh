#!/bin/sh
# Writes the password into a config file at start instead of passing it as an argument
# (arguments are visible in `ps`). The image itself contains no secret.
set -eu
: "${REDIS_PASSWORD:?}"
(umask 077; printf 'requirepass "%s"\n' "${REDIS_PASSWORD}" > /tmp/redis-auth.conf)
exec redis-server /etc/redis/redis.conf
