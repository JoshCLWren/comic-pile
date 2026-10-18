"""Tests for the daily Vercel Cron release-sync trigger (#3119).

The endpoint is machine-authenticated rather than user-authenticated. These
tests prove the secret gate fails closed, overlapping invocations are a
non-error no-op, one owner/source failure cannot roll back successful work,
retries stay idempotent, and the route stays a thin service delegation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import clear_settings_cache
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.models.user import User
from app.services import reading_plan_sync_service as sync_service
from app.services.reading_plan_sync_service import (
    RELEASE_SYNC_CRON_LOCK_KEY,
    run_scheduled_release_sync,
)
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineResponse
from tests.conftest import get_or_create_user_async

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CRON_URL = "/api/v1/cron/release-sync"
TEST_CRON_SECRET = "test-cron-secret-value-0123456789"
FIXED_AS_OF = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)


@dataclass
class _FakeProvider(ComicVineClient):
    """Provider double that can fail selected volumes."""

    rosters: dict[int, list[dict[str, object]]] = field(default_factory=dict)
    failures: dict[int, Exception] = field(default_factory=dict)
    calls: list[tuple[int, bool]] = field(default_factory=list)

    def __init__(
        self,
        rosters: dict[int, list[dict[str, object]]] | None = None,
        failures: dict[int, Exception] | None = None,
    ) -> None:
        self.rosters = rosters or {}
        self.failures = failures or {}
        self.calls = []

    async def fetch_volume_issues(
        self, volume_id: int, *, refresh: bool = False
    ) -> list[dict[str, object]]:
        self.calls.append((volume_id, refresh))
        if volume_id in self.failures:
            raise self.failures[volume_id]
        return list(self.rosters.get(volume_id, []))

    async def fetch_issue(
        self, issue_id: int, *, refresh: bool = False
    ) -> ComicVineResponse:
        raise ComicVineError("fake provider does not hydrate issues")

    async def fetch_story_arc(
        self, arc_id: int, *, refresh: bool = False
    ) -> ComicVineResponse:
        raise ComicVineError("fake provider has no story arcs")


def _released_row(issue_id: int, issue_number: str) -> dict[str, object]:
    """Return one released provider roster row."""
    return {
        "id": issue_id,
        "issue_number": issue_number,
        "store_date": "2025-06-01",
        "cover_date": "1999-01-01",
    }


def _configure_cron_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str = TEST_CRON_SECRET
) -> str:
    """Configure the cron secret for the current test and refresh settings."""
    monkeypatch.setenv("CRON_SECRET", secret)
    clear_settings_cache()
    return secret


def _bearer(secret: str) -> dict[str, str]:
    """Build the authorization header Vercel sends to a cron endpoint."""
    return {"Authorization": f"Bearer {secret}"}


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider) -> None:
    """Install a fake provider on the service's client factory."""
    monkeypatch.setattr(
        sync_service, "build_comicvine_client", lambda: provider, raising=True
    )


async def _seed_source(
    db: AsyncSession,
    *,
    user_id: int,
    volume_id: int,
    enabled: bool = True,
) -> Thread:
    """Create a plan, thread, confirmed mapping, and release source."""
    plan = ContinuityPlan(
        user_id=user_id,
        name=f"Plan {volume_id}",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    db.add(plan)
    await db.flush()
    thread = Thread(
        title=f"Thread {volume_id}",
        format="comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=str(volume_id),
        metadata_json={"name": f"Fixture Saga {volume_id}"},
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="test",
        )
    )
    db.add(
        ReadingPlanReleaseSource(
            plan_id=plan.id,
            thread_id=thread.id,
            external_identity_id=identity.id,
            enabled=enabled,
        )
    )
    await db.flush()
    return thread


async def _issue_numbers(db: AsyncSession, *, thread_id: int) -> list[str]:
    """Return persisted issue numbers for one thread."""
    rows = await db.execute(
        select(Issue.issue_number)
        .where(Issue.thread_id == thread_id)
        .order_by(Issue.position, Issue.id)
    )
    return list(rows.scalars().all())


def test_vercel_config_declares_one_daily_release_sync_cron() -> None:
    """The deployment must expose exactly one daily release-sync cron."""
    config = json.loads(
        (REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8")
    )

    assert config["crons"] == [
        {"path": CRON_URL, "schedule": "0 9 * * *"}
    ]

    from scripts.validate_vercel_config import check_hobby_cron

    assert check_hobby_cron(config) == []


@pytest.mark.asyncio
async def test_cron_fails_closed_when_secret_is_not_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No deployment secret means no work is possible, with or without a header."""
    # An explicit empty environment value overrides any local dotenv file, so
    # the fail-closed contract is deterministic on developer machines too.
    monkeypatch.setenv("CRON_SECRET", "")
    clear_settings_cache()

    anonymous = await client.get(CRON_URL)
    guessed = await client.get(CRON_URL, headers=_bearer("any-guess"))

    assert anonymous.status_code == 503
    assert guessed.status_code == 503
    assert "not configured" in anonymous.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-secret"},
        {"Authorization": "Basic test-cron-secret-value-0123456789"},
        {"Authorization": "Bearer"},
        {"Authorization": "test-cron-secret-value-0123456789"},
    ],
)
async def test_cron_rejects_missing_or_incorrect_bearer(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    """Only an exact bearer match reaches the handler."""
    _configure_cron_secret(monkeypatch)

    response = await client.get(CRON_URL, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_cron_rejects_non_ascii_authorization_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ASCII bearer value is rejected by the gate, never a 500.

    httpx cannot transmit non-ASCII header bytes, so this exercises the
    dependency directly to prove ``compare_digest`` is byte-safe.
    """
    from app.access_control import require_cron_secret

    _configure_cron_secret(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        require_cron_secret(authorization="Bearer sécret-é")

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_cron_runs_for_every_owner_with_enabled_sources(
    client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled run discovers owners instead of relying on a request user."""
    secret = _configure_cron_secret(monkeypatch)
    stranger = await get_or_create_user_async(async_db, "cron_owner_two@test.com")
    first_thread = await _seed_source(
        async_db, user_id=default_user.id, volume_id=7101
    )
    second_thread = await _seed_source(
        async_db, user_id=stranger.id, volume_id=7102
    )
    provider = _FakeProvider(
        {
            7101: [_released_row(71011, "1")],
            7102: [_released_row(71021, "1")],
        }
    )
    _use_provider(monkeypatch, provider)

    response = await client.get(CRON_URL, headers=_bearer(secret))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "completed"
    result = body["result"]
    assert result["users_total"] == 2
    assert result["users_processed"] == 2
    assert result["users_failed"] == 0
    assert result["created_issues"] == 2
    assert result["failed_sources"] == 0
    assert result["truncated"] is False
    assert response.headers["cache-control"] == "no-store"
    assert await _issue_numbers(async_db, thread_id=first_thread.id) == ["1"]
    assert await _issue_numbers(async_db, thread_id=second_thread.id) == ["1"]


@pytest.mark.asyncio
async def test_cron_already_running_is_a_non_error_noop(
    client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second invocation exits cleanly while another run holds the lock."""
    secret = _configure_cron_secret(monkeypatch)
    thread = await _seed_source(async_db, user_id=default_user.id, volume_id=7201)
    provider = _FakeProvider({7201: [_released_row(72011, "1")]})
    _use_provider(monkeypatch, provider)

    holder = await db_engine.connect()
    holder_transaction = await holder.begin()
    try:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": RELEASE_SYNC_CRON_LOCK_KEY},
        )

        response = await client.get(CRON_URL, headers=_bearer(secret))
    finally:
        await holder_transaction.rollback()
        await holder.close()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "already_running"
    assert "already active" in body["message"]
    assert body["result"]["users_total"] == 0
    assert body["result"]["created_issues"] == 0
    assert provider.calls == []
    assert await _issue_numbers(async_db, thread_id=thread.id) == []


@pytest.mark.asyncio
async def test_cron_partial_source_failure_preserves_successful_work(
    client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed volume is reported without rolling back the healthy volume."""
    secret = _configure_cron_secret(monkeypatch)
    good_thread = await _seed_source(
        async_db, user_id=default_user.id, volume_id=7301
    )
    await _seed_source(async_db, user_id=default_user.id, volume_id=7302)
    provider = _FakeProvider(
        {7301: [_released_row(73011, "1")]},
        failures={7302: ComicVineError("provider timeout")},
    )
    _use_provider(monkeypatch, provider)

    response = await client.get(CRON_URL, headers=_bearer(secret))

    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    assert result["users_processed"] == 1
    assert result["created_issues"] == 1
    assert result["failed_sources"] == 1
    assert result["successful_sources"] == 1
    assert len(result["failures"]) == 1
    assert result["failures"][0]["volume_id"] == 7302
    assert body["success"] is False
    assert await _issue_numbers(async_db, thread_id=good_thread.id) == ["1"]


@pytest.mark.asyncio
async def test_cron_retry_is_idempotent(
    client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retried daily invocation reuses the canonical issue instead of duplicating."""
    secret = _configure_cron_secret(monkeypatch)
    thread = await _seed_source(async_db, user_id=default_user.id, volume_id=7401)
    provider = _FakeProvider({7401: [_released_row(74011, "1")]})
    _use_provider(monkeypatch, provider)

    first = await client.get(CRON_URL, headers=_bearer(secret))
    second = await client.get(CRON_URL, headers=_bearer(secret))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["result"]["created_issues"] == 1
    assert second.json()["result"]["created_issues"] == 0
    assert second.json()["result"]["reused_issues"] == 1
    assert await _issue_numbers(async_db, thread_id=thread.id) == ["1"]


@pytest.mark.asyncio
async def test_cron_defers_owners_when_time_budget_is_exhausted(
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The serverless wall-clock budget stops starting new owners cleanly."""
    await _seed_source(async_db, user_id=default_user.id, volume_id=7501)
    provider = _FakeProvider({7501: [_released_row(75011, "1")]})

    # The first read starts the run at 0.0s; every later read reports 2.0s so
    # the loop check sees an exhausted budget while duration reads stay stable.
    pending_clock_reads: list[float] = [0.0]

    def fake_monotonic() -> float:
        return pending_clock_reads.pop() if pending_clock_reads else 2.0

    monkeypatch.setattr(
        sync_service, "time", SimpleNamespace(monotonic=fake_monotonic)
    )

    report = await run_scheduled_release_sync(
        async_db,
        as_of=FIXED_AS_OF,
        client=provider,
        max_duration_seconds=1.0,
    )

    assert report.status == "completed"
    assert report.truncated is True
    assert report.users_deferred == 1
    assert report.users_processed == 0
    assert report.success is False
    assert provider.calls == []


@pytest.mark.asyncio
async def test_cron_does_not_log_the_secret_or_provider_key(
    client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Structured logs and responses never expose deployment secrets."""
    secret = _configure_cron_secret(monkeypatch)
    provider_key = "comicvine-api-key-sentinel"
    monkeypatch.setenv("COMICVINE_API_KEY", provider_key)
    await _seed_source(async_db, user_id=default_user.id, volume_id=7601)
    _use_provider(
        monkeypatch, _FakeProvider({7601: [_released_row(76011, "1")]})
    )

    with caplog.at_level(logging.INFO):
        response = await client.get(CRON_URL, headers=_bearer(secret))

    assert response.status_code == 200
    assert secret not in response.text
    assert provider_key not in caplog.text
    assert secret not in caplog.text


def test_cron_route_is_hidden_from_the_generated_client_schema() -> None:
    """Operational cron routes must not leak into the frontend client contract."""
    from app.main import create_app

    schema = create_app(serve_frontend=False).openapi()

    assert CRON_URL not in schema["paths"]


def test_cron_router_delegates_to_the_service_layer() -> None:
    """The router must not import provider, adoption, or query logic."""
    source = (REPOSITORY_ROOT / "app" / "api" / "cron.py").read_text(
        encoding="utf-8"
    )

    assert "run_scheduled_release_sync" in source
    assert "ComicVine" not in source
    assert "adopt_comicvine_issue" not in source
    assert "fetch_volume_issues" not in source
    assert "select(" not in source
