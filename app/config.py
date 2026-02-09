"""Centralized application configuration using Pydantic Settings.

This module consolidates all environment variables used throughout the application.
Configuration is validated at startup and provides type-safe access to settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        ...,
        description="PostgreSQL database connection URL",
        json_schema_extra={"env": "DATABASE_URL"},
    )
    test_database_url: str | None = Field(
        default=None,
        description="Database URL for testing (overrides DATABASE_URL in tests)",
        json_schema_extra={"env": "TEST_DATABASE_URL"},
    )

    @property
    def async_url(self) -> str:
        """Get the asynchronous database URL with asyncpg driver."""
        url = self.database_url
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = Field(
        ...,
        description="Secret key for JWT token signing (required)",
        json_schema_extra={"env": "SECRET_KEY"},
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm",
    )
    access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration time in minutes",
        json_schema_extra={"env": "ACCESS_TOKEN_EXPIRE_MINUTES"},
    )
    refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration time in days",
        json_schema_extra={"env": "REFRESH_TOKEN_EXPIRE_DAYS"},
    )


class AppSettings(BaseSettings):
    """General application settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production", "test"] = Field(
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

    @property
    def cors_origins_list(self) -> list[str]:
        """Get CORS origins as a list."""
        if not self.cors_origins or not self.cors_origins.strip():
            if self.environment == "production":
                return []
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

    def validate_production_cors(self) -> None:
        """Validate that CORS is properly configured in production."""
        if self.environment == "production":
            if not self.cors_origins or not self.cors_origins.strip():
                raise RuntimeError("CORS_ORIGINS must be set in production mode")


class SessionSettings(BaseSettings):
    """Reading session configuration settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
            return 6
        return v

    @field_validator("start_die")
    @classmethod
    def validate_start_die(cls, v: int) -> int:
        """Ensure start die is within valid range."""
        if not 4 <= v <= 20:
            return 6
        return v


class RatingSettings(BaseSettings):
    """Rating system configuration settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
            return 0.5
        return v

    @field_validator("rating_max")
    @classmethod
    def validate_rating_max(cls, v: float) -> float:
        """Ensure rating max is within valid range."""
        if not 0.5 <= v <= 5.0:
            return 5.0
        return v

    @field_validator("rating_threshold")
    @classmethod
    def validate_rating_threshold(cls, v: float) -> float:
        """Ensure rating threshold is within valid range."""
        if not 0.5 <= v <= 5.0:
            return 4.0
        return v


class Settings(BaseSettings):
    """Main settings class that aggregates all configuration groups."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Nested settings groups
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


# Cached settings instances to avoid re-reading environment on every access
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
    get_settings.cache_clear()
