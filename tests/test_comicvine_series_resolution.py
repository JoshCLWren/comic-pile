"""Regression tests for deterministic ComicVine series-based issue resolution.

These tests exercise the resolution service without live ComicVine access by
substituting a fake provider client. They guard against regressions in the
deterministic mapping logic and the post-commit attribute handling that previously
risked ``MissingGreenlet`` errors under async SQLAlchemy.
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
from app.services.comicvine_series_resolution import (
    _is_ambiguous_special,
    _normalize_issue_label,
    _run_series_resolution,
    schedule_series_issue_resolution,
)
from comic_pile.comicvine_provider import ComicVineResponse, ComicVineRateLimitError


@pytest_asyncio.fixture(autouse=True)
async def bind_resolution_session_factory(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Bind background resolution sessions to the current test engine."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(resolution_module, "AsyncSessionLocal", session_factory)
    yield


class _FakeComicVineClient:
    """Provider client stub that returns a single deterministic volume roster."""

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
            payload={
                "results": {
                    "id": issue_id,
                    "name": f"Issue {issue_id}",
                    "story_arc_credits": [],
                }
            },
            from_cache=False,
            cache_key=f"issue-{issue_id}",
        )


async def _seed(
    db: AsyncSession,
    *,
    username: str,
    issue_number: str,
    confirmed_series: bool,
) -> tuple[User, Issue, ExternalIdentity | None]:
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title="Series resolution thread",
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
    series_identity: ExternalIdentity | None = None
    if confirmed_series:
        series_identity = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id="4050-999",
            metadata_json={"volume_id": 999, "volume_name": "Series resolution thread"},
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
    return user, issue, series_identity


@pytest.mark.asyncio
async def test_normalize_issue_label_strips_hash_and_case(async_db: AsyncSession) -> None:
    """Labels are NFKC-normalized, hash-stripped, and lowercased."""
    assert _normalize_issue_label("#5") == "5"
    assert _normalize_issue_label("  Annual 1 ") == "annual 1"
    assert _normalize_issue_label(None) == ""
    assert _normalize_issue_label("＃12") == "12"


@pytest.mark.asyncio
async def test_is_ambiguous_special_detects_non_issue_volumes(async_db: AsyncSession) -> None:
    """Annuals, specials, one-shots, and giants are treated as ambiguous."""
    assert _is_ambiguous_special("Annual 1") is True
    assert _is_ambiguous_special("Giant-Size X") is True
    assert _is_ambiguous_special("One-Shot") is True
    assert _is_ambiguous_special("5") is False
    assert _is_ambiguous_special(None) is False


@pytest.mark.asyncio
async def test_schedule_skips_without_confirmed_series(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No background task is created when resolution cannot possibly succeed."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_noseries", issue_number="5", confirmed_series=False
    )
    spy = AsyncMock()
    monkeypatch.setattr(resolution_module, "_run_series_resolution", spy)

    scheduled = await schedule_series_issue_resolution(async_db_committed, issue.id, user.id)

    assert scheduled is False
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_runs_when_series_confirmed(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confirmed series mapping lets the resolver schedule and run."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_sched", issue_number="5", confirmed_series=True
    )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _FakeComicVineClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    scheduled = await schedule_series_issue_resolution(async_db_committed, issue.id, user.id)
    assert scheduled is True

    task = resolution_module._pending_resolutions[issue.id]
    await task

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
async def test_resolves_confirmed_mapping_from_series(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single deterministic match produces a confirmed issue mapping."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_happy", issue_number="5", confirmed_series=True
    )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _FakeComicVineClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    await _run_series_resolution(issue.id, user.id)

    mapping = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalar_one_or_none()
    assert mapping is not None
    assert mapping.status == "confirmed"
    assert mapping.confidence == 1.0
    hydrate.assert_awaited_once()
    assert hydrate.call_args.args[2] == 4005


@pytest.mark.asyncio
async def test_skips_when_already_confirmed(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing confirmed mapping prevents a duplicate resolution."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_existing", issue_number="5", confirmed_series=True
    )
    existing = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-99999",
        metadata_json={"issue_number": "5"},
    )
    async_db_committed.add(existing)
    await async_db_committed.flush()
    async_db_committed.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=existing.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await async_db_committed.commit()

    monkeypatch.setattr(resolution_module, "ComicVineClient", _FakeComicVineClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    await _run_series_resolution(issue.id, user.id)

    mappings = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalars().all()
    assert len(mappings) == 1
    assert mappings[0].external_identity_id == existing.id
    hydrate.assert_not_called()


@pytest.mark.asyncio
async def test_skips_ambiguous_special_issue(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issues that likely belong to another volume are not resolved."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_special", issue_number="Annual 1", confirmed_series=True
    )
    monkeypatch.setattr(resolution_module, "ComicVineClient", _FakeComicVineClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    await _run_series_resolution(issue.id, user.id)

    mapping = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalar_one_or_none()
    assert mapping is None
    hydrate.assert_not_called()


@pytest.mark.asyncio
async def test_defers_on_rate_limit(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider rate limit defers resolution without creating a mapping."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_ratelimit", issue_number="5", confirmed_series=True
    )

    class _RateLimitClient(_FakeComicVineClient):
        async def request(
            self, endpoint_bucket: str, endpoint: str, params: dict[str, object], *, refresh: bool = False
        ) -> ComicVineResponse:
            raise ComicVineRateLimitError("rate limited")

    monkeypatch.setattr(resolution_module, "ComicVineClient", _RateLimitClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    await _run_series_resolution(issue.id, user.id)

    mapping = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalar_one_or_none()
    assert mapping is None
    hydrate.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_match_does_not_auto_confirm(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for defect 1 (#1628): ambiguous multi-match must not be confirmed."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_duplicate", issue_number="5", confirmed_series=True
    )

    class _DuplicateClient(_FakeComicVineClient):
        async def request(
            self, endpoint_bucket: str, endpoint: str, params: dict[str, object], *, refresh: bool = False
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
                        },
                        {
                            "id": 4010,
                            "issue_number": "5",
                            "name": "Test Series #5 (duplicate)",
                            "site_detail_url": "https://comicvine.gamespot.com/issue/4000-4010/",
                            "volume": {"id": 999},
                        },
                    ],
                    "number_of_total_results": 2,
                    "limit": 100,
                    "offset": 0,
                },
                from_cache=False,
                cache_key="issues-duplicate",
            )

    monkeypatch.setattr(resolution_module, "ComicVineClient", _DuplicateClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    hydrate = AsyncMock()
    monkeypatch.setattr(resolution_module, "hydrate_issue", hydrate)

    await _run_series_resolution(issue.id, user.id)

    mappings = (
        await async_db_committed.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == issue.id
            )
        )
    ).scalars().all()
    # Ambiguous multi-match must not produce a confirmed mapping
    assert len(mappings) == 0 or all(m.status != "confirmed" for m in mappings)
    hydrate.assert_not_called()


@pytest.mark.asyncio
async def test_exception_containment_no_unretrieved_task(
    async_db_committed: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for defect 4 (#1628): unhandled exceptions must not escape."""
    user, issue, _series = await _seed(
        async_db_committed, username="series_res_exception", issue_number="5", confirmed_series=True
    )

    monkeypatch.setattr(resolution_module, "ComicVineClient", _FakeComicVineClient)
    monkeypatch.setenv("COMICVINE_API_KEY", "test-key")
    # Force an unhandled exception inside resolution (simulate DB/advisory failure)
    monkeypatch.setattr(
        resolution_module,
        "_run_series_resolution_impl",
        AsyncMock(side_effect=RuntimeError("simulated crash")),
    )

    # Schedule and await the background task; no unretrieved exception should escape.
    scheduled = await schedule_series_issue_resolution(async_db_committed, issue.id, user.id)
    assert scheduled is True
    task = resolution_module._pending_resolutions.get(issue.id)
    assert task is not None
    # Awaiting the task should complete without raising the simulated exception
    # because the outer wrapper catches it.
    await task


@pytest.mark.asyncio
async def test_find_existing_mapping_hardened_against_multiple_rows(
    async_db_committed: AsyncSession
) -> None:
    """Regression test for defect 5 (#1628): multiple non-confirmed rows must not raise."""
    from app.services.comicvine_series_resolution import _find_existing_mapping

    user = User(username="hardening_user")
    async_db_committed.add(user)
    await async_db_committed.flush()
    thread = Thread(
        title="Hardening thread",
        format="Comic",
        issues_remaining=1,
        user_id=user.id,
        status="active",
    )
    async_db_committed.add(thread)
    await async_db_committed.flush()
    issue = Issue(thread_id=thread.id, issue_number="99", position=1, status="unread")
    async_db_committed.add(issue)
    await async_db_committed.flush()

    identity1 = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-1",
    )
    identity2 = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-2",
    )
    async_db_committed.add(identity1)
    async_db_committed.add(identity2)
    await async_db_committed.flush()

    mapping1 = IssueExternalIdentityMapping(
        issue_id=issue.id,
        external_identity_id=identity1.id,
        status="candidate",
        confidence=0.5,
    )
    mapping2 = IssueExternalIdentityMapping(
        issue_id=issue.id,
        external_identity_id=identity2.id,
        status="candidate",
        confidence=0.5,
    )
    async_db_committed.add(mapping1)
    async_db_committed.add(mapping2)
    await async_db_committed.commit()

    # Should return the first row without raising MultipleResultsFound
    result = await _find_existing_mapping(async_db_committed, issue.id)
    assert result is not None
    assert result.status == "candidate"
