import logging
import os
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

BASE_URL = os.environ.get("CITYBIKE_BASE_URL", "https://api.citybik.es/v2")
NETWORK_ID = os.environ.get("CITYBIKES_NETWORK_ID", "pittsburgh")
TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "10"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("fetcher")
 
app = Flask(__name__)


class UpstreamError(Exception):
    """CityBikes is unreachable or returned something we cannot use."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

def fetch_network():
    url = f"{BASE_URL}/networks/{NETWORK_ID}"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout as exc:
        raise UpstreamError("CityBikes request timed out", 504) from exc
    except ValueError as exc:
        raise UpstreamError("CityBikes returned invalid JSON") from exc
    except requests.RequestException as exc:
        raise UpstreamError(f"CityBikes request failed: {exc}") from exc

    network = data.get("network") if isinstance(data, dict) else None
    if not isinstance(network, dict) or not isinstance(network.get("stations"), list):
        raise UpstreamError("Unexpected CityBikes response format")
    return network

def _int_or_none(value):
    """Counters can be null upstream. Keep 'unknown' as None, never fake a 0."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None

def normalize(network):
    """Reduce the big CityBikes payload to the small contract History relies on."""
    stations = []
    for st in network["stations"]:
        if not st.get("id"):
            continue
        extra = st.get("extra") or {}
        stations.append(
            {
                "id": st["id"],
                "name": st.get("name"),
                "latitude": st.get("latitude"),
                "longitude": st.get("longitude"),
                "free_bikes": _int_or_none(st.get("free_bikes")),
                "empty_slots": _int_or_none(st.get("empty_slots")),
                "ebikes": _int_or_none(extra.get("ebikes")),
                "slots": _int_or_none(extra.get("slots")),
            }
        )

    return {
        "network_id": network.get("id", NETWORK_ID),
        "network_name": network.get("name"),
        # We stamp the time ourselves. The per-station timestamps from CityBikes
        # are malformed (e.g. '...+00:00Z'), so we deliberately do not parse them.
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "stations": stations,
    }

@app.errorhandler(UpstreamError)
def handle_upstream_error(err):
    log.error("upstream error: %s", err.message)
    return jsonify({"error": err.message}), err.status_code


@app.get("/health")
def health():
    # Liveness only: does NOT call CityBikes, so it stays green if upstream is down.
    return jsonify({"status": "ok"})


@app.get("/snapshot")
def snapshot():
    data = normalize(fetch_network())
    log.info("snapshot ok: %d stations", len(data["stations"]))
    return jsonify(data)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8001")))
