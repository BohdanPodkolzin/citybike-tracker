import json
import logging
import os
import time

log = logging.getLogger("fetcher.broker")

REQUEST_QUEUE = "fetch.requests"
LEASE = 30              # pgmq visibility timeout (s): a request is "ours" this long, then it is offered again
WAIT = 5                # seconds one pgmq.read_with_poll() waits inside PostgreSQL for a request
POLL_MS = 200           # how often read_with_poll() looks, in milliseconds
STALE_AFTER = 60        # seconds: a request older than this was abandoned by History
MAX_READS = 3           # a request that was handed out more often than this keeps killing its worker: drop it
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
REQUESTS = "fetch_requests"
REPLIES = "fetch_replies"

SCHEMA = f"""
SELECT pg_advisory_xact_lock(727401);  -- History and Fetcher may both set up at start
CREATE EXTENSION IF NOT EXISTS pgmq;
SELECT pgmq.create('{REQUESTS}');
SELECT pgmq.create('{REPLIES}')
"""

# take ONE request that is not expired and not leased by another worker (SKIP LOCKED: never wait)
CLAIM = (f"SELECT msg_id, read_ct, message::text, (now() - enqueued_at) > make_interval(secs => %s) "
         f"FROM pgmq.read_with_poll('{REQUESTS}', %s, 1, %s, %s)")
REPLY = f"SELECT pgmq.send('{REPLIES}', %s::jsonb)"
DONE = f"SELECT pgmq.delete('{REQUESTS}', %s::bigint)"
CLEANUP = (f"DELETE FROM pgmq.q_{REQUESTS} WHERE enqueued_at < now() - interval '{STALE_AFTER} seconds'; "
           f"DELETE FROM pgmq.q_{REPLIES} WHERE enqueued_at < now() - interval '{STALE_AFTER} seconds'")

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
                log.info("worker ready, waiting for requests in the pgmq queue %s", REQUESTS)
                idle = 0
                while True:

                    if self.process_one(conn, handle):
                        idle = 0
                        continue
                    idle += 1
                    if idle % 12 == 1:  
                        with conn, conn.cursor() as cur:
                            cur.execute(CLEANUP)
            except psycopg2.Error as exc: 
                log.warning("postgres problem: %s", exc)
                time.sleep(RETRY)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass

    def process_one(self, conn, handle):
        """Take one request, answer it. Returns False when the queue stayed empty."""
        with conn, conn.cursor() as cur: 
            cur.execute(CLAIM, (STALE_AFTER, LEASE, WAIT, POLL_MS))
            row = cur.fetchone()
        if row is None:
            return False
        msg_id, read_ct, body, stale = row
        if stale or read_ct > MAX_READS:
            log.warning("dropping request %s (%s)", msg_id,
                        "abandoned by History" if stale else f"handed out {read_ct} times")
            reply = None
        else:
            reply = _run(handle, body)
        with conn, conn.cursor() as cur:  
            if reply is not None:
                try:
                    correlation_id = str(json.loads(body)["id"])
                except (ValueError, KeyError, TypeError):
                    correlation_id = None
                if correlation_id is not None:
                    cur.execute(REPLY, (json.dumps({"id": correlation_id, "reply": reply}),))
            cur.execute(DONE, (msg_id,))
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

