import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    """A required setting is missing or invalid. Fix the environment, not the code."""


def _required(env, name):
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _number(env, name, default, cast, minimum):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


QUEUE_BACKENDS = ("rabbitmq", "postgres")
CACHE_BACKENDS = ("redis", "postgres")


def _choice(env, name, allowed, default):
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}, got {raw!r}")
    return raw


def _optional(env, name):
    return (env.get(name) or "").strip()


# kw_only: fields may be declared in any order (required and optional mixed)
@dataclass(frozen=True, kw_only=True)
class Settings:
    db_host: str
    db_name: str
    db_user: str
    db_password: str = field(repr=False)  # never printed in logs or tracebacks
    queue_backend: str = "rabbitmq"
    cache_backend: str = "redis"
    redis_host: str = ""
    redis_password: str = field(default="", repr=False)
    redis_port: int = 6379
    rabbitmq_host: str = ""
    rabbitmq_user: str = ""
    rabbitmq_password: str = field(default="", repr=False)
    rabbitmq_port: int = 5672
    rabbitmq_vhost: str = "citybikes"
    db_port: int = 5432
    poll_interval: float = 60.0
    request_timeout: float = 10.0
    db_connect_timeout: int = 5
    host: str = "0.0.0.0"
    port: int = 8002

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        queue = _choice(env, "QUEUE_BACKEND", QUEUE_BACKENDS, "rabbitmq")
        cache = _choice(env, "CACHE_BACKEND", CACHE_BACKENDS, "redis")
        # a backend's own settings are required only when that backend is chosen
        pick = _required if queue == "rabbitmq" else _optional
        pick_redis = _required if cache == "redis" else _optional
        return cls(
            queue_backend=queue,
            cache_backend=cache,
            rabbitmq_host=pick(env, "RABBITMQ_HOST"),
            rabbitmq_user=pick(env, "RABBITMQ_USER"),
            rabbitmq_password=pick(env, "RABBITMQ_PASSWORD"),
            rabbitmq_port=_number(env, "RABBITMQ_PORT", 5672, int, 1),
            rabbitmq_vhost=_optional(env, "RABBITMQ_VHOST") or "citybikes",
            redis_host=pick_redis(env, "REDIS_HOST"),
            redis_password=pick_redis(env, "REDIS_PASSWORD"),
            db_host=_required(env, "DB_HOST"),
            db_name=_required(env, "DB_NAME"),
            db_user=_required(env, "DB_USER"),
            db_password=_required(env, "DB_PASSWORD"),
            db_port=_number(env, "DB_PORT", 5432, int, 1),
            redis_port=_number(env, "REDIS_PORT", 6379, int, 1),
            poll_interval=_number(env, "POLL_INTERVAL", 60.0, float, 5),
            request_timeout=_number(env, "REQUEST_TIMEOUT", 10.0, float, 1),
            db_connect_timeout=_number(env, "DB_CONNECT_TIMEOUT", 5, int, 1),
            host=(env.get("HOST") or "0.0.0.0").strip(),
            port=_number(env, "PORT", 8002, int, 1),
        )
