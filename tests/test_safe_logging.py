"""Regression tests for credential-safe configuration logging."""

import logging

import pytest

from app.safe_logging import (
    redact_sensitive_values,
    safe_connection_metadata,
    safe_exception_metadata,
)


def test_connection_metadata_excludes_database_credentials() -> None:
    """Database metadata must not preserve userinfo or query credentials."""
    password = "p%40ssword-super-secret"
    token = "neon-token-should-never-log"
    url = (
        f"postgresql+asyncpg://comic_user:{password}@ep-example.us-east-2.aws.neon.tech/"
        f"comic_pile?sslmode=require&token={token}"
    )

    metadata = safe_connection_metadata(url)
    rendered = repr(metadata)

    assert metadata == {
        "scheme": "postgresql+asyncpg",
        "host": "ep-example.us-east-2.aws.neon.tech",
        "port": None,
        "database": "comic_pile",
        "ssl_required": True,
    }
    assert "comic_user" not in rendered
    assert password not in rendered
    assert "p@ssword-super-secret" not in rendered
    assert token not in rendered


def test_connection_metadata_excludes_redis_token_and_userinfo() -> None:
    """Redis metadata must expose only its non-secret network identity."""
    token = "upstash-rest-token-value"
    metadata = safe_connection_metadata(
        f"rediss://default:{token}@actual-mantis-12345.upstash.io:6379/0"
    )
    rendered = repr(metadata)

    assert metadata == {
        "scheme": "rediss",
        "host": "actual-mantis-12345.upstash.io",
        "port": 6379,
        "database": "0",
        "ssl_required": False,
    }
    assert "default" not in rendered
    assert token not in rendered


def test_redact_sensitive_values_handles_nested_configuration() -> None:
    """Known secret fields must be removed from nested structured logs."""
    values = {
        "environment": "production",
        "database": {
            "host": "db.example.test",
            "password": "database-secret",
        },
        "redis_token": "redis-secret",
        "authorization": "Bearer jwt-secret",
        "nested": [{"github_api_key": "github-secret"}],
    }

    redacted = redact_sensitive_values(values)
    rendered = repr(redacted)

    assert "db.example.test" in rendered
    assert "production" in rendered
    assert "database-secret" not in rendered
    assert "redis-secret" not in rendered
    assert "jwt-secret" not in rendered
    assert "github-secret" not in rendered
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
    assert caplog.records[0].database == {
        "scheme": "postgresql+asyncpg",
        "host": "ep-example.neon.tech",
        "port": None,
        "database": "comic_pile",
        "ssl_required": True,
    }
    assert caplog.records[1].database_error == {"error_type": "RuntimeError"}
