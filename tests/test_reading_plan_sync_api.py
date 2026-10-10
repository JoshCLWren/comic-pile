"""API contract tests for Reading Plan release-source sync endpoints (#3117)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sqlalchemy import select

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.models.user import User
from app.services import reading_plan_sync_service as sync_service
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineResponse
from tests.conftest import get_or_create_user_async

SYNC_URL = "/api/v1/reading-plan-sync/sync"
STATUS_URL = "/api/v1/reading-plan-sync/status"


@dataclass
class _FakeProvider(ComicVineClient):
    """Provider double returning a fixed released roster."""

    rosters: dict[int, list[dict[str, object]]] = field(default_factory=dict)

    def __init__(self, rosters: dict[int, list[dict[str, object]]] | None = None) -> None:
        self.rosters = rosters or {}

    async def fetch_volume_issues(
        self, volume_id: int, *, refresh: bool = False
    ) -> list[dict[str, object]]:
        return list(self.rosters.get(volume_id, []))

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        raise ComicVineError("fake provider does not hydrate issues")

    async def fetch_story_arc(self, arc_id: int, *, refresh: bool = False) -> ComicVineResponse:
        raise ComicVineError("fake provider has no story arcs")


def _released_row(issue_id: int, issue_number: str) -> dict[str, object]:
    return {
        "id": issue_id,
        "issue_number": issue_number,
        "store_date": "2025-06-01",
        "cover_date": "1999-01-01",
    }


async def _seed_source(
    db: AsyncSession,
    *,
    user_id: int,
    volume_id: int,
    enabled: bool = True,
) -> Thread:
    """Create a plan, thread, confirmed volume mapping, and release source."""
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
        ))
    return thread


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider) -> None:
    monkeypatch.setattr(
        sync_service, "build_comicvine_client", lambda: provider, raising=True
    )


@pytest.mark.asyncio
async def test_sync_endpoint_adopts_released_issue(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint adopts released issues and returns structured counters."""
    user = default_user
    await _seed_source(async_db, user_id=user.id, volume_id=6101)
    provider = _FakeProvider({6101: [_released_row(61011, "1")]})
    _use_provider(monkeypatch, provider)

    response = await auth_client.post(
        SYNC_URL, json={"as_of": "2025-06-15T00:00:00Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True, body
    assert "1 created" in body["message"]
    result = body["result"]
    assert result["enabled_sources"] == 1
    assert result["successful_sources"] == 1
    assert result["failed_sources"] == 0
    assert result["created_issues"] == 1
    assert result["future_skips"] == 0
    assert result["unknown_date_skips"] == 0
    assert result["conflicts"] == 0
    assert result["failures"] == []


@pytest.mark.asyncio
async def test_sync_endpoint_reports_future_skips(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Future solicitations are reported rather than adopted."""
    user = default_user
    await _seed_source(async_db, user_id=user.id, volume_id=6201)
    provider = _FakeProvider({6201: [_released_row(62011, "1")]})
    _use_provider(monkeypatch, provider)

    response = await auth_client.post(
        SYNC_URL, json={"as_of": "2020-01-01T00:00:00Z"}
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["future_skips"] == 1
    assert result["created_issues"] == 0


@pytest.mark.asyncio
async def test_sync_endpoint_requires_authentication(
    client: AsyncClient,
) -> None:
    """An unauthenticated sync request is rejected."""
    response = await client.post(SYNC_URL, json={"as_of": "2025-06-15T00:00:00Z"})

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sync_endpoint_rejects_malformed_as_of(
    auth_client: AsyncClient,
) -> None:
    """A non-datetime boundary is a validation error, not a 500."""
    response = await auth_client.post(SYNC_URL, json={"as_of": "not-a-date"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sync_endpoint_only_touches_the_calling_user(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sync request cannot adopt into another reader's thread."""
    stranger = await get_or_create_user_async(async_db, "api_sync_stranger@test.com")
    stranger_thread = await _seed_source(async_db, user_id=stranger.id, volume_id=6301)
    provider = _FakeProvider({6301: [_released_row(63011, "1")]})
    _use_provider(monkeypatch, provider)

    response = await auth_client.post(
        SYNC_URL, json={"as_of": "2025-06-15T00:00:00Z"}
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["enabled_sources"] == 0
    assert result["created_issues"] == 0
    assert stranger_thread.user_id == stranger.id

    issues = await auth_client.get(f"/api/v1/threads/{stranger_thread.id}/issues/")
    if issues.status_code == 200:
        assert issues.json() == []


@pytest.mark.asyncio
async def test_status_endpoint_reports_persisted_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Status exposes every release source the caller owns."""
    user = default_user
    await _seed_source(async_db, user_id=user.id, volume_id=6401)
    await _seed_source(async_db, user_id=user.id, volume_id=6402, enabled=False)

    response = await auth_client.get(STATUS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["total_sources"] == 2
    assert body["enabled_sources"] == 1
    assert {source["provider_volume_id"] for source in body["sources"]} == {
        "6401",
        "6402",
    }
    assert all(source["last_synced_at"] is None for source in body["sources"])


@pytest.mark.asyncio
async def test_sync_endpoint_persists_adopted_issue(
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint commits its writes instead of rolling them back.

    The request runs against a real-committing session and a fresh
    connection reads the result back, so a flush-only implementation
    fails this test.

    The user is created through the committed session: pairing the
    committed session with the rollback-isolated ``async_db`` fixture
    would hold ``TRUNCATE ... CASCADE`` locks on ``threads`` and
    ``users`` while the request queries them, deadlocking the run.
    """
    from httpx import ASGITransport

    from app.auth import create_access_token
    from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
    from app.database import get_db
    from app.main import app
    from tests.conftest import _create_async_db_override

    db = async_db_committed
    user = await get_or_create_user_async(db, "sync_persist_committed@test.com")
    thread = await _seed_source(db, user_id=user.id, volume_id=6601)
    provider = _FakeProvider({6601: [_released_row(66011, "1")]})
    _use_provider(monkeypatch, provider)

    app.dependency_overrides[get_db] = await _create_async_db_override(db)
    try:
        csrf = generate_csrf_token()
        token = create_access_token(data={"sub": user.username, "jti": "sync"})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as caller:
            caller.cookies.set(CSRF_COOKIE_NAME, csrf)
            caller.headers[CSRF_HEADER_NAME] = csrf
            caller.headers["Authorization"] = f"Bearer {token}"
            response = await caller.post(
                SYNC_URL, json={"as_of": "2025-06-15T00:00:00Z"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["result"]["created_issues"] == 1

    verifier = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with verifier() as fresh:
        stored = await fresh.scalar(
            select(Issue.issue_number).where(Issue.thread_id == thread.id)
        )
    assert stored == "1"


@pytest.mark.asyncio
async def test_status_endpoint_requires_authentication(client: AsyncClient) -> None:
    """An unauthenticated status request is rejected."""
    response = await client.get(STATUS_URL)

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sync_then_status_shows_last_synced_at(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful sync advances last_synced_at for the evaluated source."""
    user = default_user
    await _seed_source(async_db, user_id=user.id, volume_id=6501)
    provider = _FakeProvider({6501: [_released_row(65011, "1")]})
    _use_provider(monkeypatch, provider)

    sync_response = await auth_client.post(
        SYNC_URL, json={"as_of": "2025-06-15T00:00:00Z"}
    )
    assert sync_response.status_code == 200

    status_response = await auth_client.get(STATUS_URL)
    assert status_response.status_code == 200
    sources = status_response.json()["sources"]
    assert len(sources) == 1
    assert sources[0]["last_synced_at"] is not None
    assert datetime.fromisoformat(
        sources[0]["last_synced_at"].replace("Z", "+00:00")
    ).tzinfo is not None
    assert sources[0]["last_synced_at"].endswith("Z") or sources[0][
        "last_synced_at"
    ].endswith("+00:00")
    assert sources[0]["provider_volume_id"] == "6501"
    assert UTC is not None