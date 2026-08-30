"""Tests for the one-command cache usage, budget, and headroom report."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.cache_usage_report import (
    HttpGet,
    UpstashManagementClient,
    build_cache_usage_report,
    parse_usage,
    render_cache_usage_report,
)


def _fake_http(databases: list[dict], stats: dict) -> HttpGet:
    """Build an injectable HTTP GET that serves canned Upstash responses."""
    import json

    def _get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        if url.endswith("/v2/redis/databases"):
            return 200, json.dumps(databases).encode()
        if "/v2/redis/stats/" in url:
            return 200, json.dumps(stats).encode()
        return 404, b"{}"

    return _get


SAMPLE_DATABASE = {
    "database_id": "db-123",
    "database_name": "comic-pile",
    "type": "free",
    "db_request_limit": 500_000,
}

SAMPLE_STATS = {
    "total_monthly_requests": 120_000,
    "daily_net_commands": 4_000,
    "total_monthly_read_requests": 90_000,
    "total_monthly_write_requests": 20_000,
    "total_monthly_script_requests": 10_000,
    "total_monthly_bandwidth": 7_000,
    "hits": [{"x": "2026-08-01", "y": 80}, {"x": "2026-08-02", "y": 95}],
    "misses": [{"x": "2026-08-01", "y": 20}, {"x": "2026-08-02", "y": 5}],
    "command_counts": [
        {
            "metric_identifier": "GET",
            "data_points": [{"x": "2026-08-01", "y": 60}, {"x": "2026-08-02", "y": 40}],
        },
        {
            "metric_identifier": "SET",
            "data_points": [{"x": "2026-08-01", "y": 30}, {"x": "2026-08-02", "y": 20}],
        },
    ],
}


def test_parse_usage_extracts_command_counts_and_hits() -> None:
    """Parse the Upstash stats payload into the usage snapshot."""
    usage = parse_usage(SAMPLE_STATS, SAMPLE_DATABASE)

    assert usage.database_id == "db-123"
    assert usage.total_monthly_requests == 120_000
    assert usage.daily_net_commands == 4_000
    assert usage.command_counts == {"GET": 100, "SET": 50}
    assert usage.hits_latest == 95
    assert usage.misses_latest == 5
    assert usage.db_request_limit == 500_000


def test_build_report_with_usage_computes_headroom() -> None:
    """A configured report compares usage against the conservative budget."""
    http = _fake_http([SAMPLE_DATABASE], SAMPLE_STATS)
    now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

    report = build_cache_usage_report(
        email="a@b.com",
        api_key="key",
        now=now,
        http_get=http,
    )

    assert report.upstash_configured is True
    assert report.used_commands == 120_000
    # 350_000 budget - 120_000 used = 230_000 headroom
    assert report.headroom_commands == 230_000
    assert report.used_pct == pytest.approx(34.29, abs=0.01)
    # August has 31 days; day 15 leaves 16 remaining days.
    assert report.days_remaining == 16
    assert report.projected_month_end is not None
    assert report.budget_monthly == 350_000


def test_build_report_without_credentials_skips_usage() -> None:
    """Without Upstash credentials the report still prints budget and notes."""
    report = build_cache_usage_report()

    assert report.upstash_configured is False
    assert report.upstash is None
    assert report.used_commands is None
    assert report.headroom_commands is None
    assert any("UPSTASH_EMAIL" in note for note in report.notes)


def test_build_report_handles_api_error_gracefully() -> None:
    """An Upstash API error degrades to a skipped-usage report, not a crash."""

    def _failing(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        return 401, b'{"error":"unauthorized"}'

    report = build_cache_usage_report(
        email="a@b.com",
        api_key="bad",
        http_get=_failing,
    )

    assert report.upstash_configured is False
    assert report.upstash is None
    assert any("Upstash usage unavailable" in note for note in report.notes)


def test_build_report_explicit_database_id_short_circuits_discovery() -> None:
    """An explicit database id is used directly without listing databases."""
    http = _fake_http([SAMPLE_DATABASE], SAMPLE_STATS)

    report = build_cache_usage_report(
        email="a@b.com",
        api_key="key",
        database_id="db-direct",
        http_get=http,
    )

    assert report.upstash is not None
    assert report.upstash.database_id == "db-direct"
    assert report.used_commands == 120_000


def test_render_includes_usage_budget_and_headroom_sections() -> None:
    """The rendered text surfaces usage, budget, and headroom in one view."""
    report = build_cache_usage_report(
        email="a@b.com",
        api_key="key",
        now=datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC),
        http_get=_fake_http([SAMPLE_DATABASE], SAMPLE_STATS),
    )

    rendered = render_cache_usage_report(report)

    assert "Upstash usage" in rendered
    assert "Budget" in rendered
    assert "Headroom" in rendered
    assert "In-process cache metrics" in rendered
    assert "230,000" in rendered  # remaining headroom


def test_render_without_usage_is_still_complete() -> None:
    """A credentials-less run still renders budget and a skipped headroom note."""
    rendered = render_cache_usage_report(build_cache_usage_report())

    assert "Budget" in rendered
    assert "no live usage to compare against budget" in rendered


def test_report_to_dict_round_trips_usage() -> None:
    """The JSON mapping preserves the parsed usage and headroom fields."""
    from app.cache_usage_report import _report_to_dict

    report = build_cache_usage_report(
        email="a@b.com",
        api_key="key",
        now=datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC),
        http_get=_fake_http([SAMPLE_DATABASE], SAMPLE_STATS),
    )

    payload = _report_to_dict(report)

    assert payload["upstash"]["total_monthly_requests"] == 120_000
    assert payload["headroom_commands"] == 230_000
    assert payload["budget_monthly"] == 350_000
    assert isinstance(payload["in_process_metrics"], dict)


def test_cli_main_exits_cleanly_without_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI entry point renders a complete report and exits zero."""
    from app.cache_usage_report import main

    exit_code = main([])

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Cache usage report" in captured
    assert "Budget" in captured


def test_cli_main_json_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """The --json flag emits a parseable JSON document."""
    import json as _json

    from app.cache_usage_report import main

    exit_code = main(["--json"])

    assert exit_code == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["budget_monthly"] == 350_000


def test_live_http_getter_parses_response() -> None:
    """The default urllib path decodes a 200 response when no injector is set."""
    import json as _json

    client = UpstashManagementClient(email="a@b.com", api_key="key")
    body = _json.dumps([SAMPLE_DATABASE]).encode()

    with patch("app.cache_usage_report.urllib.request.urlopen") as mock_urlopen:
        response = MagicMock()
        response.status = 200
        response.read.return_value = body
        mock_urlopen.return_value.__enter__.return_value = response

        databases = client.list_databases()

    assert databases == [SAMPLE_DATABASE]


def test_live_http_getter_raises_on_api_error() -> None:
    """The default urllib path wraps a 4xx response as UpstashApiError."""
    import urllib.error as urllib_error

    from app.cache_usage_report import UpstashApiError

    client = UpstashManagementClient(email="a@b.com", api_key="key")
    http_error = urllib_error.HTTPError("url", 401, "Unauthorized", {}, None)

    with patch("app.cache_usage_report.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = http_error

        with pytest.raises(UpstashApiError):
            client.list_databases()

