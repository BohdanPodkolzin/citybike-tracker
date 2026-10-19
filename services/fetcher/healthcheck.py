"""Docker HEALTHCHECK for the fetcher: it has no port, so check what it lives on - the broker."""
import sys

from broker import make_consumer

try:
    make_consumer().ping()
except Exception as exc:  # any failure = unhealthy
    sys.exit(f"unhealthy: {exc}")
