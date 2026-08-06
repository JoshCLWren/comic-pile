"""Helpers for logging configuration metadata without exposing credentials."""

from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

_SECRET_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "database_url",
    "redis_url",
    "connection_url",
)
_DATABASE_SCHEMES = {
    "postgres",
    "postgresql",
    "postgresql+asyncpg",
    "postgresql+psycopg",
    "postgresql+psycopg2",
    "redis",
    "rediss",
}
_TLS_REQUIRED_MODES = {"require", "verify-ca", "verify-full"}
_EMPTY_CONNECTION_METADATA: dict[str, str | int | bool | None] = {
    "scheme": None,
    "host": None,
    "port": None,
    "database": None,
    "ssl_required": False,
}


def safe_connection_metadata(connection_url: str) -> dict[str, str | int | bool | None]:
    """Return non-secret connection metadata suitable for structured logs.

    Args:
        connection_url: A database, Redis, or HTTP connection URL.

    Returns:
        Metadata containing only the scheme, host, port, validated database name,
        and whether the connection requires TLS. Malformed URLs return empty metadata
        so diagnostic logging cannot break application startup.
    """
    try:
        parsed = urlsplit(connection_url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return _EMPTY_CONNECTION_METADATA.copy()

    database = (
        unquote(parsed.path.lstrip("/")) or None
        if scheme in _DATABASE_SCHEMES
        else None
    )
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    ssl_value = (query.get("sslmode") or query.get("ssl") or "").lower()
    ssl_required = scheme == "rediss" or ssl_value in _TLS_REQUIRED_MODES
    return {
        "scheme": parsed.scheme or None,
        "host": host,
        "port": port,
        "database": database,
        "ssl_required": ssl_required,
    }


def redact_sensitive_values(value: object) -> object:
    """Recursively replace secret-bearing mapping values before logging.

    Args:
        value: Arbitrary structured value intended for a log event.

    Returns:
        A structurally similar value with secret-bearing fields redacted.
    """
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if any(marker in str(key).lower() for marker in _SECRET_MARKERS)
                else redact_sensitive_values(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_values(item) for item in value)
    return value


def safe_exception_metadata(error: BaseException) -> dict[str, str]:
    """Return exception metadata without serializing its potentially secret message.

    Args:
        error: Exception raised while handling configuration or a dependency.

    Returns:
        The exception type only.
    """
    return {"error_type": type(error).__name__}
