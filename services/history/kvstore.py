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
        if self._client is None:  # created on first use, so the module is not needed until then
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
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE TABLE IF NOT EXISTS kv_hstore (
    namespace TEXT   PRIMARY KEY,
    entries   hstore NOT NULL DEFAULT ''::hstore,
    expires   hstore NOT NULL DEFAULT ''::hstore
)
"""

KV_GET = ("SELECT entries -> %s FROM kv_hstore "
          "WHERE namespace = %s AND (expires -> %s)::bigint > extract(epoch FROM now())::bigint")

_EXPIRED = ("ARRAY(SELECT k FROM each(kv_hstore.expires) AS e(k, v) "
            "WHERE v::bigint <= extract(epoch FROM now())::bigint)")
KV_SET = ("INSERT INTO kv_hstore (namespace, entries, expires) "
          "VALUES (%s, hstore(%s::text, %s::text), hstore(%s::text, (extract(epoch FROM now())::bigint + %s)::text)) "
          "ON CONFLICT (namespace) DO UPDATE SET "
          f"entries = delete(kv_hstore.entries, {_EXPIRED}) || EXCLUDED.entries, "
          f"expires = delete(kv_hstore.expires, {_EXPIRED}) || EXCLUDED.expires")


def _namespace(key):
    """"prefs:ab12..." -> "prefs" (keys without a colon share the namespace "default")."""
    head, sep, _ = key.partition(":")
    return head if sep and head else "default"


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
                    cur.execute(KV_GET, (key, _namespace(key), key))
                    row = cur.fetchone()
            return row[0] if row else None
        except DatabaseUnavailable as exc:
            raise CacheUnavailable(str(exc)) from exc

    def set(self, key, value, ttl):
        try:
            with self._db.connection() as conn:
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(KV_SET, (_namespace(key), key, value, key, int(ttl)))
        except DatabaseUnavailable as exc:
            raise CacheUnavailable(str(exc)) from exc


def make_store(settings, db):
    if settings.cache_backend == "redis":
        return RedisStore(settings)
    if settings.cache_backend == "postgres":
        return PostgresStore(db)
    raise ValueError(f"unknown cache backend {settings.cache_backend!r}")
