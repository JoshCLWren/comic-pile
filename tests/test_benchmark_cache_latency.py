"""Unit tests for the cache-latency benchmark helpers."""

from __future__ import annotations

from scripts.benchmark_cache_latency import (
    BENCH_KV_KEY,
    DEFAULT_KV_TABLE,
    Run,
    _summarize,
    normalize_asyncpg_url,
    redact_report,
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


def test_benchmark_uses_one_shared_kv_key_and_table() -> None:
    """Neon insert/select and Upstash GET must share one key and the documented table."""
    assert BENCH_KV_KEY == "comic_pile_cache_latency_bench_key_v1"
    assert DEFAULT_KV_TABLE == "bench_cache_kv"
