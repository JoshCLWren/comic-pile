"""Centralized application configuration using Pydantic Settings.

This module consolidates all environment variables used throughout the application.
Configuration is validated at startup and provides type-safe access to settings.
"""

import os
import secrets
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PLACEHOLDER_SECRET_VALUES = frozenset(
    {
        "",
        "[SENSITIVE]",
        "<redacted>",
        "redacted",
        "undefined",
        "null",
    }
)


def _usable_secret(value: str | None) -> str | None:
    """Return a stripped secret, ignoring empty and placeholder values.

    Args:
        value: Candidate environment or settings value.

    Returns:
        The usable secret, or ``None``.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in _PLACEHOLDER_SECRET_VALUES:
        return None
    if stripped == "[SENSITIVE]":
        return None
    return stripped


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    database_url: str = Field(
        default_factory=lambda: (
            os.environ.get("DATABASE_URL")
            or "postgresql://postgres:postgres@localhost:5432/comic_pile_test"
        ),
        description="PostgreSQL database connection URL",
        json_schema_extra={"env": "DATABASE_URL"},
    )
    test_database_url: str | None = Field(
        default=None,
        description="Database URL for testing (overrides DATABASE_URL in tests)",
        json_schema_extra={"env": "TEST_DATABASE_URL"},
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def use_test_database_url(cls, v: str) -> str:
        """Use test database URL if in test environment."""
        if get_app_settings().environment == "test":
            test_url = os.getenv("TEST_DATABASE_URL")
            if test_url:
                return test_url
        if not v:
            raise ValueError("DATABASE_URL is required")
        return v

    @property
    def async_url(self) -> str:
        """Get the asynchronous database URL with asyncpg driver."""
        url = (
            self.test_database_url
            if get_app_settings().environment == "test" and self.test_database_url
            else self.database_url
        )
        if url.startswith("postgresql+asyncpg://"):
            return url
        elif url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url


class AuthSettings(BaseSettings):
    """Authentication and security settings."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    secret_key: str = Field(
        default="",
        description="Secret key for JWT token signing (required)",
        json_schema_extra={"env": "SECRET_KEY"},
    )
    algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    access_token_expire_minutes: int = Field(
        default=720,
        description=(
            "Access token expiration time in minutes. Default is 12 hours so tab "
            "focus and concurrent React Query traffic do not constantly trip "
            "refresh; the httpOnly refresh cookie remains the durable session."
        ),
        json_schema_extra={"env": "ACCESS_TOKEN_EXPIRE_MINUTES"},
    )
    refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration time in days",
        json_schema_extra={"env": "REFRESH_TOKEN_EXPIRE_DAYS"},
    )

    @field_validator("secret_key", mode="before")
    @classmethod
    def validate_secret_key(cls, v: str | None) -> str:
        """Require explicit secret key in production, use it in test mode, randomize in development."""
        environment = os.environ.get("ENVIRONMENT", "development")
        if environment == "production":
            if v and v.strip():
                return v
            raise ValueError("SECRET_KEY must be set in production mode")
        if environment == "test" and v and v.strip():
            return v
        return secrets.token_urlsafe(48)


class AppSettings(BaseSettings):
    """General application settings."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    environment: Literal["development", "staging", "production", "test"] = Field(
        default="development",
        description="Application environment",
        json_schema_extra={"env": "ENVIRONMENT"},
    )
    cors_origins: str | None = Field(
        default=None,
        description="Comma-separated list of allowed CORS origins",
        json_schema_extra={"env": "CORS_ORIGINS"},
    )
    enable_debug_routes: bool = Field(
        default=False,
        description="Enable debug routes (should be False in production)",
        json_schema_extra={"env": "ENABLE_DEBUG_ROUTES"},
    )
    enable_internal_ops_routes: bool = Field(
        default=False,
        description="Enable internal operations routes",
        json_schema_extra={"env": "ENABLE_INTERNAL_OPS_ROUTES"},
    )
    legacy_dependency_blocking_enabled: bool = Field(
        default=True,
        description=(
            "Keep the raw Dependency Roll compatibility path enabled until the "
            "reader-order migration cutover audit passes in production"
        ),
        json_schema_extra={"env": "LEGACY_DEPENDENCY_BLOCKING_ENABLED"},
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Get CORS origins as a list."""
        if not self.cors_origins or not self.cors_origins.strip():
            if self.environment == "production":
                raise RuntimeError("CORS_ORIGINS must be set in production")
            return ["*"]
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        if self.environment == "production" and "*" in origins:
            raise RuntimeError("Wildcard CORS not allowed in production")
        return origins

    def validate_production_cors(self) -> None:
        """Validate that CORS is properly configured in production."""
        if self.environment == "production":
            if not self.cors_origins or not self.cors_origins.strip():
                raise RuntimeError("CORS_ORIGINS must be set in production mode")


class SessionSettings(BaseSettings):
    """Reading session configuration settings."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    session_gap_hours: int = Field(
        default=6,
        description="Hours of inactivity before starting a new session (1-168)",
        json_schema_extra={"env": "SESSION_GAP_HOURS"},
    )
    start_die: int = Field(
        default=6,
        description="Starting die size for new sessions (4-20)",
        json_schema_extra={"env": "START_DIE"},
    )

    @field_validator("session_gap_hours")
    @classmethod
    def validate_session_gap_hours(cls, v: int) -> int:
        """Ensure session gap hours is within valid range."""
        if not 1 <= v <= 168:
            raise ValueError(f"SESSION_GAP_HOURS must be between 1 and 168 hours (1 week), got {v}")
        return v

    @field_validator("start_die")
    @classmethod
    def validate_start_die(cls, v: int) -> int:
        """Ensure start die is within valid range."""
        if not 4 <= v <= 20:
            raise ValueError(f"START_DIE must be between 4 and 20, got {v}")
        return v


class RatingSettings(BaseSettings):
    """Rating system configuration settings."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    rating_min: float = Field(
        default=0.5,
        description="Minimum allowed rating value (0.0-5.0)",
        json_schema_extra={"env": "RATING_MIN"},
    )
    rating_max: float = Field(
        default=5.0,
        description="Maximum allowed rating value (0.5-5.0)",
        json_schema_extra={"env": "RATING_MAX"},
    )
    rating_threshold: float = Field(
        default=4.0,
        description="Threshold for 'good' rating that moves thread to front (0.5-5.0)",
        json_schema_extra={"env": "RATING_THRESHOLD"},
    )

    @field_validator("rating_min")
    @classmethod
    def validate_rating_min(cls, v: float) -> float:
        """Ensure rating min is within valid range."""
        if not 0.0 <= v <= 5.0:
            raise ValueError(f"RATING_MIN must be between 0.0 and 5.0, got {v}")
        return v

    @field_validator("rating_max")
    @classmethod
    def validate_rating_max(cls, v: float) -> float:
        """Ensure rating max is within valid range."""
        if not 0.5 <= v <= 5.0:
            raise ValueError(f"RATING_MAX must be between 0.5 and 5.0, got {v}")
        return v

    @field_validator("rating_threshold")
    @classmethod
    def validate_rating_threshold(cls, v: float) -> float:
        """Ensure rating threshold is within valid range."""
        if not 0.5 <= v <= 5.0:
            raise ValueError(f"RATING_THRESHOLD must be between 0.5 and 5.0, got {v}")
        return v


class RecommendationSettings(BaseSettings):
    """Recommendation-quality diagnostics and algorithm versioning settings.

    The canonical version and control-mode identifiers live in
    :mod:`comic_pile.recommendation_version` and are shared by selection,
    decision snapshots, diagnostics, and metrics so they cannot drift. See
    Phase 9 (issue #1767) for the safe-legacy-rollback contract these settings
    control.
    """

    model_config = SettingsConfigDict(
        env_file=[".env.test", ".env", ".envrc"],
        extra="ignore",
        populate_by_name=True,
    )

    algorithm_version: str = Field(
        default="v1-contextual",
        description=(
            "Canonical recommendation algorithm version identifier (single source "
            "of truth in comic_pile/recommendation_version.py) used in diagnostics "
            "and decision snapshots"
        ),
        validation_alias=AliasChoices(
            "RECOMMENDATION_ALGORITHM_VERSION",
            "algorithm_version",
        ),
    )
    control_mode: Literal["contextual", "legacy"] = Field(
        default="contextual",
        description=(
            "Active recommendation control mode (vocabulary owned by "
            "comic_pile/recommendation_version.py). 'legacy' forces unweighted "
            "selection while leaving instrumentation active."
        ),
        validation_alias=AliasChoices("RECOMMENDATION_CONTROL_MODE", "control_mode"),
    )


class GitHubSettings(BaseSettings):
    """GitHub integration settings for bug reporting."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    github_token: str = Field(
        default="",
        description="GitHub personal access token with repo scope",
        json_schema_extra={"env": "GITHUB_TOKEN"},
    )
    github_repo_owner: str = Field(
        default="",
        description="GitHub repository owner",
        json_schema_extra={"env": "GITHUB_REPO_OWNER"},
    )
    github_repo_name: str = Field(
        default="",
        description="GitHub repository name",
        json_schema_extra={"env": "GITHUB_REPO_NAME"},
    )
    latticery_token: str = Field(
        default="",
        description="Dedicated GitHub PAT for JoshCLWren/Latticery cross-repository delivery operations (requires repo scope)",
        json_schema_extra={"env": "LATTICERY_TOKEN"},
    )
    allowed_target_repos: list[str] = Field(
        default_factory=lambda: ["JoshCLWren/comic-pile", "JoshCLWren/Latticery"],
        description="Allowlisted target repositories for cross-repo factory delivery",
        json_schema_extra={"env": "ALLOWED_TARGET_REPOS"},
    )

    @property
    def is_configured(self) -> bool:
        """Return True if all GitHub settings are set with non-whitespace values."""
        return bool(
            self.github_token.strip()
            and self.github_repo_owner.strip()
            and self.github_repo_name.strip()
        )

    @property
    def is_latticery_configured(self) -> bool:
        """Return True if the LATTICERY_TOKEN is available for cross-repo delivery."""
        return bool(self.latticery_token.strip())

    @property
    def default_target_repo(self) -> str:
        """Return the default target repository (ComicPile itself)."""
        if self.github_repo_owner.strip() and self.github_repo_name.strip():
            return f"{self.github_repo_owner}/{self.github_repo_name}"
        return "JoshCLWren/comic-pile"

    def validate_target_repo(self, target_repo: str) -> str:
        """Validate that a target repository is allowlisted.

        Args:
            target_repo: The target repository string (owner/name).

        Returns:
            The validated target repository string.

        Raises:
            ValueError: If the target repository is not allowlisted.
        """
        if target_repo not in self.allowed_target_repos:
            raise ValueError(
                f"Target repository '{target_repo}' is not allowlisted. "
                f"Allowed: {self.allowed_target_repos}"
            )
        return target_repo

    def get_credential_for_repo(self, target_repo: str) -> str:
        """Get the appropriate GitHub token for a target repository.

        Args:
            target_repo: The target repository string (owner/name).

        Returns:
            The GitHub token string for the target repository.

        Raises:
            ValueError: If the target repository is not allowlisted.
            RuntimeError: If LATTICERY_TOKEN is required but unavailable.
        """
        self.validate_target_repo(target_repo)
        if target_repo == "JoshCLWren/Latticery":
            if not self.is_latticery_configured:
                raise RuntimeError(
                    "LATTICERY_TOKEN is required for JoshCLWren/Latticery delivery "
                    "but is not configured. Fail-closed."
                )
            return self.latticery_token
        return self.github_token


class EmailSettings(BaseSettings):
    """Outbound email configuration settings (issue #2778).

    Resend is the selected outbound email provider for password-reset
    delivery. All three core values are deployment configuration, never
    source literals. Placeholder values are treated as missing.
    """

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    resend_api_key: str = Field(
        default="",
        description="Resend API key for outbound email (RESEND_API_KEY)",
        json_schema_extra={"env": "RESEND_API_KEY"},
    )
    password_reset_sender: str = Field(
        default="",
        description=(
            "Verified sender identity for password-reset mail, e.g. "
            "'Comic Pile <no-reply@example.com>' (PASSWORD_RESET_SENDER)"
        ),
        json_schema_extra={"env": "PASSWORD_RESET_SENDER"},
    )
    password_reset_origin: str = Field(
        default="",
        description=(
            "Public web origin used to build password-reset links, e.g. "
            "'https://app.example.com' (PASSWORD_RESET_ORIGIN)"
        ),
        json_schema_extra={"env": "PASSWORD_RESET_ORIGIN"},
    )
    password_reset_path: str = Field(
        default="/reset-password",
        description="Public reset-page path appended to the origin",
        json_schema_extra={"env": "PASSWORD_RESET_PATH"},
    )

    @property
    def usable_resend_api_key(self) -> str | None:
        """Return the Resend API key, or None when missing/placeholder."""
        return _usable_secret(self.resend_api_key or None)

    @property
    def normalized_origin(self) -> str | None:
        """Return the reset-link origin without a trailing slash, or None."""
        value = (self.password_reset_origin or "").strip()
        if not value:
            return None
        return value.rstrip("/")

    @property
    def normalized_path(self) -> str:
        """Return the reset-page path guaranteed to start with '/'."""
        value = (self.password_reset_path or "").strip() or "/reset-password"
        return value if value.startswith("/") else f"/{value}"

    @property
    def is_configured(self) -> bool:
        """Return True when all required outbound-email settings are present."""
        sender = (self.password_reset_sender or "").strip()
        return bool(
            self.usable_resend_api_key and sender and self.normalized_origin,
        )


class ImageDeliverySettings(BaseSettings):
    """Remote comic cover image optimization settings."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    image_optimizer_allowed_hosts: str = Field(
        default="comicvine.gamespot.com,www.comicvine.com,comicvine.com",
        description=(
            "Comma-separated upstream image hosts the optimizer may fetch. "
            "Any host outside this list is rejected so the endpoint cannot become "
            "an open proxy."
        ),
        json_schema_extra={"env": "IMAGE_OPTIMIZER_ALLOWED_HOSTS"},
    )
    image_optimizer_max_upstream_bytes: int = Field(
        default=4_000_000,
        ge=1,
        le=50_000_000,
        description=(
            "Maximum accepted upstream image payload size in bytes. Kept below "
            "Vercel's ~4.5 MB serverless response limit so even an untransformed "
            "passthrough fits a single function response."
        ),
        json_schema_extra={"env": "IMAGE_OPTIMIZER_MAX_UPSTREAM_BYTES"},
    )
    image_optimizer_upstream_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Total timeout for fetching an upstream cover image.",
        json_schema_extra={"env": "IMAGE_OPTIMIZER_UPSTREAM_TIMEOUT_SECONDS"},
    )
    image_optimizer_webp_quality: int = Field(
        default=80,
        ge=1,
        le=100,
        description="WebP encoder quality used for resized variants.",
        json_schema_extra={"env": "IMAGE_OPTIMIZER_WEBP_QUALITY"},
    )
    image_optimizer_avif_quality: int = Field(
        default=75,
        ge=1,
        le=100,
        description="AVIF encoder quality used for resized variants; ignored when libavif is unavailable (falls back to WebP).",
        json_schema_extra={"env": "IMAGE_OPTIMIZER_AVIF_QUALITY"},
    )


class Settings(BaseSettings):
    """Main settings class that aggregates all configuration groups."""

    model_config = SettingsConfigDict(env_file=[".env.test", ".env", ".envrc"], extra="ignore")

    @property
    def database(self) -> DatabaseSettings:
        """Get database settings."""
        return get_database_settings()

    @property
    def auth(self) -> AuthSettings:
        """Get auth settings."""
        return get_auth_settings()

    @property
    def app(self) -> AppSettings:
        """Get app settings."""
        return get_app_settings()

    @property
    def session(self) -> SessionSettings:
        """Get session settings."""
        return get_session_settings()

    @property
    def rating(self) -> RatingSettings:
        """Get rating settings."""
        return get_rating_settings()

    @property
    def github(self) -> GitHubSettings:
        """Get GitHub settings."""
        return get_github_settings()

    @property
    def recommendation(self) -> RecommendationSettings:
        """Get recommendation settings."""
        return get_recommendation_settings()

    @property
    def image_delivery(self) -> ImageDeliverySettings:
        """Get remote image delivery settings."""
        return get_image_delivery_settings()

    @property
    def email(self) -> EmailSettings:
        """Get outbound email settings."""
        return get_email_settings()


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Get cached database settings instance."""
    return DatabaseSettings()


@lru_cache
def get_auth_settings() -> AuthSettings:
    """Get cached auth settings instance."""
    return AuthSettings()


@lru_cache
def get_app_settings() -> AppSettings:
    """Get cached app settings instance."""
    return AppSettings()


@lru_cache
def get_session_settings() -> SessionSettings:
    """Get cached session settings instance."""
    return SessionSettings()


@lru_cache
def get_rating_settings() -> RatingSettings:
    """Get cached rating settings instance."""
    return RatingSettings()


@lru_cache
def get_github_settings() -> GitHubSettings:
    """Get cached GitHub settings instance."""
    return GitHubSettings()


@lru_cache
def get_recommendation_settings() -> RecommendationSettings:
    """Get cached recommendation settings instance."""
    return RecommendationSettings()


@lru_cache
def get_email_settings() -> EmailSettings:
    """Get cached outbound email settings instance."""
    return EmailSettings()


@lru_cache
def get_image_delivery_settings() -> ImageDeliverySettings:
    """Get cached remote image delivery settings instance."""
    return ImageDeliverySettings()


@lru_cache
def get_settings() -> Settings:
    """Get cached main settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear all cached settings (useful for testing)."""
    get_database_settings.cache_clear()
    get_auth_settings.cache_clear()
    get_app_settings.cache_clear()
    get_session_settings.cache_clear()
    get_rating_settings.cache_clear()
    get_github_settings.cache_clear()
    get_recommendation_settings.cache_clear()
    get_email_settings.cache_clear()
    get_image_delivery_settings.cache_clear()
    get_settings.cache_clear()
