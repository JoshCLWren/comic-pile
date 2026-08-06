"""Helpers for logging configuration metadata without exposing credentials."""

from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

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
)


def safe_connection_metadata(connection_url: str) -> dict[str, str | int | bool | None]:
    """Return non-secret connection metadata suitable for structured logs.

    Args:
        connection_url: A database, Redis, or HTTP connection URL.

    Returns:
        Metadata containing only the scheme, host, port, database/path, and SSL mode.
    """
    parsed = urlsplit(connection_url)
    path = unquote(parsed.path.lstrip("/")) or None
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in parsed.query.split("&")
        if part
    )
    ssl_value = query.get("sslmode") or query.get("ssl")
    ssl_required = ssl_value not in {None, "", "0", "false", "disable"}
    return {
        "scheme": parsed.scheme or None,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": path,
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
