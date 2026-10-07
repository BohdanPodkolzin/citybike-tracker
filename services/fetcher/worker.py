""" 
Waiting for task form redis list -> asking the CityBikes API -> put reply to into reply list 

  request  ->  list "fetch:requests"       {"id": "<hex>"}
  reply    ->  list "fetch:reply:<id>"     the snapshot, or {"error": "..."}
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
 
import redis
import requests

REQUESTS = "fetch:requests"
REPLY_PREFIX = "fetch:reply:"
REPLY_TTL = 60 # seconds; unread reply? cleans itself up

BASE_URL = os.environ.get("CITYBIKES_BASE_URL", "https://api.citybik.es/v2")
NETWORK_ID = os.environ.get("CITYBIKES_NETWORK_ID", "pittsburgh")
TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fetcher")

class UpstreamError(Exception):
    """CityBikes is unreachable or returned something we cannot use."""


def fetch_network():
    """Call CityBikes and return the raw 'network' object."""
    try:
        resp = requests.get(f"{BASE_URL}/networks/{NETWORK_ID}", timeout=TIMEOUT)
        resp.raise_for_status()
        network = resp.json().get("network")
    except (requests.RequestException, ValueError, AttributeError) as exc:
        raise UpstreamError(f"CityBikes request failed: {exc}") from exc
    if not isinstance(network, dict) or not isinstance(network.get("stations"), list):
        raise UpstreamError("Unexpected CityBikes response format")
    return network

def _int_or_none(value):
    """Counters can be null upstream. Keep 'unknown' as None, never fake a 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None

def normalize(network):
    """Reduce the big CityBikes payload to the small contract History relies on."""
    stations = []
    for st in network["stations"]:
        if not st.get("id"):
            continue
        extra = st.get("extra") or {}
        stations.append({
            "id": st["id"],
            "name": st.get("name"),
            "latitude": st.get("latitude"),
            "longitude": st.get("longitude"),
            "free_bikes": _int_or_none(st.get("free_bikes")),
            "empty_slots": _int_or_none(st.get("empty_slots")),
            "ebikes": _int_or_none(extra.get("ebikes")),
            "slots": _int_or_none(extra.get("slots")),
        })
    return {
        "network_id": network.get("id", NETWORK_ID),
        "network_name": network.get("name"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "stations": stations,
    }

def answer(r, message):
    """Handle one request: fetch the data and put the reply where History waits."""
    try:
        request_id = str(json.loads(message)["id"])
    except (ValueError, KeyError, TypeError):
        log.warning("ignoring a malformed request: %r", message)
        return
    try:
        reply = normalize(fetch_network())
        log.info("request %s answered: %d stations", request_id, len(reply["stations"]))
    except UpstreamError as exc:
        log.warning("request %s failed: %s", request_id, exc)
        reply = {"error": str(exc)}
    key = REPLY_PREFIX + request_id
    r.lpush(key, json.dumps(reply)) # push el to the left side of a list
    r.expire(key, REPLY_TTL)

def start_worker(r):
    log.info("worker ready, waiting for requests")
    while True:
        try:
            item = r.brpop(REQUESTS, timeout=5)  # request list: pop and delete right req, if r = [] then block loop (waiting)
            if item:
                answer(r, item[1]) # 
        except redis.RedisError as exc:
            log.warning("redis problem: %s", exc)
            time.sleep(3)

def need(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing environment variable: {name}")
    return value

if __name__ == "__main__":
    client = redis.Redis(
        host=need("REDIS_HOST"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=need("REDIS_PASSWORD"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=10
    )
    start_worker(client)
