"""
Every operation opens a short-lived connection instead.
"""

import logging
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

log = logging.getLogger("history.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS network_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    fetched_at     TIMESTAMPTZ      NOT NULL,
    network_id     TEXT             NOT NULL,
    network_name   TEXT,
    stations_count INTEGER          NOT NULL,
    free_bikes     INTEGER          NOT NULL,
    empty_slots    INTEGER          NOT NULL,
    occupancy_pct  DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_network_snapshots_fetched_at
    ON network_snapshots (fetched_at DESC);

CREATE TABLE IF NOT EXISTS station_snapshots (
    snapshot_id BIGINT NOT NULL REFERENCES network_snapshots(id) ON DELETE CASCADE,
    station_id  TEXT   NOT NULL,
    name        TEXT,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    free_bikes  INTEGER,
    empty_slots INTEGER,
    ebikes      INTEGER,
    slots       INTEGER,
    PRIMARY KEY (snapshot_id, station_id)
);
"""

NETWORK_COLUMNS = (
    "id, fetched_at, network_id, network_name, "
    "stations_count, free_bikes, empty_slots, occupancy_pct"
)


class DatabaseUnavailable(Exception):
    """Cannot reach or talk to PostgreSQL right now (a transient problem)."""


def _iso(value):
    return value.isoformat() if value is not None else None


def _network_row(row):
    row = dict(row)
    row["fetched_at"] = _iso(row["fetched_at"])
    return row


class Database:
    def __init__(self, settings):
        self._s = settings
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    # ---------------------------------------------------------- plumbing ----
    @contextmanager
    def _connection(self):
        s = self._s
        try:
            conn = psycopg2.connect(
                host=s.db_host,
                port=s.db_port,
                dbname=s.db_name,
                user=s.db_user,
                password=s.db_password,
                connect_timeout=s.db_connect_timeout,
                options="-c timezone=UTC",
            )
        except psycopg2.OperationalError as exc:
            raise DatabaseUnavailable(str(exc).strip()) from exc
        try:
            with conn:  # commit on success, rollback on error
                yield conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            raise DatabaseUnavailable(str(exc).strip()) from exc
        finally:
            conn.close()

    def ensure_schema(self):
        """Create tables if missing. Cheap after the first success."""
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connection() as conn, conn.cursor() as cur:
                cur.execute(SCHEMA)
            self._schema_ready = True
            log.info("database schema is ready")

    # ------------------------------------------------------------ writing ----
    def save_snapshot(self, agg, stations):
        """Store one network snapshot plus its stations in ONE transaction."""
        self.ensure_schema()
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO network_snapshots
                    (fetched_at, network_id, network_name, stations_count,
                     free_bikes, empty_slots, occupancy_pct)
                VALUES (%(fetched_at)s, %(network_id)s, %(network_name)s,
                        %(stations_count)s, %(free_bikes)s, %(empty_slots)s,
                        %(occupancy_pct)s)
                RETURNING id
                """,
                agg,
            )
            snapshot_id = cur.fetchone()[0]
            rows = [
                (
                    snapshot_id,
                    str(st["id"]),
                    st.get("name"),
                    st.get("latitude"),
                    st.get("longitude"),
                    st.get("free_bikes"),
                    st.get("empty_slots"),
                    st.get("ebikes"),
                    st.get("slots"),
                )
                for st in stations
            ]
            if rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO station_snapshots
                        (snapshot_id, station_id, name, latitude, longitude,
                         free_bikes, empty_slots, ebikes, slots)
                    VALUES %s
                    """,
                    rows,
                )
        return snapshot_id

    # ------------------------------------------------------------ reading ----
    def count_snapshots(self):
        self.ensure_schema()
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM network_snapshots")
            return cur.fetchone()[0]

    def latest_two(self):
        """The two newest network snapshots (newest first)."""
        self.ensure_schema()
        with self._connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {NETWORK_COLUMNS} FROM network_snapshots "
                "ORDER BY fetched_at DESC, id DESC LIMIT 2"
            )
            return [_network_row(r) for r in cur.fetchall()]

    def history(self, minutes):
        """Network snapshots from the last `minutes`, oldest first (for charts)."""
        self.ensure_schema()
        with self._connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT {NETWORK_COLUMNS} FROM network_snapshots
                WHERE fetched_at >= now() - make_interval(mins => %s)
                ORDER BY fetched_at ASC, id ASC
                LIMIT 20000
                """,
                (minutes,),
            )
            return [_network_row(r) for r in cur.fetchall()]

    def stations_latest(self, limit=None, top=False):
        """Stations of the newest snapshot.

        top=True orders by free bikes (most first); otherwise by name.
        Returns None when there is no data yet.
        """
        self.ensure_schema()
        order = "free_bikes DESC NULLS LAST, name" if top else "name"
        sql = (
            "SELECT station_id AS id, name, latitude, longitude, "
            "free_bikes, empty_slots, ebikes, slots "
            f"FROM station_snapshots WHERE snapshot_id = %s ORDER BY {order}"
        )
        params = [None]
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        with self._connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, fetched_at FROM network_snapshots "
                "ORDER BY fetched_at DESC, id DESC LIMIT 1"
            )
            head = cur.fetchone()
            if head is None:
                return None
            params[0] = head["id"]
            cur.execute(sql, params)
            return {
                "snapshot_id": head["id"],
                "fetched_at": _iso(head["fetched_at"]),
                "stations": [dict(r) for r in cur.fetchall()],
            }