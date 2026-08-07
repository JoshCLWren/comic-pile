"""Tests for credential-safe structured logging helpers."""

import logging

import pytest

from app.safe_logging import (
    redact_sensitive_values,
    safe_connection_metadata,
    safe_exception_metadata,
)


def test_connection_metadata_omits_credentials_and_query_values() -> None:
    """Connection metadata must expose only allowlisted operational fields."""
    database_url = (
        "postgresql+asyncpg://comic_user:database-password@ep-example.neon.tech:5432/"
        "comic_pile?sslmode=require&token=redis-token"
    )

    metadata = safe_connection_metadata(database_url)

    assert metadata == {
        "scheme": "postgresql+asyncpg",
        "host": "ep-example.neon.tech",
        "port": 5432,
        "database": "comic_pile",
        "ssl_required": True,
    }
    rendered = repr(metadata)
    assert "comic_user" not in rendered
    assert "database-password" not in rendered
    assert "redis-token" not in rendered


def test_connection_metadata_handles_opaque_http_paths() -> None:
    """Opaque HTTP paths may contain tokens and must not be logged as database names."""
    metadata = safe_connection_metadata(
        "https://api.example.test/redis-token-that-must-not-log?authorization=secret"
    )

    assert metadata == {
        "scheme": "https",
        "host": "api.example.test",
        "port": None,
        "database": None,
        "ssl_required": True,
    }
    rendered = repr(metadata)
    assert "redis-token" not in rendered
    assert "authorization" not in rendered
    assert "secret" not in rendered


def test_connection_metadata_treats_redis_tls_correctly() -> None:
    """Redis TLS metadata must distinguish redis and rediss schemes."""
    assert safe_connection_metadata("redis://localhost:6379/0")["ssl_required"] is False
    assert safe_connection_metadata("rediss://cache.example.test:6379/0")["ssl_required"] is True


def test_connection_metadata_treats_postgres_sslmode_correctly() -> None:
    """PostgreSQL TLS metadata must honor disabling and requiring sslmode values."""
    assert (
        safe_connection_metadata("postgresql://db.example.test/app?sslmode=disable")[
            "ssl_required"
        ]
        is False
    )
    assert (
        safe_connection_metadata("postgresql://db.example.test/app?sslmode=require")[
            "ssl_required"
        ]
        is True
    )


def test_connection_metadata_survives_invalid_ports() -> None:
    """Malformed URLs must produce safe empty metadata rather than crashing diagnostics."""
    metadata = safe_connection_metadata("postgresql://db.example.test:not-a-port/app")

    assert metadata == {
        "scheme": "postgresql",
        "host": "db.example.test",
        "port": None,
        "database": "app",
        "ssl_required": None,
    }


def test_redaction_handles_secret_keys_and_connection_urls() -> None:
    """Secret-shaped values and connection URLs must be redacted recursively."""
    values = {
        "DATABASE_URL": "postgresql://user:password@example.test/app",
        "UPSTASH_REDIS_REST_TOKEN": "redis-token",
        "nested": {
            "authorization": "Bearer private-token",
            "safe": "visible",
        },
    }

    redacted = redact_sensitive_values(values)

    assert redacted == {
        "DATABASE_URL": "[REDACTED]",
        "UPSTASH_REDIS_REST_TOKEN": "[REDACTED]",
        "nested": {
            "authorization": "[REDACTED]",
            "safe": "visible",
        },
    }


def test_redaction_handles_encoded_credentials() -> None:
    """Encoded URL credentials must not survive redaction or rendered metadata."""
    raw_password = "encoded/password"
    encoded_password = "encoded%2Fpassword"
    values = {
        "DATABASE_URL": f"postgresql://user:{encoded_password}@db.example.test/app",
        "REDIS_URL": f"rediss://default:{encoded_password}@cache.example.test:6379/0",
        "TOKEN": raw_password,
        "CONNECTION_URL": f"https://api.example.test/{encoded_password}",
    }

    redacted = redact_sensitive_values(values)
    rendered = repr(redacted)

    assert raw_password not in rendered
    assert encoded_password not in rendered
    assert "encoded/password" not in rendered
    assert rendered.count("[REDACTED]") == 4


def test_exception_metadata_does_not_serialize_secret_message() -> None:
    """Dependency exceptions may contain full URLs and must log only their type."""
    password = "encoded%2Fdatabase-password"
    error = RuntimeError(
        f"could not connect to postgresql://user:{password}@db.example.test/comic_pile"
    )

    metadata = safe_exception_metadata(error)

    assert metadata == {"error_type": "RuntimeError"}
    assert password not in repr(metadata)
    assert "db.example.test" not in repr(metadata)


def test_emitted_logs_exclude_connection_and_exception_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The actual structured log records must never serialize credential-shaped values."""
    logger = logging.getLogger("tests.safe_logging")
    database_password = "database-password-that-must-not-log"
    redis_token = "redis-token-that-must-not-log"
    database_url = (
        "postgresql+asyncpg://comic_user:"
        f"{database_password}@ep-example.neon.tech/comic_pile"
        f"?sslmode=require&token={redis_token}"
    )
    error = RuntimeError(f"connection failed for {database_url}")

    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info(
            "Database configured",
            extra={"database": safe_connection_metadata(database_url)},
        )
        logger.error(
            "Database connection test failed",
            extra={"database_error": safe_exception_metadata(error)},
        )

    rendered_records = repr(caplog.records)
    assert database_password not in caplog.text
    assert redis_token not in caplog.text
    assert "comic_user" not in caplog.text
    assert database_password not in rendered_records
    assert redis_token not in rendered_records
    assert "comic_user" not in rendered_records
    assert caplog.records[0].__dict__.get("database") == {
        "scheme": "postgresql+asyncpg",
        "host": "ep-example.neon.tech",
        "port": None,
        "database": "comic_pile",
        "ssl_required": True,
    }
    assert caplog.records[1].__dict__.get("database_error") == {
        "error_type": "RuntimeError"
    }
