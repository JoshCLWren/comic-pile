"""Fail-closed deployment guards for Vercel data-service configuration."""

import os
from collections.abc import MutableMapping
from typing import Literal

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


def _validate_database_identity(
    environment: MutableMapping[str, str],
    vercel_environment: VercelEnvironment,
) -> None:
    """Prevent Production and Preview from sharing the same database identity."""
    if not environment.get("DATABASE_URL"):
        if vercel_environment == "production":
            raise RuntimeError("DATABASE_URL is required for a Production deployment")
        return

    service_id = environment.get("DATABASE_SERVICE_ID")
    production_service_id = environment.get("PRODUCTION_DATABASE_SERVICE_ID")
    if not service_id or not production_service_id:
        raise RuntimeError(
            "DATABASE_SERVICE_ID and PRODUCTION_DATABASE_SERVICE_ID are required "
            "for Vercel data-service isolation"
        )

    if vercel_environment == "production" and service_id != production_service_id:
        raise RuntimeError("Production DATABASE_SERVICE_ID does not match the approved service")
    if vercel_environment == "preview" and service_id == production_service_id:
        raise RuntimeError("Preview cannot use the Production database service")


def _disable_preview_redis(environment: MutableMapping[str, str]) -> None:
    """Remove every Redis credential before application configuration is imported."""
    for variable_name in _REMOTE_REDIS_VARIABLES:
        environment.pop(variable_name, None)
    environment["CACHE_ENABLED"] = "false"


def _reject_preview_internal_routes(environment: MutableMapping[str, str]) -> None:
    """Keep test-helper and internal operations routes unavailable in Preview."""
    forbidden = ("ENABLE_DEBUG_ROUTES", "ENABLE_INTERNAL_OPS_ROUTES")
    enabled = [name for name in forbidden if environment.get(name, "").lower() in {"1", "true", "yes"}]
    if enabled:
        raise RuntimeError("Preview deployments cannot enable debug or internal operations routes")


def validate_vercel_service_isolation(
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Validate Vercel service identities before importing application configuration.

    Args:
        environment: Mutable environment mapping. Defaults to ``os.environ``.

    Returns:
        None.

    Raises:
        RuntimeError: When Production or Preview service configuration is unsafe.
    """
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
