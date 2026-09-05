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
    env_presence,
    kv_rest_preflight,
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
    elapsed = summary["elapsed_ms"]
    assert isinstance(elapsed, dict)
    assert elapsed["p50"] == 13.25


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

    upstash = redacted["upstash_rest_get"]
    assert isinstance(upstash, dict)
    endpoint = upstash["endpoint"]
    assert isinstance(endpoint, str)
    assert "upstash.io" not in endpoint
    assert "<redacted>" in endpoint
    runs = upstash["runs"]
    assert isinstance(runs, list)
    first_run = runs[0]
    assert isinstance(first_run, dict)
    assert first_run["error_detail"] == "<redacted>"
    original = report["upstash_rest_get"]
    assert isinstance(original, dict)
    assert (
        original["endpoint"]
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


def test_upstash_rest_aliases_prefer_kv_rest_over_empty_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty native Upstash names and RESP aliases must not hide Vercel KV REST."""
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("KV_URL", "redis://localhost:6379")
    monkeypatch.setenv("KV_REST_API_URL", "https://example.upstash.io")
    monkeypatch.setenv("KV_REST_API_READ_ONLY_TOKEN", "readonly-token")
    monkeypatch.setenv("KV_REST_API_TOKEN", "write-token")

    assert resolve_upstash_rest_url() == "https://example.upstash.io"
    assert resolve_upstash_rest_token() == "write-token"

    monkeypatch.delenv("KV_REST_API_TOKEN")
    assert resolve_upstash_rest_token() == "readonly-token"


def test_upstash_rest_aliases_treat_sensitive_placeholders_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Vercel [SENSITIVE] pull placeholder is not a credential."""
    monkeypatch.setenv("KV_REST_API_URL", "[SENSITIVE]")
    monkeypatch.setenv("KV_REST_API_TOKEN", "[SENSITIVE]")
    monkeypatch.delenv("KV_REST_API_READ_ONLY_TOKEN", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    assert resolve_upstash_rest_url() is None
    assert resolve_upstash_rest_token() is None
    assert env_presence("KV_REST_API_URL") == "redacted"
    assert env_presence("KV_REST_API_TOKEN") == "redacted"


def test_kv_rest_preflight_fails_with_boolean_labels_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preflight must fail closed without printing secret values."""
    monkeypatch.setenv("KV_REST_API_URL", "[SENSITIVE]")
    monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)
    monkeypatch.delenv("KV_REST_API_READ_ONLY_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="url_ready=no") as caught:
        kv_rest_preflight()

    message = str(caught.value)
    assert "KV_REST_API_URL=redacted" in message
    assert "KV_REST_API_TOKEN=missing" in message
    assert "[SENSITIVE]" not in message


def test_kv_rest_preflight_passes_when_kv_aliases_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A production-context child with KV REST aliases is ready to measure."""
    monkeypatch.setenv("KV_REST_API_URL", "https://example.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "write-token")

    coverage = kv_rest_preflight()

    assert coverage["url_ready"] == "yes"
    assert coverage["token_ready"] == "yes"
    assert "write-token" not in str(coverage)
