"""Tests for DB-first ComicVine issue metadata fallback hydration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services import comicvine_fallback
from app.services import comicvine_intelligence
from app.services.comicvine_fallback import (
    _hydrate_with_retries,
    metadata_needs_hydration,
    refresh_issue_metadata,
)
from app.services.comicvine_intelligence import get_issue_intelligence
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineRateLimitError


def _deep_raw_payload() -> dict[str, object]:
    """Build the singular issue field shape used to distinguish deep hydration from roster data."""
    return {
        "id": 123,
        "name": "Issue title",
        "issue_number": "1",
        "cover_date": "2026-01-01",
        "store_date": "2025-12-15",
        "image": {},
        "volume": {"id": 456, "name": "Series"},
        "person_credits": [],
        "character_credits": [],
        "team_credits": [],
        "story_arc_credits": [],
        "date_last_updated": "2026-08-01T00:00:00+00:00",
    }


def _identity(*, metadata: dict[str, object], updated_at: datetime) -> ExternalIdentity:
    """Construct an in-memory ComicVine issue identity for freshness tests."""
    return ExternalIdentity(
        id=10,
        provider="comicvine",
        entity_type="issue",
        external_id="123",
        metadata_json=metadata,
        updated_at=updated_at,
    )


def test_metadata_freshness_distinguishes_deep_basic_and_stale_rows() -> None:
    """Only fresh singular-issue metadata avoids a provider fallback."""
    now = datetime(2026, 8, 11, tzinfo=UTC)
    fresh = _identity(
        metadata={"raw_provider_payload": _deep_raw_payload()},
        updated_at=now - timedelta(days=5),
    )
    basic = _identity(
        metadata={
            "raw_provider_payload": {
                "id": 123,
                "issue_number": "1",
                "volume": {"id": 456},
            }
        },
        updated_at=now - timedelta(days=1),
    )
    stale = _identity(
        metadata={"raw_provider_payload": _deep_raw_payload()},
        updated_at=now - timedelta(days=31),
    )

    assert metadata_needs_hydration(fresh, now=now) is False
    assert metadata_needs_hydration(basic, now=now) is True
    assert metadata_needs_hydration(stale, now=now) is True


class _FakeResult:
    """Minimal stand-in for a SQLAlchemy scalar result."""

    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeSession:
    """Context-manager stand-in for an AsyncSession used by hydration tests."""

    def __init__(
        self,
        *,
        lock_error: Exception | None = None,
        lock_value: bool = True,
    ) -> None:
        self._lock_error = lock_error
        self._lock_value = lock_value

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        if self._lock_error is not None:
            raise self._lock_error
        return _FakeResult(self._lock_value)


@pytest.mark.asyncio
async def test_refresh_defers_when_advisory_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-process deduplication stays in Postgres via the advisory transaction lock."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    monkeypatch.setattr(
        comicvine_fallback,
        "AsyncSessionLocal",
        lambda: _FakeSession(lock_value=False),
    )

    result = await refresh_issue_metadata(77)

    assert result is False


@pytest.mark.asyncio
async def test_refresh_handles_advisory_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB/advisory-lock TimeoutError is logged and returned, never leaked as a task exception."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    monkeypatch.setattr(
        comicvine_fallback,
        "AsyncSessionLocal",
        lambda: _FakeSession(lock_error=TimeoutError("advisory lock timed out")),
    )

    result = await refresh_issue_metadata(77)

    assert result is False


@pytest.mark.asyncio
async def test_refresh_handles_db_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pool checkout timeout is caught and returned instead of escaping the request."""
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")

    def _raising_session_factory() -> _FakeSession:
        raise sqlalchemy_exc.TimeoutError("pool checkout timed out")

    monkeypatch.setattr(comicvine_fallback, "AsyncSessionLocal", _raising_session_factory)

    result = await refresh_issue_metadata(77)

    assert result is False


@pytest.mark.asyncio
async def test_refresh_skips_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No provider work happens when the API key is absent from the environment."""
    monkeypatch.delenv("COMICVINE_API_KEY", raising=False)

    def _unexpected_factory() -> _FakeSession:
        raise AssertionError("session should never open without an API key")

    monkeypatch.setattr(comicvine_fallback, "AsyncSessionLocal", _unexpected_factory)

    result = await refresh_issue_metadata(77)

    assert result is False


def test_no_detached_task_scheduling_remains() -> None:
    """The fallback no longer exposes the unbounded background-task scheduler."""
    assert not hasattr(comicvine_fallback, "schedule_issue_metadata_hydration")
    assert not hasattr(comicvine_fallback, "_pending_hydrations")


@pytest.mark.asyncio
async def test_no_confirmed_mapping_never_schedules_provider_lookup(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue intelligence never guesses a ComicVine identity from title, thread, or issue number."""
    hydrated: list[int] = []

    async def fake_refresh(identity_id: int) -> bool:
        hydrated.append(identity_id)
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", fake_refresh)

    result = await get_issue_intelligence(async_db, issue_id=987_654_321, user_id=1)

    assert result is None
    assert hydrated == []


async def _mapped_issue(
    db: AsyncSession,
    *,
    metadata: dict[str, object],
    username: str,
) -> tuple[User, Issue, ExternalIdentity]:
    """Create one owned issue with a confirmed ComicVine issue-level mapping."""
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title="Fallback test series",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="123",
        metadata_json=metadata,
        updated_at=datetime.now(UTC),
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.flush()
    return user, issue, identity


@pytest.mark.asyncio
async def test_missing_metadata_hydrates_inline_but_returns_current_db_result(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing metadata row remains usable while its confirmed identity hydrates inline."""
    user, issue, identity = await _mapped_issue(
        async_db,
        metadata={"issue_number": "1"},
        username="comicvine_fallback_missing",
    )
    hydrated: list[int] = []

    async def fake_refresh(identity_id: int) -> bool:
        hydrated.append(identity_id)
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", fake_refresh)

    result = await get_issue_intelligence(async_db, issue.id, user.id)

    assert result is not None
    assert result.comicvine_issue_id == "123"
    assert result.issue_number == "1"
    assert hydrated == [identity.id]


@pytest.mark.asyncio
async def test_complete_metadata_causes_no_provider_hydration(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh singular issue metadata is served entirely from Postgres."""
    user, issue, _identity_row = await _mapped_issue(
        async_db,
        metadata={
            "issue_number": "1",
            "name": "Issue title",
            "volume": {"id": 456, "name": "Series"},
            "raw_provider_payload": _deep_raw_payload(),
        },
        username="comicvine_fallback_complete",
    )
    hydrated: list[int] = []

    async def fake_refresh(identity_id: int) -> bool:
        hydrated.append(identity_id)
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", fake_refresh)

    result = await get_issue_intelligence(async_db, issue.id, user.id)

    assert result is not None
    assert result.series_name == "Series"
    assert result.name == "Issue title"
    assert hydrated == []


@pytest.mark.asyncio
async def test_inline_hydration_serves_fresh_provider_metadata(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previously shallow identity serves the real provider image URL after inline hydration."""
    user, issue, identity = await _mapped_issue(
        async_db,
        metadata={"issue_number": "1"},
        username="comicvine_fallback_inline_refresh",
    )

    async def fake_refresh(identity_id: int) -> bool:
        row = await async_db.get(ExternalIdentity, identity_id)
        assert row is not None
        row.metadata_json = {
            "issue_number": "1",
            "name": "Martian Manhunter Annual",
            "primary_image": "https://static.comicvine.example/cover.jpg",
            "volume": {"id": 456, "name": "Series"},
            "raw_provider_payload": _deep_raw_payload(),
        }
        await async_db.flush()
        return True

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", fake_refresh)

    result = await get_issue_intelligence(async_db, issue.id, user.id)

    assert result is not None
    assert result.name == "Martian Manhunter Annual"
    assert result.image_url == "https://static.comicvine.example/cover.jpg"


@pytest.mark.asyncio
async def test_hydration_success_commits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful live hydration persists through the existing hydrator and commits once."""
    db = AsyncMock(spec=AsyncSession)
    client = cast(ComicVineClient, object())
    calls = 0

    async def fake_hydrate(
        db_arg: AsyncSession,
        client_arg: ComicVineClient,
        issue_id: int,
        *,
        refresh: bool = False,
    ) -> ExternalIdentity:
        nonlocal calls
        calls += 1
        assert db_arg is db
        assert client_arg is client
        assert issue_id == 123
        assert refresh is True
        return _identity(metadata={}, updated_at=datetime.now(UTC))

    monkeypatch.setattr(comicvine_fallback, "hydrate_issue", fake_hydrate)

    result = await _hydrate_with_retries(db, client, identity_id=10, issue_id=123)

    assert result is True
    assert calls == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [ComicVineError("malformed provider payload"), TimeoutError("provider timed out")],
)
async def test_provider_failure_retries_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Malformed responses and timeouts retry once, then stop without committing."""
    db = AsyncMock(spec=AsyncSession)
    client = cast(ComicVineClient, object())
    calls = 0

    async def fake_hydrate(
        db_arg: AsyncSession,
        client_arg: ComicVineClient,
        issue_id: int,
        *,
        refresh: bool = False,
    ) -> ExternalIdentity:
        del db_arg, client_arg, issue_id, refresh
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(comicvine_fallback, "hydrate_issue", fake_hydrate)
    monkeypatch.setattr(comicvine_fallback, "COMICVINE_FALLBACK_RETRY_DELAY_SECONDS", 0.0)

    result = await _hydrate_with_retries(db, client, identity_id=10, issue_id=123)

    assert result is False
    assert calls == 2
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_defers_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider rate limit never creates a retry burst from a product view."""
    db = AsyncMock(spec=AsyncSession)
    client = cast(ComicVineClient, object())
    calls = 0

    async def fake_hydrate(
        db_arg: AsyncSession,
        client_arg: ComicVineClient,
        issue_id: int,
        *,
        refresh: bool = False,
    ) -> ExternalIdentity:
        del db_arg, client_arg, issue_id, refresh
        nonlocal calls
        calls += 1
        raise ComicVineRateLimitError("rate limited")

    monkeypatch.setattr(comicvine_fallback, "hydrate_issue", fake_hydrate)

    result = await _hydrate_with_retries(db, client, identity_id=10, issue_id=123)

    assert result is False
    assert calls == 1
    db.commit.assert_not_awaited()
