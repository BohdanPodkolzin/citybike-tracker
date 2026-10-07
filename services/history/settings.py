"""History service configuration. Everything comes from environment variables."""

import os
from dataclasses import dataclass, field
 
 
class ConfigError(Exception):
    """A required setting is missing or invalid. Fix the environment, not the code."""
 
 # do not start the app without required vars
def _required(env, name):
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value
 
 # cast - int | float. minimum - min allowed value
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
 
 
# kw_only: fields may be declared in any order (required and optional mixed)
@dataclass(frozen=True, kw_only=True)
class Settings:
    db_host: str
    db_name: str
    db_user: str
    db_password: str = field(repr=False)  # never printed in logs or tracebacks
    redis_host: str
    redis_password: str = field(repr=False)
    db_port: int = 5432
    redis_port: int = 6379
    poll_interval: float = 60.0
    request_timeout: float = 10.0
    db_connect_timeout: int = 5
    host: str = "0.0.0.0"
    port: int = 8002

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            db_host=_required(env, "DB_HOST"),
            db_name=_required(env, "DB_NAME"),
            db_user=_required(env, "DB_USER"),
            db_password=_required(env, "DB_PASSWORD"),
            redis_host=_required(env, "REDIS_HOST"),
            redis_password=_required(env, "REDIS_PASSWORD"),
            db_port=_number(env, "DB_PORT", 5432, int, 1),
            redis_port=_number(env, "REDIS_PORT", 6379, int, 1),
            poll_interval=_number(env, "POLL_INTERVAL", 60.0, float, 5),
            request_timeout=_number(env, "REQUEST_TIMEOUT", 10.0, float, 1),
            db_connect_timeout=_number(env, "DB_CONNECT_TIMEOUT", 5, int, 1),
            host=(env.get("HOST") or "0.0.0.0").strip(),
            port=_number(env, "PORT", 8002, int, 1),
        )
