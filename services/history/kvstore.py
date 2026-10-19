import logging
import threading

from db import DatabaseUnavailable

log = logging.getLogger("history.kvstore")

class CacheUnavailable(Exception):
    """The cache backend is unreachable right now (a transient problem)."""


class RedisStore:
    name = "redis"

    def __init__(self, settings):
        self._s = settings
        self._client = None

    def _redis(self):
        if self._client is None:
            import redis
            s = self._s
            self._client = redis.Redis(
                host=s.redis_host, port=s.redis_port, password=s.redis_password,
                decode_responses=True, socket_connect_timeout=3, socket_timeout=5,
            )
        return self._client

    def get(self, key):
        import redis
        try:
            return self._redis().get(key)
        except redis.RedisError as exc:
            raise CacheUnavailable(str(exc)) from exc

    def set(self, key, value, ttl):
        import redis
        try:
            self._redis().set(key, value, ex=ttl)
        except redis.RedisError as exc:
            raise CacheUnavailable(str(exc)) from exc

KV_SCHEMA = """
SELECT pg_advisory_xact_lock(727402);
CREATE TABLE IF NOT EXISTS kv_store (
    key        TEXT        PRIMARY KEY,
    value      TEXT        NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kv_store_expires_at ON kv_store (expires_at);
"""
KV_GET = "SELECT value FROM kv_store WHERE key = %s AND expires_at > now()"
KV_SET = ("INSERT INTO kv_store (key, value, expires_at) VALUES (%s, %s, now() + make_interval(secs => %s)) "
          "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, expires_at = EXCLUDED.expires_at")
KV_PURGE = "DELETE FROM kv_store WHERE expires_at < now()"


class PostgresStore:
    name = "postgres"

    def __init__(self, db):
        self._db = db
        self._schema_ready = False
        self._lock = threading.Lock()

    def _ensure_schema(self, conn):
        if self._schema_ready:
            return
        with self._lock:
            if not self._schema_ready:
                with conn.cursor() as cur:
                    cur.execute(KV_SCHEMA)
                self._schema_ready = True

    def get(self, key):
        try:
            with self._db.connection() as conn:
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(KV_GET, (key,))
                    row = cur.fetchone()
            return row[0] if row else None
        except DatabaseUnavailable as exc:
            raise CacheUnavailable(str(exc)) from exc

    def set(self, key, value, ttl):
        try:
            with self._db.connection() as conn:
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(KV_PURGE)  # saving is rare, so cleaning up here is enough
                    cur.execute(KV_SET, (key, value, ttl))
        except DatabaseUnavailable as exc:
            raise CacheUnavailable(str(exc)) from exc


def make_store(settings, db):
    if settings.cache_backend == "redis":
        return RedisStore(settings)
    if settings.cache_backend == "postgres":
        return PostgresStore(db)
    raise ValueError(f"unknown cache backend {settings.cache_backend!r}")