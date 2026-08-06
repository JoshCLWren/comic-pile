"""Fail-closed deployment guards for Vercel data-service configuration."""

import os
from collections.abc import MutableMapping
from typing import Literal
from urllib.parse import urlsplit

VercelEnvironment = Literal["production", "preview", "development"]
_REMOTE_REDIS_VARIABLES = (
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
    "REDIS_URL",
)


def _require_environment_identity(
    environment: MutableMapping[str, str],
    vercel_environment: VercelEnvironment,
) -> None:
    """Require the operator-managed deployment identity to match Vercel."""
    configured_environment = environment.get("SERVICE_DEPLOYMENT_ENV")
    if configured_environment != vercel_environment:
        raise RuntimeError(
            "SERVICE_DEPLOYMENT_ENV must match VERCEL_ENV; configure it separately "
            "for Production and Preview"
        )


def _database_host(database_url: str) -> str:
    """Return the normalized connection host without exposing credentials."""
    host = urlsplit(database_url).hostname
    if not host:
        raise RuntimeError("DATABASE_URL must include a valid database host")
    return host.lower().rstrip(".")


def _validate_database_identity(
    environment: MutableMapping[str, str],
    vercel_environment: VercelEnvironment,
) -> None:
    """Bind Production and Preview checks to the actual connection target."""
    database_url = environment.get("DATABASE_URL")
    if not database_url:
        if vercel_environment == "production":
            raise RuntimeError("DATABASE_URL is required for a Production deployment")
        return

    production_host = environment.get("PRODUCTION_DATABASE_HOST")
    if not production_host:
        raise RuntimeError(
            "PRODUCTION_DATABASE_HOST is required for Vercel data-service isolation"
        )

    connection_host = _database_host(database_url)
    approved_production_host = production_host.lower().rstrip(".")
    if vercel_environment == "production" and connection_host != approved_production_host:
        raise RuntimeError("Production DATABASE_URL does not use the approved database host")
    if vercel_environment == "preview" and connection_host == approved_production_host:
        raise RuntimeError("Preview cannot use the Production database service")


def _disable_preview_redis(environment: MutableMapping[str, str]) -> None:
    """Remove every Redis credential before application configuration is imported."""
    for variable_name in _REMOTE_REDIS_VARIABLES:
        environment.pop(variable_name, None)
    environment["CACHE_ENABLED"] = "false"


def _reject_preview_internal_routes(environment: MutableMapping[str, str]) -> None:
    """Keep test-helper and internal operations routes unavailable in Preview."""
    forbidden = (
        "ENABLE_DEBUG_ROUTES",
        "ENABLE_INTERNAL_OPS_ROUTES",
        "TEST_ENVIRONMENT",
    )
    enabled = [
        name
        for name in forbidden
        if environment.get(name, "").lower() in {"1", "true", "yes"}
    ]
    if enabled:
        raise RuntimeError("Preview deployments cannot enable debug or internal operations routes")


def validate_vercel_service_isolation(
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Validate Vercel service identities before importing application configuration."""
    values = os.environ if environment is None else environment
    raw_vercel_environment = values.get("VERCEL_ENV")
    if raw_vercel_environment not in {"production", "preview", "development"}:
        return

    vercel_environment: VercelEnvironment = raw_vercel_environment
    if vercel_environment == "development":
        return

    _require_environment_identity(values, vercel_environment)
    _validate_database_identity(values, vercel_environment)

    if vercel_environment == "preview":
        _reject_preview_internal_routes(values)
        _disable_preview_redis(values)
        # Preview must behave like Production for route mounting even when it uses isolated data.
        values["ENVIRONMENT"] = "production"
