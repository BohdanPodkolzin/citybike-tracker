"""Docker HEALTHCHECK for the fetcher: it has no port, so check what it lives on - Redis."""
import os
import sys

import redis

try:
    redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ["REDIS_PASSWORD"],
        socket_connect_timeout=3,
    ).ping()
except Exception as exc:  # any failure = unhealthy
    sys.exit(f"unhealthy: {exc}")
