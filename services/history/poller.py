import json
import logging
import threading
import uuid
from datetime import datetime, timezone
 
import redis
 
from db import DatabaseUnavailable


log = logging.getLogger("history.poller")

class PollError(Exception):
    """Fetcher is unreachable or returned something unusable."""

def _datetime_now():
    return datetime.now(timezone.utc).isoformat()

REQUESTS = "fetch:requests"
REPLY_PREFIX = "fetch:reply:"

def get_snapshot(cache, settings):
    """fetcher giving fresh data throug broker(redis) and wait for its answer"""
    request_id = uuid.uuid4().hex
    message = json.dumps({"id": request_id})
    try:
        cache.lpush(REQUESTS, message)
        item = cache.brpop(REPLY_PREFIX + request_id, timeout=max(1, int(settings.request_timeout)))
        if item is None:
            cache.lrem(REQUESTS, 1, message)  # nobody took it: withdraw, so requests never pile up
            raise PollError("Fetcher did not answer in time (is it running?)")
        reply = json.loads(item[1])
    except redis.RedisError as exc:
        raise PollError(f"Redis: {exc}") from exc
    if isinstance(reply, dict) and "error" in reply:
        raise PollError(f"Fetcher: {reply['error']}")
    return reply

def _parse_time(value):
    if not isinstance(value, str):
        raise PollError("Fetcher response has no fetched_at")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PollError(f"Bad fetched_at: {value!r}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def build_snapshot(data):
    if not isinstance(data, dict) or not isinstance(data.get("stations"), list):
        raise PollError("Unexpected Fetcher response format")
 
    unique = {}  # one entry per station id, in case of duplicates
    for st in data["stations"]:
        if isinstance(st, dict) and st.get("id") is not None:
            unique[str(st["id"])] = st
    stations = list(unique.values())
 
    bikes = sum(s["free_bikes"] for s in stations if isinstance(s.get("free_bikes"), int))
    slots = sum(s["empty_slots"] for s in stations if isinstance(s.get("empty_slots"), int))
    total = bikes + slots
    aggregates = {
        "fetched_at": _parse_time(data.get("fetched_at")),
        "network_id": str(data.get("network_id") or ""),
        "network_name": data.get("network_name"),
        "stations_count": len(stations),
        "free_bikes": bikes,
        "empty_slots": slots,
        # share of docks that currently hold a bike
        "occupancy_pct": round(100.0 * bikes / total, 1) if total > 0 else None,
    }
    return aggregates, stations


class PollState:
    """Thread-safe status of the poller, shown by /api/status."""
 
    def __init__(self):
        self._lock = threading.Lock()
        self._d = {
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
            "consecutive_failures": 0,
            "polls_ok": 0,
            "polls_failed": 0,
        }

    def record_success(self):
        with self._lock:
            now = _datetime_now()
            self._d.update(
                last_attempt_at=now, last_success_at=now, last_error=None,
                consecutive_failures=0,
            )
            self._d["polls_ok"] += 1

    def record_failure(self, message):
        with self._lock:
            self._d.update(last_attempt_at=_datetime_now(), last_error=message)
            self._d["consecutive_failures"] += 1
            self._d["polls_failed"] += 1

    def snapshot(self):
        with self._lock:
            return dict(self._d)

class Poller:
    def __init__(self, settings, db, state, cache=None, fetch=None):
        self._settings = settings
        self._db = db
        self._state = state
        self._fetch = fetch or (lambda s: get_snapshot(cache, s))
        self._stop = threading.Event()
        self._thread = None
 
    def cycle(self):
        """One poll. Never raises; returns True when a snapshot was stored."""
        try:
            data = self._fetch(self._settings)
            aggregates, stations = build_snapshot(data)
            self._db.save_snapshot(aggregates, stations)
        except PollError as exc:
            log.warning("poll failed (fetcher): %s", exc)
            self._state.record_failure(f"fetcher: {exc}")
            return False
        except DatabaseUnavailable as exc:
            log.warning("poll failed (database): %s", exc)
            self._state.record_failure(f"database: {exc}")
            return False
        except Exception as exc:  # a bug must not kill the loop either
            log.exception("unexpected error in poll cycle")
            self._state.record_failure(f"unexpected: {exc}")
            return False
        self._state.record_success()
        log.info(
            "stored snapshot: %d stations, %d bikes, %d free slots",
            aggregates["stations_count"], aggregates["free_bikes"], aggregates["empty_slots"],
        )
        return True
 
    def run(self):
        while not self._stop.is_set():
            self.cycle()
            self._stop.wait(self._settings.poll_interval)
 
    def start(self):
        self._thread = threading.Thread(target=self.run, name="poller", daemon=True)
        self._thread.start()
        log.info("poller started, interval %ss", self._settings.poll_interval)
 
    def stop(self):
        self._stop.set()
