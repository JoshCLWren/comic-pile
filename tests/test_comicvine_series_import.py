"""Tests for the source-driven ComicVine series import (#2772).

Covers the one-click add happy path, similarly named run disambiguation via the
selected volume id, canonical issue reuse, optional already-read personal state,
irregular provider numbering, provider failure handling, and retry idempotency
(no duplicate thread or issue on retry).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from comic_pile.comicvine_provider import ComicVineError, ComicVineResponse

SERIES_URL = "/api/v1/comicvine/series:import"
VOLUME_ID = 40500


def _volume_response(name: str = "Stormwatch") -> ComicVineResponse:
    """Build a minimal decoded provider volume payload."""
    return ComicVineResponse(
        payload={
            "results": {
                "id": VOLUME_ID,
                "name": name,
                "publisher": {"name": "WildStorm"},
                "start_year": "1993",
                "count_of_issues": 3,
            }
        },
        from_cache=False,
        cache_key="volume",
    )


class _StubClient:
    """ComicVine client double that serves a fixed volume and issue roster."""

    def __init__(
        self,
        issues: list[dict[str, Any]],
        *,
        volume: ComicVineResponse | None = None,
        volume_error: Exception | None = None,
        issues_error: Exception | None = None,
        fetch_issue_error: Exception | None = None,
    ) -> None:
        self._issues = issues
        self._volume = volume if volume is not None else _volume_response()
        self._volume_error = volume_error
        self._issues_error = issues_error
        self._fetch_issue_error = fetch_issue_error

    async def fetch_volume(self, volume_id: int, **_kwargs: object) -> ComicVineResponse:
        if self._volume_error is not None:
            raise self._volume_error
        return self._volume

    async def fetch_volume_issues(
        self, volume_id: int, **_kwargs: object
    ) -> list[dict[str, Any]]:
        if self._issues_error is not None:
            raise self._issues_error
        return self._issues

    async def fetch_issue(self, issue_id: int, **_kwargs: object) -> ComicVineResponse:
        if self._fetch_issue_error is not None:
            raise self._fetch_issue_error
        return ComicVineResponse(
            payload={"results": {"id": issue_id, "name": "Stub", "issue_number": "1"}},
            from_cache=False,
            cache_key="issue",
        )


def _issue_rows(*issue_ids: int, numbers: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """Build provider issue rows, optionally with explicit irregular numbering."""
    numbers = numbers or {}
    return [
        {
            "id": issue_id,
            "issue_number": numbers.get(issue_id, str(issue_id)),
            "name": f"Issue {issue_id}",
            "site_detail_url": f"https://comicvine.gamespot.com/issue/4000-{issue_id}/",
        }
        for issue_id in issue_ids
    ]


def _install_client(
    monkeypatch: pytest.MonkeyPatch, client: _StubClient | None
) -> None:
    """Point the series-import endpoint at a stubbed provider client."""
    monkeypatch.setattr("app.api.comicvine_resolution._get_comicvine_client", lambda: client)


async def _confirmed_mappings(
    async_db: AsyncSession, thread_id: int
) -> list[str]:
    """Return the ComicVine issue ids confirmed against one thread."""
    result = await async_db.execute(
        select(ExternalIdentity.external_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .where(
            Issue.thread_id == thread_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == "comicvine",
        )
    )
    return sorted(result.scalars().all())


@pytest.mark.asyncio
async def test_series_import_creates_thread_and_adopts_roster(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One selection creates the local series and every provider issue with confirmed identity."""
    _install_client(monkeypatch, _StubClient(_issue_rows(101, 102, 103)))

    response = await auth_client.post(
        SERIES_URL,
        json={"comicvine_volume_id": VOLUME_ID},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["thread_created"] is True
    assert body["series_name"] == "Stormwatch"
    assert body["comicvine_volume_id"] == VOLUME_ID
    assert body["total_issues_in_series"] == 3
    assert body["issues_adopted"] == 3
    assert body["issues_skipped"] == 0
    assert body["issues_conflict"] == 0
    assert len(body["issue_results"]) == 3

    thread = await async_db.get(Thread, body["thread_id"])
    assert thread is not None
    assert thread.user_id == default_user.id
    # The local title comes from the provider, never from user re-entry.
    assert thread.title == "Stormwatch"
    assert thread.total_issues == 3
    assert thread.issues_remaining == 3
    assert thread.status == "active"

    issues = (
        (
            await async_db.execute(
                select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
            )
        )
        .scalars()
        .all()
    )
    assert [issue.issue_number for issue in issues] == ["101", "102", "103"]
    assert await _confirmed_mappings(async_db, thread.id) == ["101", "102", "103"]

    series_mapping = (
        (
            await async_db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == thread.id
                )
            )
        )
        .scalars()
        .first()
    )
    assert series_mapping is not None
    assert series_mapping.status == "confirmed"


@pytest.mark.asyncio
async def test_series_import_preserves_irregular_provider_numbering(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Annuals and fractional numbers survive verbatim rather than becoming a range."""
    _install_client(
        monkeypatch,
        _StubClient(
            _issue_rows(
                201, 202, 203, 204,
                numbers={201: "1", 202: "1.5", 203: "Annual 1", 204: "2"},
            )
        ),
    )

    response = await auth_client.post(
        SERIES_URL,
        json={"comicvine_volume_id": VOLUME_ID},
    )

    assert response.status_code == 201
    body = response.json()
    issues = (
        (
            await async_db.execute(
                select(Issue)
                .where(Issue.thread_id == body["thread_id"])
                .order_by(Issue.position)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(issue.issue_number for issue in issues) == [
        "1",
        "1.5",
        "2",
        "Annual 1",
    ]


@pytest.mark.asyncio
async def test_already_read_count_is_applied_as_personal_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Already-read progress marks leading rows read and updates derived counters."""
    _install_client(monkeypatch, _StubClient(_issue_rows(301, 302, 303)))

    response = await auth_client.post(
        SERIES_URL,
        json={"comicvine_volume_id": VOLUME_ID, "already_read_count": 2},
    )

    assert response.status_code == 201
    body = response.json()
    thread = await async_db.get(Thread, body["thread_id"])
    assert thread is not None
    assert thread.total_issues == 3
    assert thread.issues_remaining == 1

    issues = (
        (
            await async_db.execute(
                select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
            )
        )
        .scalars()
        .all()
    )
    assert [issue.status for issue in issues] == ["read", "read", "unread"]
    assert issues[0].read_at is not None
    assert issues[2].read_at is None
    assert thread.next_unread_issue_id == issues[2].id


@pytest.mark.asyncio
async def test_already_read_count_beyond_roster_completes_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-reported read count cannot exceed the roster or corrupt the counters."""
    _install_client(monkeypatch, _StubClient(_issue_rows(401, 402)))

    response = await auth_client.post(
        SERIES_URL,
        json={"comicvine_volume_id": VOLUME_ID, "already_read_count": 99},
    )

    assert response.status_code == 201
    body = response.json()
    thread = await async_db.get(Thread, body["thread_id"])
    assert thread is not None
    assert thread.total_issues == 2
    assert thread.issues_remaining == 0
    assert thread.status == "completed"
    assert thread.next_unread_issue_id is None


@pytest.mark.asyncio
async def test_retry_reuses_the_existing_thread_instead_of_duplicating_it(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the same volume twice adopts into the original series."""
    _install_client(monkeypatch, _StubClient(_issue_rows(501, 502)))

    first = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["thread_created"] is True

    second = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})
    assert second.status_code == 201
    second_body = second.json()
    assert second_body["thread_created"] is False
    assert second_body["thread_id"] == first_body["thread_id"]

    matching_threads = (
        await async_db.execute(
            select(Thread)
            .join(
                ThreadExternalSeriesMapping,
                ThreadExternalSeriesMapping.thread_id == Thread.id,
            )
            .join(
                ExternalIdentity,
                ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
            )
            .where(
                Thread.user_id == default_user.id,
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.external_id == str(VOLUME_ID),
            )
        )
    ).scalars().all()
    assert [thread.id for thread in matching_threads] == [first_body["thread_id"]]

    issues = (
        (
            await async_db.execute(
                select(Issue).where(Issue.thread_id == first_body["thread_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(issues) == 2
    assert sorted(issue.issue_number for issue in issues) == ["501", "502"]


@pytest.mark.asyncio
async def test_retry_after_partial_failure_adds_only_missing_issues(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first import that fails mid-roster leaves state a retry can complete."""
    # The third issue raises during hydration, so only the first two land.
    partial = _StubClient(_issue_rows(601, 602, 603), fetch_issue_error=ComicVineError("boom"))
    _install_client(monkeypatch, partial)

    first = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["thread_created"] is True

    # A healthy retry supplies the full roster for the same volume.
    _install_client(monkeypatch, _StubClient(_issue_rows(601, 602, 603)))

    second = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})
    assert second.status_code == 201
    second_body = second.json()
    assert second_body["thread_created"] is False
    assert second_body["thread_id"] == first_body["thread_id"]

    thread = await async_db.get(Thread, first_body["thread_id"])
    assert thread is not None
    assert thread.total_issues == 3
    assert thread.issues_remaining == 3
    assert len(await _confirmed_mappings(async_db, thread.id)) == 3


@pytest.mark.asyncio
async def test_distinct_volumes_create_distinct_threads(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two similarly named runs stay distinct series keyed by their volume id."""
    _install_client(
        monkeypatch,
        _StubClient(_issue_rows(701), volume=_volume_response("Ultimate Spider-Man")),
    )
    first = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})
    assert first.status_code == 201

    class _SecondClient(_StubClient):
        async def fetch_volume(self, volume_id: int, **_kwargs: object) -> ComicVineResponse:
            response = _volume_response("Ultimate Spider-Man")
            return ComicVineResponse(
                payload={**response.payload, "results": {**response.payload["results"], "id": 999}},
                from_cache=False,
                cache_key="volume",
            )

    _install_client(monkeypatch, _SecondClient(_issue_rows(702)))
    second = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": 999})
    assert second.status_code == 201

    assert second.json()["thread_created"] is True
    assert second.json()["thread_id"] != first.json()["thread_id"]


@pytest.mark.asyncio
async def test_provider_volume_failure_returns_bad_gateway(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure is bounded and creates no local state."""
    _install_client(
        monkeypatch,
        _StubClient(_issue_rows(801), volume_error=ComicVineError("provider down")),
    )

    response = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "provider_failure"


@pytest.mark.asyncio
async def test_provider_roster_failure_returns_bad_gateway(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A roster fetch failure surfaces as a bounded provider error, not a fake series."""
    _install_client(
        monkeypatch,
        _StubClient([], issues_error=ComicVineError("roster down")),
    )

    response = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "provider_failure"


@pytest.mark.asyncio
async def test_empty_roster_is_rejected_without_fabricating_a_series(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty provider roster fails closed rather than creating an empty thread."""
    _install_client(monkeypatch, _StubClient([]))

    response = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_issues"


@pytest.mark.asyncio
async def test_unconfigured_provider_returns_service_unavailable(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a configured provider the import fails closed, leaving manual add available."""
    _install_client(monkeypatch, None)

    response = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": VOLUME_ID})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_unavailable"


@pytest.mark.asyncio
async def test_import_rejects_invalid_volume_id(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-positive volume id is rejected by request validation before any provider call."""
    _install_client(monkeypatch, _StubClient([]))

    response = await auth_client.post(SERIES_URL, json={"comicvine_volume_id": 0})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_reading_order_returns_not_found(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown reading order target fails closed with a 404."""
    _install_client(monkeypatch, _StubClient(_issue_rows(901)))

    response = await auth_client.post(
        SERIES_URL,
        json={"comicvine_volume_id": VOLUME_ID, "reading_order_id": 999999},
    )

    assert response.status_code == 404