import json
import logging
import os
import time

log = logging.getLogger("fetcher.broker")

REQUEST_QUEUE = "fetch.requests"
REPLY_TTL = 60          # seconds a reply stays in Postgres if History gave up waiting
LEASE = 30              # seconds a Postgres request is "ours" before it is offered again
POLL = 0.5              # seconds between looks at an empty Postgres queue
RETRY = 3               # seconds to wait before reconnecting

BACKENDS = ("rabbitmq", "postgres")

class ConfigError(Exception):
    """A required setting is missing or invalid. Fix the environment, not the code."""


def _need(env, name):
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _run(handle, message):
    """Never let one bad request kill the worker: a bug becomes an error reply."""
    try:
        return handle(message)
    except Exception as exc:  
        log.exception("unexpected error while handling a request")
        return {"error": f"fetcher internal error: {exc}"}


# ============================================================== RabbitMQ
class RabbitConsumer:
    name = "rabbitmq"

    def __init__(self, host, port, user, password, vhost):
        self.host, self.port, self.user, self.password, self.vhost = host, port, user, password, vhost

    def _params(self):
        import pika
        return pika.ConnectionParameters(
            host=self.host, port=self.port, virtual_host=self.vhost,
            credentials=pika.PlainCredentials(self.user, self.password),
            heartbeat=30, socket_timeout=5, blocked_connection_timeout=30, connection_attempts=1,
        )

    def ping(self):
        import pika
        pika.BlockingConnection(self._params()).close()

    def serve(self, handle):
        import pika
        while True:
            try:
                self._consume(handle)
            except (pika.exceptions.AMQPError, OSError) as exc:  # broker restarting or unreachable
                log.warning("rabbitmq problem: %s", exc)
                time.sleep(RETRY)

    def _consume(self, handle):
        import pika
        conn = pika.BlockingConnection(self._params())
        try:
            channel = conn.channel()
            channel.queue_declare(queue=REQUEST_QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)  # one request at a time
            log.info("worker ready, waiting for requests on queue %s", REQUEST_QUEUE)
            # inactivity_timeout: wake up every 5 s so heartbeats are answered
            for method, props, body in channel.consume(REQUEST_QUEUE, inactivity_timeout=5):
                if method is None:
                    continue
                self.on_delivery(channel, method, props, body, handle)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def on_delivery(self, channel, method, props, body, handle):
        import pika
        reply = _run(handle, body)
        if reply is not None and props.reply_to:
            channel.basic_publish(
                exchange="", routing_key=props.reply_to, body=json.dumps(reply).encode(),
                properties=pika.BasicProperties(correlation_id=props.correlation_id,
                                                content_type="application/json"),
            )
        # ack only AFTER the reply is sent: if we crash before, the request is delivered again
        channel.basic_ack(method.delivery_tag)


# ============================================================= PostgreSQL
SCHEMA = """
SELECT pg_advisory_xact_lock(727401);  -- History and Fetcher may both create the tables at start
CREATE TABLE IF NOT EXISTS mq_requests (
    id             BIGSERIAL   PRIMARY KEY,
    queue          TEXT        NOT NULL,
    correlation_id TEXT        NOT NULL,
    body           TEXT        NOT NULL,
    expires_at     TIMESTAMPTZ NOT NULL,
    locked_until   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_mq_requests_queue ON mq_requests (queue, id);
CREATE TABLE IF NOT EXISTS mq_replies (
    correlation_id TEXT        PRIMARY KEY,
    body           TEXT        NOT NULL,
    expires_at     TIMESTAMPTZ NOT NULL
);
"""

# take ONE request that is not expired and not leased by another worker (SKIP LOCKED: never wait)
CLAIM = """
UPDATE mq_requests SET locked_until = now() + make_interval(secs => %s)
WHERE id = (
    SELECT id FROM mq_requests
    WHERE queue = %s AND expires_at > now() AND (locked_until IS NULL OR locked_until < now())
    ORDER BY id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, correlation_id, body
"""
REPLY = """
INSERT INTO mq_replies (correlation_id, body, expires_at)
VALUES (%s, %s, now() + make_interval(secs => %s))
ON CONFLICT (correlation_id) DO UPDATE SET body = EXCLUDED.body, expires_at = EXCLUDED.expires_at
"""
DONE = "DELETE FROM mq_requests WHERE id = %s"
CLEANUP = ("DELETE FROM mq_requests WHERE expires_at < now() - interval '1 minute'; "
           "DELETE FROM mq_replies WHERE expires_at < now()")


class PostgresConsumer:
    name = "postgres"

    def __init__(self, host, port, dbname, user, password):
        self.params = dict(host=host, port=port, dbname=dbname, user=user, password=password,
                           connect_timeout=5, options="-c timezone=UTC")
        self._schema_ready = False

    def _connect(self):
        import psycopg2
        return psycopg2.connect(**self.params)

    def ping(self):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()

    def ensure_schema(self, conn):
        if not self._schema_ready:
            with conn, conn.cursor() as cur:  # one transaction (the advisory lock lives inside it)
                cur.execute(SCHEMA)
            self._schema_ready = True

    def serve(self, handle):
        import psycopg2
        while True:
            conn = None
            try:
                conn = self._connect()
                self.ensure_schema(conn)
                log.info("worker ready, waiting for requests in table mq_requests")
                idle = 0
                while True:
                    if self.process_one(conn, handle):
                        idle = 0
                        continue
                    idle += 1
                    if idle % 120 == 1:  # about once a minute while idle
                        with conn, conn.cursor() as cur:
                            cur.execute(CLEANUP)
                    time.sleep(POLL)
            except psycopg2.Error as exc:  # database restarting or unreachable
                log.warning("postgres problem: %s", exc)
                time.sleep(RETRY)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass

    def process_one(self, conn, handle):
        """Claim one request, answer it. Returns False when the queue is empty."""
        with conn, conn.cursor() as cur:
            cur.execute(CLAIM, (LEASE, REQUEST_QUEUE))
            row = cur.fetchone()
        if row is None:
            return False
        request_id, correlation_id, body = row
        reply = _run(handle, body)
        with conn, conn.cursor() as cur:  # reply + removal of the request: all or nothing
            if reply is not None:
                cur.execute(REPLY, (correlation_id, json.dumps(reply), REPLY_TTL))
            cur.execute(DONE, (request_id,))
        return True


# ================================================================ factory
def make_consumer(env=None):
    env = os.environ if env is None else env
    backend = (env.get("QUEUE_BACKEND") or "rabbitmq").strip().lower()
    if backend == "rabbitmq":
        return RabbitConsumer(
            host=_need(env, "RABBITMQ_HOST"), port=int(env.get("RABBITMQ_PORT") or 5672),
            user=_need(env, "RABBITMQ_USER"), password=_need(env, "RABBITMQ_PASSWORD"),
            vhost=(env.get("RABBITMQ_VHOST") or "citybikes"),
        )
    if backend == "postgres":
        return PostgresConsumer(
            host=_need(env, "DB_HOST"), port=int(env.get("DB_PORT") or 5432),
            dbname=_need(env, "DB_NAME"), user=_need(env, "DB_USER"), password=_need(env, "DB_PASSWORD"),
        )
    raise ConfigError(f"QUEUE_BACKEND must be one of {', '.join(BACKENDS)}, got {backend!r}")
