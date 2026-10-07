import json
import logging
import re
import uuid
 
import redis
from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, HTTPException
 
from db import Database, DatabaseUnavailable
from poller import Poller, PollState
from settings import ConfigError, Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("history")


def _int_arg(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"{name} must be an integer between {lo} and {hi}") from None
    if not lo <= value <= hi:
        raise BadRequest(f"{name} must be an integer between {lo} and {hi}")
    return value


def _delta(cur, prev):
    if prev is None:
        return None
    occ = None
    if cur["occupancy_pct"] is not None and prev["occupancy_pct"] is not None:
        occ = round(cur["occupancy_pct"] - prev["occupancy_pct"], 1)
    return {
        "free_bikes": cur["free_bikes"] - prev["free_bikes"],
        "empty_slots": cur["empty_slots"] - prev["empty_slots"],
        "occupancy_pct": occ,
    }

SESSION_COOKIE = "sid"
SESSION_RE = re.compile(r"^[0-9a-f]{32}$")  # only ids we generated ourselves are accepted

PREFS_TTL = 30 * 24 * 3600
PREF_CHOICES = {"theme": ("light", "dark"), "range": (60, 360, 1440), "stationsTab": ("top", "empty")}
PREF_DEFAULTS = {"theme": None, "range": 60, "stationsTab": "top"}  # theme None = follow the system

def allowed_prefs(data):
    """Keep only known keys with allowed values; everything else falls back to the default."""
    data = data if isinstance(data, dict) else {}
    return {key: (data[key] if data.get(key) in allowed else PREF_DEFAULTS[key])
            for key, allowed in PREF_CHOICES.items()}

def make_cache(s):
    return redis.Redis(host=s.redis_host, port=s.redis_port, password=s.redis_password,
                       decode_responses=True, socket_connect_timeout=3,
                       socket_timeout=s.request_timeout + 5)  # longer than the wait for a fetcher reply


def create_app(settings=None, db=None, start_poller=True, cache=None):
    settings = settings or Settings.from_env()
    db = db or Database(settings)
    cache = cache if cache is not None else make_cache(settings)
    state = PollState()

    app = Flask(__name__)

    # ----------------------------------------------------------- errors ----
    @app.errorhandler(DatabaseUnavailable)
    def db_down(exc):
        log.warning("database unavailable: %s", exc)
        return jsonify({"error": "database unavailable"}), 503

    @app.errorhandler(redis.RedisError)
    def cache_down(exc):
        log.warning("cache unavailable: %s", exc)
        return jsonify({"error": "cache unavailable"}), 503

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify({"error": exc.description}), exc.code

    @app.errorhandler(Exception)
    def unexpected(exc):
        log.exception("unhandled error")
        return jsonify({"error": "internal error"}), 500

    # ----------------------------------------------------------- routes ----
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/status")
    def status():
        info = state.snapshot()
        info["poll_interval"] = settings.poll_interval
        try:
            info["snapshots_total"] = db.count_snapshots()
            info["db_ok"] = True
        except DatabaseUnavailable as exc:
            info["snapshots_total"] = None
            info["db_ok"] = False
            info["db_error"] = str(exc)
        return jsonify(info)

    @app.get("/api/current")
    def current():
        rows = db.latest_two()
        if not rows:
            return jsonify({"error": "no data yet"}), 404
        cur = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        return jsonify({"current": cur, "previous": prev, "delta": _delta(cur, prev)})

    @app.get("/api/history")
    def history():
        minutes = _int_arg("minutes", 60, 1, 10080)
        return jsonify({"minutes": minutes, "snapshots": db.history(minutes)})

    @app.get("/api/stations/top")
    def stations_top():
        limit = _int_arg("limit", 10, 1, 100)
        data = db.stations_latest(limit=limit, top=True)
        if data is None:
            return jsonify({"error": "no data yet"}), 404
        return jsonify(data)

    @app.get("/api/stations/latest")
    def stations_latest():
        data = db.stations_latest()
        if data is None:
            return jsonify({"error": "no data yet"}), 404
        return jsonify(data)

    @app.put("/api/preferences")
    def put_preferences():
        prefs = allowed_prefs(request.get_json(silent=True))
        sid = request.cookies.get(SESSION_COOKIE, "")
        if not SESSION_RE.match(sid):
            sid = uuid.uuid4().hex  # first save from this browser: give it an id
        cache.set(f"prefs:{sid}", json.dumps(prefs), ex=PREFS_TTL)
        resp = jsonify(prefs)
        resp.set_cookie(SESSION_COOKIE, sid, max_age=PREFS_TTL, httponly=True, samesite="Lax")
        return resp

    @app.get("/api/preferences")
    def get_preferences():
        sid = request.cookies.get(SESSION_COOKIE, "")
        raw = cache.get(f"prefs:{sid}") if SESSION_RE.match(sid) else None
        return jsonify(allowed_prefs(json.loads(raw)) if raw else PREF_DEFAULTS)

    # ----------------------------------------------------------- poller ----
    if start_poller:
        poller = Poller(settings, db, state, cache)
        poller.start()
        app.extensions["poller"] = poller

    return app


if __name__ == "__main__":
    try:
        cfg = Settings.from_env()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}")
    # use_reloader=False: the reloader would start a second process and a second poller.
    create_app(cfg).run(host=cfg.host, port=cfg.port, threaded=True, use_reloader=False)