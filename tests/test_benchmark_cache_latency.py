"""Unit tests for the cache-latency benchmark helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.benchmark_cache_latency import (
    BENCH_KV_KEY,
    DEFAULT_KV_TABLE,
    Run,
    _summarize,
    _upstash_request,
    load_dotenv_values,
    normalize_asyncpg_url,
    redact_report,
    resolve_upstash_rest_token,
    resolve_upstash_rest_url,
)


def test_normalize_asyncpg_url_strips_sqlalchemy_dialects() -> None:
    """asyncpg.connect rejects SQLAlchemy dialect URLs used by the app."""
    assert (
        normalize_asyncpg_url("postgresql+asyncpg://user:pass@host/db")
        == "postgresql://user:pass@host/db"
    )
    assert (
        normalize_asyncpg_url("postgresql+psycopg://user:pass@host/db")
        == "postgresql://user:pass@host/db"
    )
    assert normalize_asyncpg_url("postgresql://user:pass@host/db") == (
        "postgresql://user:pass@host/db"
    )


def test_summarize_ignores_skipped_and_error_runs() -> None:
    """Zero-latency skipped rows must not collapse the measured distribution."""
    runs = [
        Run("neon_point_select", 0, 12.5, "ok", None, None, None),
        Run("neon_point_select", 1, 0.0, "skipped", None, None, "DATABASE_URL required"),
        Run("neon_point_select", 2, 14.0, "ok", None, None, None),
        Run("neon_point_select", 3, 99.0, "error", None, None, "connect_failed"),
    ]

    summary = _summarize(runs)

    assert summary is not None
    assert summary["samples"] == 2
    assert summary["elapsed_ms"]["p50"] == 13.25


def test_summarize_returns_none_when_no_ok_samples() -> None:
    """A skipped path has no latency distribution."""
    runs = [
        Run("upstash_rest_get", 0, 0.0, "skipped", None, None, "missing token"),
    ]

    assert _summarize(runs) is None


def test_redact_report_rewrites_upstash_host_and_credential_errors() -> None:
    """Committed JSON must not include provider hostnames or connection strings."""
    report = {
        "upstash_rest_get": {
            "endpoint": "https://us1-secret.upstash.io/get/comic_pile_cache_latency_bench_key_v1",
            "runs": [
                {
                    "error_detail": "connect_failed: postgresql://user:hunter2@host/db",
                }
            ],
        }
    }

    redacted = redact_report(report)

    endpoint = redacted["upstash_rest_get"]["endpoint"]
    assert isinstance(endpoint, str)
    assert "upstash.io" not in endpoint
    assert "<redacted>" in endpoint
    assert redacted["upstash_rest_get"]["runs"][0]["error_detail"] == "<redacted>"
    assert (
        report["upstash_rest_get"]["endpoint"]
        == "https://us1-secret.upstash.io/get/comic_pile_cache_latency_bench_key_v1"
    )


def test_upstash_request_rejects_placeholder_urls() -> None:
    """A Vercel [SENSITIVE] placeholder must not crash the harness."""
    elapsed_ms, http_status, _body, error = _upstash_request(
        "[SENSITIVE]/get/comic_pile_cache_latency_bench_key_v1",
        "token",
        1.0,
    )

    assert elapsed_ms == 0.0
    assert http_status == 0
    assert error is not None
    assert "invalid_upstash_url_scheme" in error


def test_benchmark_uses_one_shared_kv_key_and_table() -> None:
    """Neon insert/select and Upstash GET must share one key and the documented table."""
    assert BENCH_KV_KEY == "comic_pile_cache_latency_bench_key_v1"
    assert DEFAULT_KV_TABLE == "bench_cache_kv"


def test_load_dotenv_values_strips_quotes(tmp_path: Path) -> None:
    """Vercel env-pull files may quote values; the loader must not keep the quotes."""
    env_file = tmp_path / ".env.production.local"
    env_file.write_text(
        'KV_REST_API_URL="https://example.upstash.io"\n'
        "KV_REST_API_TOKEN=plain-token\n"
        "UPSTASH_REDIS_REST_TOKEN=[SENSITIVE]\n"
        "# comment\n",
        encoding="utf-8",
    )

    values = load_dotenv_values(str(env_file))

    assert values["KV_REST_API_URL"] == "https://example.upstash.io"
    assert values["KV_REST_API_TOKEN"] == "plain-token"
    assert "UPSTASH_REDIS_REST_TOKEN" not in values


def test_upstash_rest_aliases_prefer_native_then_vercel_kv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vercel KV REST names are accepted when native Upstash names are absent."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    monkeypatch.setenv("KV_REST_API_URL", "https://example.upstash.io")
    monkeypatch.setenv("KV_REST_API_READ_ONLY_TOKEN", "readonly-token")
    monkeypatch.setenv("KV_REST_API_TOKEN", "write-token")

    assert resolve_upstash_rest_url() == "https://example.upstash.io"
    assert resolve_upstash_rest_token() == "write-token"

    monkeypatch.delenv("KV_REST_API_TOKEN")
    assert resolve_upstash_rest_token() == "readonly-token"

    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://native.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "native-token")
    assert resolve_upstash_rest_url() == "https://native.upstash.io"
    assert resolve_upstash_rest_token() == "native-token"
