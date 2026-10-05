"""Stores snapshots in PostgreSQL and serves them to the UI over a small REST API.

Run ONE process (gunicorn: --workers 1 --threads 4). The poller lives inside
the process, so several workers would each poll and store duplicates.
"""
import logging

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


def create_app(settings=None, db=None, start_poller=True):
    settings = settings or Settings.from_env()
    db = db or Database(settings)
    state = PollState()

    app = Flask(__name__)

    # ----------------------------------------------------------- errors ----
    @app.errorhandler(DatabaseUnavailable)
    def db_down(exc):
        log.warning("database unavailable: %s", exc)
        return jsonify({"error": "database unavailable"}), 503

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
        # Liveness only: stays green even if the database or Fetcher is down.
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

    # ----------------------------------------------------------- poller ----
    if start_poller:
        poller = Poller(settings, db, state)
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