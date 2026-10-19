import json
import logging
import os
import sys
from datetime import datetime, timezone
 
import requests
 
from broker import ConfigError, make_consumer
 
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
        # We stamp the time ourselves: CityBikes' own timestamps are malformed.
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "stations": stations,
    }
 
 
def handle(message):
    """Handle one request. Returns the reply (the snapshot or {"error": ...}),
    or None for a malformed request, which is ignored."""
    try:
        request_id = str(json.loads(message)["id"])
    except (ValueError, KeyError, TypeError):
        log.warning("ignoring a malformed request: %r", message)
        return None
    try:
        reply = normalize(fetch_network())
        log.info("request %s answered: %d stations", request_id, len(reply["stations"]))
    except UpstreamError as exc:
        log.warning("request %s failed: %s", request_id, exc)
        reply = {"error": str(exc)}
    return reply
 
 
if __name__ == "__main__":
    try:
        consumer = make_consumer()
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")
    log.info("queue backend: %s", consumer.name)
    consumer.serve(handle)
