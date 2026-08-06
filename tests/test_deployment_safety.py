"""Tests for fail-closed Vercel data-service isolation."""

import pytest

from app.deployment_safety import validate_vercel_service_isolation


def _production_environment() -> dict[str, str]:
    """Return the minimum approved Production configuration."""
    return {
        "VERCEL_ENV": "production",
        "SERVICE_DEPLOYMENT_ENV": "production",
        "DATABASE_URL": "postgresql://user:secret@production.example/app",
        "DATABASE_SERVICE_ID": "neon-production-main",
        "PRODUCTION_DATABASE_SERVICE_ID": "neon-production-main",
    }


def _preview_environment() -> dict[str, str]:
    """Return the minimum isolated Preview configuration."""
    return {
        "VERCEL_ENV": "preview",
        "SERVICE_DEPLOYMENT_ENV": "preview",
        "DATABASE_URL": "postgresql://user:secret@preview.example/app",
        "DATABASE_SERVICE_ID": "neon-preview-branch",
        "PRODUCTION_DATABASE_SERVICE_ID": "neon-production-main",
    }


def test_production_accepts_only_the_approved_database_identity() -> None:
    """Allow Production when its stable service identity matches the approved value."""
    environment = _production_environment()

    validate_vercel_service_isolation(environment)

    assert environment["DATABASE_URL"].endswith("production.example/app")


def test_production_rejects_an_unapproved_database_identity() -> None:
    """Fail closed when Production points at an unexpected database service."""
    environment = _production_environment()
    environment["DATABASE_SERVICE_ID"] = "neon-preview-branch"

    with pytest.raises(RuntimeError, match="approved service"):
        validate_vercel_service_isolation(environment)


def test_preview_rejects_the_production_database_identity_without_logging_values() -> None:
    """Block Preview from starting against the Production Neon service."""
    environment = _preview_environment()
    environment["DATABASE_SERVICE_ID"] = environment["PRODUCTION_DATABASE_SERVICE_ID"]

    with pytest.raises(RuntimeError, match="Preview cannot use the Production database service") as error:
        validate_vercel_service_isolation(environment)

    assert "secret" not in str(error.value)
    assert "production.example" not in str(error.value)


def test_preview_requires_explicit_service_identity_metadata() -> None:
    """Do not trust a Preview database URL without stable non-secret identity metadata."""
    environment = _preview_environment()
    environment.pop("DATABASE_SERVICE_ID")

    with pytest.raises(RuntimeError, match="DATABASE_SERVICE_ID"):
        validate_vercel_service_isolation(environment)


def test_preview_removes_all_redis_credentials_and_disables_cache() -> None:
    """Ensure Preview cannot contact Upstash even when credentials were inherited."""
    environment = _preview_environment() | {
        "UPSTASH_REDIS_REST_URL": "https://production-upstash.example",
        "UPSTASH_REDIS_REST_TOKEN": "production-token",
        "REDIS_URL": "redis://production.example:6379/0",
        "CACHE_ENABLED": "true",
    }

    validate_vercel_service_isolation(environment)

    assert "UPSTASH_REDIS_REST_URL" not in environment
    assert "UPSTASH_REDIS_REST_TOKEN" not in environment
    assert "REDIS_URL" not in environment
    assert environment["CACHE_ENABLED"] == "false"


def test_preview_rejects_debug_and_internal_routes() -> None:
    """Keep helper routes unavailable regardless of Preview data isolation."""
    for variable_name in ("ENABLE_DEBUG_ROUTES", "ENABLE_INTERNAL_OPS_ROUTES"):
        environment = _preview_environment() | {variable_name: "true"}

        with pytest.raises(RuntimeError, match="cannot enable"):
            validate_vercel_service_isolation(environment)


def test_ci_and_local_environments_are_unchanged() -> None:
    """Leave disposable CI and local services outside the Vercel guard."""
    environment = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5437/comic_pile_test",
        "REDIS_URL": "redis://localhost:6379/0",
    }

    validate_vercel_service_isolation(environment)

    assert environment["REDIS_URL"] == "redis://localhost:6379/0"


def test_vercel_environment_identity_must_match_its_scope() -> None:
    """Catch variables accidentally copied between Production and Preview scopes."""
    environment = _preview_environment()
    environment["SERVICE_DEPLOYMENT_ENV"] = "production"

    with pytest.raises(RuntimeError, match="must match VERCEL_ENV"):
        validate_vercel_service_isolation(environment)
