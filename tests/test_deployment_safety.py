"""Tests for fail-closed Vercel data-service isolation."""

import pytest

from app.deployment_safety import validate_vercel_service_isolation


def _production_environment() -> dict[str, str]:
    """Return the minimum approved Production configuration."""
    return {
        "VERCEL_ENV": "production",
        "SERVICE_DEPLOYMENT_ENV": "production",
        "DATABASE_URL": "postgresql://user:secret@production.example/app",
        "PRODUCTION_DATABASE_HOST": "production.example",
    }


def _preview_environment() -> dict[str, str]:
    """Return the minimum isolated Preview configuration."""
    return {
        "VERCEL_ENV": "preview",
        "SERVICE_DEPLOYMENT_ENV": "preview",
        "DATABASE_URL": "postgresql://user:secret@preview.example/app",
        "PRODUCTION_DATABASE_HOST": "production.example",
    }


def test_production_accepts_only_the_approved_database_host() -> None:
    """Allow Production when DATABASE_URL uses the approved host."""
    environment = _production_environment()

    validate_vercel_service_isolation(environment)

    assert environment["DATABASE_URL"].endswith("production.example/app")


def test_production_rejects_an_unapproved_database_host() -> None:
    """Fail closed when Production points at an unexpected database host."""
    environment = _production_environment()
    environment["DATABASE_URL"] = "postgresql://user:secret@preview.example/app"

    with pytest.raises(RuntimeError, match="approved database host"):
        validate_vercel_service_isolation(environment)


def test_preview_rejects_production_url_even_with_preview_metadata() -> None:
    """Bind isolation to DATABASE_URL rather than a separately configured label."""
    environment = _preview_environment()
    environment["DATABASE_URL"] = "postgresql://user:secret@production.example/app"
    environment["DATABASE_SERVICE_ID"] = "neon-preview-branch"

    with pytest.raises(
        RuntimeError,
        match="Preview cannot use the Production database service",
    ) as error:
        validate_vercel_service_isolation(environment)

    assert "secret" not in str(error.value)
    assert "production.example" not in str(error.value)


def test_preview_requires_the_approved_production_host_reference() -> None:
    """Require the non-secret reference used to compare connection targets."""
    environment = _preview_environment()
    environment.pop("PRODUCTION_DATABASE_HOST")

    with pytest.raises(RuntimeError, match="PRODUCTION_DATABASE_HOST"):
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


def test_preview_rejects_debug_internal_and_test_routes() -> None:
    """Keep every helper route unavailable regardless of Preview data isolation."""
    forbidden = (
        "ENABLE_DEBUG_ROUTES",
        "ENABLE_INTERNAL_OPS_ROUTES",
        "TEST_ENVIRONMENT",
    )
    for variable_name in forbidden:
        environment = _preview_environment() | {variable_name: "true"}

        with pytest.raises(RuntimeError, match="cannot enable"):
            validate_vercel_service_isolation(environment)


def test_preview_forces_production_route_mounting_behavior() -> None:
    """Prevent the normal non-production debug router condition from matching Preview."""
    environment = _preview_environment() | {"ENVIRONMENT": "development"}

    validate_vercel_service_isolation(environment)

    assert environment["ENVIRONMENT"] == "production"


def test_ci_and_local_environments_are_unchanged() -> None:
    """Leave disposable CI and local services outside the Vercel guard."""
    environment = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5437/comic_pile_test",
        "REDIS_URL": "redis://localhost:6379/0",
    }

    validate_vercel_service_isolation(environment)

    assert environment["REDIS_URL"] == "redis://localhost:6379/0"


def test_vercel_development_environment_is_unchanged() -> None:
    """Leave Vercel development services outside the deployment guard."""
    environment = {
        "VERCEL_ENV": "development",
        "REDIS_URL": "redis://localhost:6379/0",
        "CACHE_ENABLED": "true",
    }

    validate_vercel_service_isolation(environment)

    assert environment["REDIS_URL"] == "redis://localhost:6379/0"
    assert environment["CACHE_ENABLED"] == "true"


def test_vercel_environment_identity_must_match_its_scope() -> None:
    """Catch variables accidentally copied between Production and Preview scopes."""
    environment = _preview_environment()
    environment["SERVICE_DEPLOYMENT_ENV"] = "production"

    with pytest.raises(RuntimeError, match="must match VERCEL_ENV"):
        validate_vercel_service_isolation(environment)
