import json
import logging
import time
import uuid

from db import DatabaseUnavailable

log = logging.getLogger("history.broker")

REQUEST_QUEUE = "fetch.requests"
REPLY_TO = "amq.rabbitmq.reply-to"
POLL = 0.3  


class BrokerError(Exception):
    """The queue backend is unreachable or misbehaves."""


class QueueTimeout(BrokerError):
    """Nobody answered in time."""


# ============================================================== RabbitMQ

class RabbitRequester:
    name = "rabbitmq"

    def __init__(self, settings):
        self._s = settings

    def _params(self):
        import pika
        s = self._s
        return pika.ConnectionParameters(
            host=s.rabbitmq_host, port=s.rabbitmq_port, virtual_host=s.rabbitmq_vhost,
            credentials=pika.PlainCredentials(s.rabbitmq_user, s.rabbitmq_password),
            heartbeat=30, socket_timeout=5, blocked_connection_timeout=30, connection_attempts=1,
        )

    def request(self, timeout):
        import pika
        errors = (pika.exceptions.AMQPError, OSError)
        correlation_id = uuid.uuid4().hex
        got = {}

        def on_reply(_channel, _method, props, body):
            if props.correlation_id == correlation_id:  # only the answer to OUR request
                got["body"] = body

        # a short-lived connection per request (one poll a minute): a restarted broker
        # heals by itself, there is no stale connection to repair
        try:
            conn = pika.BlockingConnection(self._params())
        except errors as exc:
            raise BrokerError(str(exc) or type(exc).__name__) from exc
        try:
            channel = conn.channel()
            channel.queue_declare(queue=REQUEST_QUEUE, durable=True)
            # direct reply-to: start consuming from the pseudo-queue BEFORE publishing
            channel.basic_consume(queue=REPLY_TO, on_message_callback=on_reply, auto_ack=True)
            channel.basic_publish(
                exchange="", routing_key=REQUEST_QUEUE, body=json.dumps({"id": correlation_id}).encode(),
                properties=pika.BasicProperties(
                    reply_to=REPLY_TO, correlation_id=correlation_id, content_type="application/json",
                    expiration=str(max(1, int(timeout * 1000))),  # message TTL in ms
                ),
            )
            deadline = time.monotonic() + timeout
            while "body" not in got:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise QueueTimeout("no answer in time")
                conn.process_data_events(time_limit=min(left, 1.0))
        except errors as exc:
            raise BrokerError(str(exc) or type(exc).__name__) from exc
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001  (already broken)
                pass
        try:
            return json.loads(got["body"])
        except ValueError as exc:
            raise BrokerError("reply is not valid JSON") from exc


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
CLEANUP = ("DELETE FROM mq_requests WHERE expires_at < now() - interval '1 minute'; "
           "DELETE FROM mq_replies WHERE expires_at < now()")
SEND = ("INSERT INTO mq_requests (queue, correlation_id, body, expires_at) "
        "VALUES (%s, %s, %s, now() + make_interval(secs => %s))")
TAKE_REPLY = "DELETE FROM mq_replies WHERE correlation_id = %s RETURNING body"
WITHDRAW = "DELETE FROM mq_requests WHERE correlation_id = %s"


class PostgresRequester:
    name = "postgres"

    def __init__(self, db):
        self._db = db
        self._schema_ready = False

    def _ensure_schema(self, conn):
        if not self._schema_ready:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            self._schema_ready = True

    def request(self, timeout):
        correlation_id = uuid.uuid4().hex
        try:
            with self._db.connection() as conn:
                conn.autocommit = True  # every statement is visible to the Fetcher at once
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(CLEANUP)
                    cur.execute(SEND, (REQUEST_QUEUE, correlation_id, json.dumps({"id": correlation_id}), timeout))
                    deadline = time.monotonic() + timeout
                    while True:
                        cur.execute(TAKE_REPLY, (correlation_id,))
                        row = cur.fetchone()
                        if row is not None:
                            break
                        if time.monotonic() >= deadline:
                            cur.execute(WITHDRAW, (correlation_id,))  # nobody took it: withdraw it
                            raise QueueTimeout("no answer in time")
                        time.sleep(POLL)
        except DatabaseUnavailable as exc:
            raise BrokerError(str(exc)) from exc
        try:
            return json.loads(row[0])
        except ValueError as exc:
            raise BrokerError("reply is not valid JSON") from exc


# ================================================================ factory
def make_requester(settings, db):
    if settings.queue_backend == "rabbitmq":
        return RabbitRequester(settings)
    if settings.queue_backend == "postgres":
        return PostgresRequester(db)
    raise ValueError(f"unknown queue backend {settings.queue_backend!r}")
