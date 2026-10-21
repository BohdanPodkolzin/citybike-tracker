import json
import logging
import math
import time
import uuid

from db import DatabaseUnavailable

log = logging.getLogger("history.broker")

REQUEST_QUEUE = "fetch.requests"
REPLY_TO = "amq.rabbitmq.reply-to"   # RabbitMQ "direct reply-to": no reply queue to create or clean up
POLL_MS = 200                        # how often pgmq.read_with_poll() looks for the reply, in milliseconds


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
            if props.correlation_id == correlation_id:
                got["body"] = body

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


# ============================================================= PostgreSQL ====

REQUESTS = "fetch_requests"
REPLIES = "fetch_replies"
STALE_AFTER = 60       
REPLY_VT = 30         

SCHEMA = f"""
SELECT pg_advisory_xact_lock(727401);  -- History and Fetcher may both set up at start
CREATE EXTENSION IF NOT EXISTS pgmq;
SELECT pgmq.create('{REQUESTS}');
SELECT pgmq.create('{REPLIES}')
"""

CLEANUP = (f"DELETE FROM pgmq.q_{REQUESTS} WHERE enqueued_at < now() - interval '{STALE_AFTER} seconds'; "
           f"DELETE FROM pgmq.q_{REPLIES} WHERE enqueued_at < now() - interval '{STALE_AFTER} seconds'")
SEND = f"SELECT pgmq.send('{REQUESTS}', %s::jsonb)"
WAIT_REPLY = (f"SELECT msg_id, message::text FROM pgmq.read_with_poll('{REPLIES}', {REPLY_VT}, 1, %s, {POLL_MS}, %s::jsonb)")
DELETE_REPLY = f"SELECT pgmq.delete('{REPLIES}', %s::bigint)"
WITHDRAW = f"SELECT pgmq.delete('{REQUESTS}', %s::bigint)"


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
        mine = json.dumps({"id": correlation_id})
        try:
            with self._db.connection() as conn:
                conn.autocommit = True  
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(CLEANUP)
                    cur.execute(SEND, (mine,))
                    request_msg_id = cur.fetchone()[0]

                    cur.execute(WAIT_REPLY, (max(1, math.ceil(timeout)), mine))
                    row = cur.fetchone()
                    if row is None:
                        cur.execute(WITHDRAW, (request_msg_id,))  
                        raise QueueTimeout("no answer in time")
                    reply_msg_id, body = row
                    cur.execute(DELETE_REPLY, (reply_msg_id,))
        except DatabaseUnavailable as exc:
            raise BrokerError(str(exc)) from exc
        try:
            reply = json.loads(body)["reply"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BrokerError("reply is not valid JSON with a 'reply' field") from exc
        if not isinstance(reply, dict):
            raise BrokerError("reply is not an object")
        return reply


# ================================================================ factory
def make_requester(settings, db):
    if settings.queue_backend == "rabbitmq":
        return RabbitRequester(settings)
    if settings.queue_backend == "postgres":
        return PostgresRequester(db)
    raise ValueError(f"unknown queue backend {settings.queue_backend!r}")
