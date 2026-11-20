"""Bootstrap alias telemetry coverage for the Roll cutover gate (issue #2718).

Production must be able to distinguish ``/api/roll/bootstrap`` (legacy),
``/api/v1/roll/bootstrap`` (v1), and ``/api/v2/roll/bootstrap`` (v2), and must
record whether each caller looked like a web-origin client for the later
seven-day zero-web-origin deletion gate. These tests pin classification,
aggregation, the authenticated snapshot, middleware wiring, and the guarantee
that only classification facts are exposed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.bootstrap_route_telemetry import (
    classify_bootstrap_alias,
    classify_web_origin,
    record_bootstrap_alias_hit,
    reset_bootstrap_alias_counters_for_tests,
    bootstrap_alias_snapshot,
)
from app.schemas.bootstrap_telemetry import (
    BootstrapAliasCounterSchema,
    BootstrapAliasSnapshotSchema,
)

LEGACY_PATH = "/api/roll/bootstrap"
V1_PATH = "/api/v1/roll/bootstrap"
V2_PATH = "/api/v2/roll/bootstrap"
SNAPSHOT_PATH = "/api/v1/bootstrap-alias-metrics"


@pytest.fixture(autouse=True)
def clean_counters() -> Iterator[None]:
    """Isolate the process-local counters between tests."""
    reset_bootstrap_alias_counters_for_tests()
    yield
    reset_bootstrap_alias_counters_for_tests()


def _counts() -> dict[tuple[str, bool, str], int]:
    """Return snapshot counts keyed by alias, web-origin, and status class."""
    return {
        (counter.alias, counter.web_origin, counter.status_class): counter.count
        for counter in bootstrap_alias_snapshot()
    }


def test_classify_bootstrap_alias_matches_only_the_three_mounted_paths() -> None:
    """Only exact bootstrap paths classify; look-alikes and sub-paths do not."""
    assert classify_bootstrap_alias(LEGACY_PATH) == "legacy"
    assert classify_bootstrap_alias(V1_PATH) == "v1"
    assert classify_bootstrap_alias(V2_PATH) == "v2"


@pytest.mark.parametrize(
    "path",
    [
        "/api/roll/bootstrap/",
        "/api/v1/roll/bootstrap/",
        "/api/v2/roll/bootstrap/",
        "/api/v2/roll/bootstrap/extra",
        "/api/v3/roll/bootstrap",
        "/api/v1/Roll/bootstrap",
        "/api/v1/roll/bootstrap-extra",
        "/api/v1/roll/bootstrapish",
        "/roll/bootstrap",
        "",
    ],
)
def test_classify_bootstrap_alias_rejects_look_alike_paths(path: str) -> None:
    """Trailing slashes, sub-paths, and case variants are never counted."""
    assert classify_bootstrap_alias(path) is None


def test_classify_bootstrap_alias_ignores_query_strings_and_fragments() -> None:
    """A mounted path keeps its alias regardless of capture-only suffixes."""
    assert classify_bootstrap_alias(f"{V2_PATH}?timezone=UTC") == "v2"
    assert classify_bootstrap_alias(f"{V1_PATH}#roll") == "v1"
    assert classify_bootstrap_alias(f"{LEGACY_PATH}?a=1#b") == "legacy"


def test_classify_web_origin_without_browser_signals_is_false() -> None:
    """A plain API client must not inflate the web-origin share."""
    info = classify_web_origin({}, host="api.example.com")
    assert info.web_origin is False
    assert info.cross_origin is False


def test_classify_web_origin_accepts_origin_referer_and_fetch_metadata() -> None:
    """Standard browser origin/fetch signals each mark a web-origin caller."""
    origin = classify_web_origin(
        {"Origin": "https://app.example.com"}, host="app.example.com"
    )
    assert origin.web_origin is True
    assert origin.cross_origin is False

    referer = classify_web_origin(
        {"Referer": "https://app.example.com/roll"}, host="api.example.com"
    )
    assert referer.web_origin is True
    assert referer.cross_origin is False

    for site in ("none", "same-origin", "same-site", "cross-site"):
        info = classify_web_origin({"Sec-Fetch-Site": site}, host="api.example.com")
        assert info.web_origin is True, site
    assert classify_web_origin({"Sec-Fetch-Site": "cross-site"}).cross_origin is True


def test_classify_web_origin_detects_cross_origin_without_userinfo_false_positives() -> None:
    """Cross-origin is derived from hosts, never from raw header equality."""
    cross = classify_web_origin(
        {"Origin": "https://other.example.com"}, host="app.example.com"
    )
    assert cross.web_origin is True
    assert cross.cross_origin is True

    credentials = classify_web_origin(
        {"Origin": "https://user:secret@app.example.com"}, host="app.example.com"
    )
    assert credentials.web_origin is True
    assert credentials.cross_origin is False

    origin_wins = classify_web_origin(
        {"Origin": "https://other.example.com", "Sec-Fetch-Site": "same-origin"},
        host="app.example.com",
    )
    assert origin_wins.cross_origin is True


def test_classify_web_origin_rejects_non_http_signals() -> None:
    """Malformed and non-HTTP values never classify as a browser origin."""
    for value in ("javascript:alert(1)", "not a url", "ftp://files.example.com/a"):
        info = classify_web_origin({"Origin": value, "Referer": value})
        assert info.web_origin is False, value
        assert info.cross_origin is False, value


def test_record_bootstrap_alias_hit_aggregates_and_sorts() -> None:
    """Counts aggregate per classification key and snapshot order is stable."""
    record_bootstrap_alias_hit("legacy", True, 200)
    record_bootstrap_alias_hit("legacy", True, 200)
    record_bootstrap_alias_hit("v1", False, 401)
    record_bootstrap_alias_hit("v2", True, 500)

    assert _counts() == {
        ("legacy", True, "2xx"): 2,
        ("v1", False, "4xx"): 1,
        ("v2", True, "5xx"): 1,
    }
    keys = [
        (counter.alias, counter.web_origin, counter.status_class)
        for counter in bootstrap_alias_snapshot()
    ]
    assert keys == sorted(keys)


def test_record_bootstrap_alias_hit_logs_only_classification_facts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The structured log line carries no path, header, identity, or payload."""
    caplog.set_level(logging.INFO, logger="app.bootstrap_route_telemetry")
    record_bootstrap_alias_hit("v2", True, 204)

    record = next(
        entry
        for entry in caplog.records
        if entry.getMessage() == "roll.bootstrap.alias.telemetry"
    )
    assert getattr(record, "bootstrap_alias", None) == "v2"
    assert getattr(record, "web_origin", None) is True
    assert getattr(record, "status_class", None) == "2xx"
    logged_fields = set(record.__dict__) & {
        "path",
        "query",
        "headers",
        "user_id",
        "payload",
        "origin",
        "referer",
    }
    assert logged_fields == set()


async def test_snapshot_endpoint_requires_authentication(client: AsyncClient) -> None:
    """Unauthenticated callers must not read alias telemetry."""
    response = await client.get(SNAPSHOT_PATH)
    assert response.status_code == 401


async def test_snapshot_endpoint_reports_counters(
    auth_client: AsyncClient,
) -> None:
    """Authenticated callers receive the process-local typed snapshot."""
    response = await auth_client.get(SNAPSHOT_PATH)
    assert response.status_code == 200

    payload = BootstrapAliasSnapshotSchema.model_validate(response.json())
    counter_fields = set(BootstrapAliasCounterSchema.model_fields)
    assert counter_fields == {"alias", "web_origin", "status_class", "count"}
    for counter in payload.counters:
        assert counter.alias in {"legacy", "v1", "v2"}
        assert counter.count >= 0
