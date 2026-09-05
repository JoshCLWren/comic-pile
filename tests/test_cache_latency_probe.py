"""Tests for the temporary production-runtime cache latency probe."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import health as health_module
from app.services.cache_latency_probe import (
    TEMPORARY_PROBE_TOKEN,
    authorize_probe_header,
    measure_upstash_rest_get,
    probe_is_enabled,
    resolve_kv_rest_token,
    resolve_kv_rest_url,
)
from app.services.errors import InvalidRequestError, NotFoundError


def test_resolve_kv_rest_ignores_resp_aliases_and_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``REDIS_URL`` / ``KV_URL`` and ``[SENSITIVE]`` must not be used."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("KV_URL", "redis://localhost:6379")
    monkeypatch.setenv("KV_REST_API_URL", "[SENSITIVE]")
    monkeypatch.setenv("KV_REST_API_TOKEN", "")
    monkeypatch.delenv("KV_REST_API_READ_ONLY_TOKEN", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    assert resolve_kv_rest_url() is None
    assert resolve_kv_rest_token() is None


def test_resolve_kv_rest_prefers_read_write_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read-write KV token wins over the GET-only fallback."""
    monkeypatch.setenv("KV_REST_API_URL", "https://example.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "write-token")
    monkeypatch.setenv("KV_REST_API_READ_ONLY_TOKEN", "readonly-token")

    assert resolve_kv_rest_url() == "https://example.upstash.io"
    assert resolve_kv_rest_token() == "write-token"


def test_probe_enabled_on_vercel_runtime_or_explicit_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vercel preview/production and the explicit flag enable the probe."""
    monkeypatch.delenv("CACHE_LATENCY_PROBE_ENABLED", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    assert probe_is_enabled() is False

    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert probe_is_enabled() is True

    monkeypatch.setenv("VERCEL_ENV", "production")
    assert probe_is_enabled() is True

    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("CACHE_LATENCY_PROBE_ENABLED", "true")
    assert probe_is_enabled() is True


def test_authorize_probe_header_is_404_without_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong or missing headers must 404 without leaking the token."""
    monkeypatch.setenv("CACHE_LATENCY_PROBE_ENABLED", "true")

    with pytest.raises(NotFoundError):
        authorize_probe_header(None)
    with pytest.raises(NotFoundError):
        authorize_probe_header("wrong-token")
    authorize_probe_header(TEMPORARY_PROBE_TOKEN)


def test_measure_upstash_rest_get_requires_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing KV REST credentials fail closed with a redacted error."""
    monkeypatch.delenv("KV_REST_API_URL", raising=False)
    monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)
    monkeypatch.delenv("KV_REST_API_READ_ONLY_TOKEN", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    with pytest.raises(InvalidRequestError, match="kv_rest_not_configured"):
        measure_upstash_rest_get(iterations=1, warmups=0)


def test_measure_upstash_rest_get_returns_redacted_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful samples are summarized without host or token material."""
    monkeypatch.setenv("KV_REST_API_URL", "https://secret.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "super-secret-token")
    monkeypatch.setenv("VERCEL_REGION", "cle1")
    monkeypatch.setenv("VERCEL_ENV", "production")

    with patch(
        "app.services.cache_latency_probe._get_once",
        return_value=(12.5, 200, None),
    ):
        result = measure_upstash_rest_get(iterations=4, warmups=1)

    assert result.status == "ok"
    assert result.samples == 4
    assert result.p50_ms == 12.5
    assert result.measured_from == "vercel:cle1"
    assert result.vercel_env == "production"
    assert "upstash.io" not in str(result)
    assert "super-secret-token" not in str(result)


def test_measure_upstash_rest_get_counts_missing_key_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing bench key still records GET hop latency."""
    monkeypatch.setenv("KV_REST_API_URL", "https://secret.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "super-secret-token")

    with patch(
        "app.services.cache_latency_probe._get_once",
        return_value=(18.25, 404, "HTTP 404"),
    ):
        result = measure_upstash_rest_get(iterations=3, warmups=0)

    assert result.status == "ok"
    assert result.samples == 3
    assert result.p50_ms == 18.25


def _probe_client() -> TestClient:
    """Build a DB-free app that mounts only the health router."""
    app = FastAPI()
    app.include_router(health_module.router, prefix="/api/v1")
    return TestClient(app)


def test_cache_latency_route_hidden_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The temporary route stays 404 in ordinary local processes."""
    monkeypatch.delenv("CACHE_LATENCY_PROBE_ENABLED", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    client = _probe_client()

    response = client.get(
        "/api/v1/health/cache-latency",
        headers={"X-Cache-Latency-Probe": TEMPORARY_PROBE_TOKEN},
    )

    assert response.status_code == 404


def test_cache_latency_route_returns_redacted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authorized preview-style call returns stats only."""
    from app.services.cache_latency_probe import CacheLatencyProbeResult

    monkeypatch.setenv("CACHE_LATENCY_PROBE_ENABLED", "true")
    fake = CacheLatencyProbeResult(
        measured_from="vercel:cle1",
        vercel_env="preview",
        samples=30,
        p50_ms=18.0,
        p95_ms=22.0,
        min_ms=15.0,
        max_ms=24.0,
        mean_ms=18.5,
        quota_blocked=False,
        status="ok",
    )
    client = _probe_client()

    with patch("app.api.health.measure_upstash_rest_get", return_value=fake):
        hidden = client.get("/api/v1/health/cache-latency")
        allowed = client.get(
            "/api/v1/health/cache-latency",
            headers={"X-Cache-Latency-Probe": TEMPORARY_PROBE_TOKEN},
        )

    assert hidden.status_code == 404
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["samples"] == 30
    assert payload["p50_ms"] == 18.0
    assert payload["measured_from"] == "vercel:cle1"
    assert "super-secret-token" not in allowed.text
    assert "upstash.io" not in allowed.text
    assert payload["note"] == "temporary-issue-2216-remove-after-measurement"
