"""Regression tests for the bounded unmapped-issue backfill reconciliation.

These tests exercise ``reconcile_unmapped_issues`` end to end against a real
test database, with the deterministic series resolver's provider client
substituted by fakes. They guard the #1628 Phase 2 contract: correct
prioritization, truthful confirmed/candidate/unresolved/skipped counts,
idempotency on rerun, and zero pseudo-identity fabrication.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.services import comicvine_series_resolution as resolution_module
from app.services.catalog import reconcile_unmapped_issues
from comic_pile.comicvine_provider import ComicVineResponse, ComicVineRateLimitError


@pytest_asyncio.fixture(autouse=True)
async def bind_resolution_session_factory(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Bind background resolution sessions to the current test engine."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(resolution_module, "AsyncSessionLocal", session_factory)
    yield


class _SingleMatchClient:
    """Provider stub returning exactly one roster match for issue 5."""

    def __init__(self, api_key: str, cache_dir: str | Path, timeout_seconds: float = 5.0) -> None:
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds

    async def request(
        self,
        endpoint_bucket: str,
        endpoint: str,
        params: dict[str, object],
        *,
        refresh: bool = False,
    ) -> ComicVineResponse:
        return ComicVineResponse(
            payload={
                "results": [
                    {
                        "id": 4005,
                        "issue_number": "5",
                        "name": "Test Series #5",
                        "site_detail_url": "https://comicvine.gamespot.com/issue/4000-4005/",
                        "volume": {"id": 999},
                    }
                ],
                "number_of_total_results": 1,
                "limit": 100,
                "offset": 0,
            },
            from_cache=False,
            cache_key="issues-999",
        )

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        return ComicVineResponse(
            payload={"results": {"id": issue_id, "name": f"Issue {issue_id}"}},
            from_cache=False,
            cache_key=f"issue-{issue_id}",
        )


class _RateLimitClient(_SingleMatchClient):
    """Provider stub that always raises the rate-limit error."""

    async def request(
        self,
        endpoint_bucket: str,
        endpoint: str,
        params: dict[str, object],
        *,
        refresh: bool = False,
    ) -> ComicVineResponse:
        raise ComicVineRateLimitError("rate limited")


async def _seed_thread_with_confirmed_series(
    db: AsyncSession,
    *,
    username: str,
    issue_number: str = "5",
    series_external_id: str = "4050-999",
) -> tuple[User, Thread, Issue, ExternalIdentity]:
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title="Backfill thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number=issue_number, position=1, status="unread")
    db.add(issue)
    await db.flush()
    series_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=series_external_id,
        metadata_json={"volume_id": 999, "volume_name": "Backfill thread"},
    )
    db.add(series_identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=series_identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.commit()
    return user, thread, issue, series_identity


@pytest.mark.asyncio
async def test_backfill_confirms_single_match(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An issue in a confirmed-series thread is confirmed via the resolver."""
    _user, _thread, issue, _series = await _seed_thread_with_confirmed_series(
        async_db_committed, username="backfill_confirm"
    )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _SingleMatchClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    counts = await reconcile_unmapped_issues(async_db_committed)

    assert counts == {"confirmed": 1, "candidate": 0, "unresolved": 0, "skipped": 0}
    mapping = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalar_one_or_none()
    assert mapping is not None
    assert mapping.status == "confirmed"
    hydrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_reports_unresolved_without_confirmed_series(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issues without a confirmed thread series stay untouched and unresolved."""
    user = User(username="backfill_noseries")
    async_db_committed.add(user)
    await async_db_committed.flush()
    thread = Thread(
        title="No series thread",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db_committed.add(thread)
    await async_db_committed.flush()
    issue = Issue(thread_id=thread.id, issue_number="7", position=1, status="unread")
    async_db_committed.add(issue)
    await async_db_committed.commit()

    spy_client = AsyncMock()
    monkeypatch.setattr(resolution_module, "ComicVineClient", spy_client)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")

    counts = await reconcile_unmapped_issues(async_db_committed)

    assert counts == {"confirmed": 0, "candidate": 0, "unresolved": 1, "skipped": 0}
    mappings = (
        (
            await async_db_committed.execute(
                select(IssueExternalIdentityMapping).where(
                    IssueExternalIdentityMapping.issue_id == issue.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert mappings == []
    spy_client.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_defers_on_rate_limit(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider rate limit leaves the issue unmapped and counted unresolved."""
    _user, _thread, issue, _series = await _seed_thread_with_confirmed_series(
        async_db_committed, username="backfill_ratelimit"
    )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _RateLimitClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")

    counts = await reconcile_unmapped_issues(async_db_committed)

    assert counts == {"confirmed": 0, "candidate": 0, "unresolved": 1, "skipped": 0}
    mapping = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalar_one_or_none()
    assert mapping is None


@pytest.mark.asyncio
async def test_backfill_counts_existing_candidate_without_duplicates(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing non-confirmed mapping counts as candidate and stays unique."""
    _user, _thread, issue, _series = await _seed_thread_with_confirmed_series(
        async_db_committed, username="backfill_candidate"
    )
    existing_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-777",
        metadata_json={"issue_number": "5"},
    )
    async_db_committed.add(existing_identity)
    await async_db_committed.flush()
    candidate = IssueExternalIdentityMapping(
        issue_id=issue.id,
        external_identity_id=existing_identity.id,
        status="candidate",
        confidence=0.5,
    )
    async_db_committed.add(candidate)
    await async_db_committed.commit()

    monkeypatch.setattr(resolution_module, "ComicVineClient", _RateLimitClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")

    counts = await reconcile_unmapped_issues(async_db_committed)

    assert counts == {"confirmed": 0, "candidate": 1, "unresolved": 0, "skipped": 0}
    mappings = (
        (await async_db_committed.execute(select(IssueExternalIdentityMapping)))
        .scalars()
        .all()
    )
    assert len(mappings) == 1
    assert mappings[0].id == candidate.id
    assert mappings[0].status == "candidate"


@pytest.mark.asyncio
async def test_backfill_is_idempotent_on_rerun(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rerunning the backfill after confirmation performs no duplicate work."""
    _user, _thread, issue, _series = await _seed_thread_with_confirmed_series(
        async_db_committed, username="backfill_idempotent"
    )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _SingleMatchClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    first = await reconcile_unmapped_issues(async_db_committed)
    assert first["confirmed"] == 1

    second = await reconcile_unmapped_issues(async_db_committed)
    assert second == {"confirmed": 0, "candidate": 0, "unresolved": 0, "skipped": 0}

    mappings = (
        (await async_db_committed.execute(select(IssueExternalIdentityMapping)))
        .scalars()
        .all()
    )
    assert len(mappings) == 1
    assert mappings[0].issue_id == issue.id
    assert mappings[0].status == "confirmed"


@pytest.mark.asyncio
async def test_backfill_respects_limit(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The limit bounds how many issues are processed in one pass."""
    for index in range(3):
        await _seed_thread_with_confirmed_series(
            async_db_committed,
            username=f"backfill_limit_{index}",
            issue_number="5",
            series_external_id=f"4050-999{index}",
        )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _SingleMatchClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")

    counts = await reconcile_unmapped_issues(async_db_committed, limit=2)

    assert counts == {"confirmed": 2, "candidate": 0, "unresolved": 0, "skipped": 0}
