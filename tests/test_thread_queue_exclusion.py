"""Regression coverage for non-destructive "Remove from Queue" (#3807).

The contract these tests pin down:

1. Excluding a series is reversible and lossless. The same Thread and Issue
   rows, issue numbers/positions, read state and timestamps, ratings and
   events, ComicVine mappings, reading-list ordering, and CBL membership
   survive both the exclusion and the restore. No row is recreated, so no
   identifier changes.
2. The exclusion is durable. Reading and issue adoption recompute lifecycle
   status from issue state; that recomputation must not silently end a
   reader's queue exclusion, because an excluded series has to stay
   restorable until it is explicitly asked for.
3. The exclusion is scoped to one reader.
4. Queue removal is explicitly distinct from permanent deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password
from app.models import (
    CustomCBLEntry,
    CustomCBLList,
    Dependency,
    Event,
    ExternalIdentity,
    Issue,
    IssueExternalIdentityMapping,
    Thread,
    User,
)
from app.services.roll_exclusion import derive_effective_roll_excluded_thread_ids
from app.services.thread_service import list_queue_threads

PASSWORD_HASH = hash_password("password")

#: Stable read timestamp so preservation assertions compare real values instead
#: of "still truthy" checks.
READ_AT = datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
RATED_AT = datetime(2024, 3, 2, 9, 30, tzinfo=UTC)

OWNER_USERNAME = "exclusion_owner"
OTHER_USERNAME = "exclusion_other_reader"


@dataclass(frozen=True)
class SeriesIds:
    """Identifiers captured before any exclusion happens."""

    title: str
    thread_id: int
    read_issue_id: int
    unread_issue_ids: tuple[int, ...]
    event_id: int
    series_identity_id: int
    issue_mapping_id: int
    strict_entry_id: int
    dependency_id: int


@dataclass(frozen=True)
class CuratedState:
    """The reader-curated records a queue removal must leave untouched."""

    event_rating: float | None
    event_issue_number: str | None
    series_external_id: str
    issue_mapping_status: str
    issue_mapping_issue_id: int
    strict_entry_position: int
    strict_entry_gate: str
    dependency_classification: str | None
    dependency_source_issue_id: int
    dependency_target_issue_id: int


@pytest_asyncio.fixture(scope="function")
async def owning_reader(async_db: AsyncSession) -> User:
    """A password-bearing reader who owns the series under test."""
    user = User(username=OWNER_USERNAME, password_hash=PASSWORD_HASH, created_at=None)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def other_reader(async_db: AsyncSession) -> User:
    """A second reader used for the cross-reader isolation contract."""
    user = User(username=OTHER_USERNAME, password_hash=PASSWORD_HASH, created_at=None)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    return user


async def _seed_series(async_db: AsyncSession, user: User, suffix: str = "a") -> SeriesIds:
    """Build a series carrying every reader-owned record the contract protects.

    The fixture deliberately mixes read and unread issues, a rated event, a
    confirmed series identity, a confirmed issue mapping, a strict reading-list
    entry, and a reader-created ordering dependency, so one round trip can prove
    that removal and restoration preserve curated state.

    Args:
        async_db: Database session owned by the test.
        user: Reader who owns the series.
        suffix: Distinguishes the externally unique provider identities so one
            test can seed several series for the same reader.

    Returns:
        Identifiers captured before any exclusion happens.
    """
    title = f"Descender {suffix}"
    thread = Thread(
        title=title,
        format="Comic",
        total_issues=3,
        issues_remaining=2,
        queue_position=1,
        status="active",
        reading_progress="in_progress",
        notes="Keep the collected covers order",
        last_rating=4.5,
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    read_issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=READ_AT,
    )
    unread_a = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread")
    unread_b = Issue(thread_id=thread.id, issue_number="3", position=3, status="unread")
    async_db.add_all([read_issue, unread_a, unread_b])
    await async_db.flush()

    thread.next_unread_issue_id = unread_a.id

    rated_event = Event(
        type="rate",
        timestamp=RATED_AT,
        thread_id=thread.id,
        issue_id=read_issue.id,
        issue_number="1",
        rating=4.5,
        die=6,
    )
    async_db.add(rated_event)

    series_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=f"83310-{suffix}",
        external_url="https://comicvine.gamespot.com/descender/4050-83310/",
    )
    issue_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"6001234-123456-{suffix}",
    )
    async_db.add_all([series_identity, issue_identity])
    await async_db.flush()

    issue_mapping = IssueExternalIdentityMapping(
        issue_id=unread_a.id,
        external_identity_id=issue_identity.id,
        status="confirmed",
        evidence_source="reader",
        confidence=1.0,
    )
    async_db.add(issue_mapping)

    strict_list = CustomCBLList(user_id=user.id, name=f"Imprint canon {suffix}", mode="strict")
    async_db.add(strict_list)
    await async_db.flush()

    strict_entry = CustomCBLEntry(
        list_id=strict_list.id,
        issue_id=unread_a.id,
        position=1,
        gate="after_previous",
    )
    async_db.add(strict_entry)

    ordering = Dependency(
        source_issue_id=read_issue.id,
        target_issue_id=unread_a.id,
        origin="reader",
        classification="A",
    )
    async_db.add(ordering)

    # The session does not expire on commit, so every flushed row already
    # carries the primary key the assertions below compare against.
    await async_db.commit()

    return SeriesIds(
        title=title,
        thread_id=thread.id,
        read_issue_id=read_issue.id,
        unread_issue_ids=(unread_a.id, unread_b.id),
        event_id=rated_event.id,
        series_identity_id=series_identity.id,
        issue_mapping_id=issue_mapping.id,
        strict_entry_id=strict_entry.id,
        dependency_id=ordering.id,
    )


async def _issue_rows(async_db: AsyncSession, thread_id: int) -> list[Issue]:
    """Load every issue row a thread owns, in canonical order."""
    return list(
        (
            await async_db.execute(
                select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
            )
        )
        .scalars()
        .all()
    )


async def _curated_state(async_db: AsyncSession, ids: SeriesIds) -> CuratedState:
    """Capture the reader-curated records a queue removal must not disturb.

    Args:
        async_db: Database session owned by the test.
        ids: Series identifiers.

    Returns:
        A comparable snapshot of every curated record.

    Raises:
        AssertionError: When a protected record has gone missing.
    """
    event = await async_db.get(Event, ids.event_id)
    series_identity = await async_db.get(ExternalIdentity, ids.series_identity_id)
    issue_mapping = await async_db.get(IssueExternalIdentityMapping, ids.issue_mapping_id)
    strict_entry = await async_db.get(CustomCBLEntry, ids.strict_entry_id)
    dependency = await async_db.get(Dependency, ids.dependency_id)

    assert event is not None, "rated event was removed"
    assert series_identity is not None, "series mapping identity was removed"
    assert issue_mapping is not None, "issue mapping was removed"
    assert strict_entry is not None, "reading-list membership was pruned"
    assert dependency is not None, "reader ordering dependency was pruned"

    return CuratedState(
        event_rating=event.rating,
        event_issue_number=event.issue_number,
        series_external_id=series_identity.external_id,
        issue_mapping_status=issue_mapping.status,
        issue_mapping_issue_id=issue_mapping.issue_id,
        strict_entry_position=strict_entry.position,
        strict_entry_gate=strict_entry.gate,
        dependency_classification=dependency.classification,
        dependency_source_issue_id=dependency.source_issue_id,
        dependency_target_issue_id=dependency.target_issue_id,
    )


async def _assert_thread_preserved(
    async_db: AsyncSession, ids: SeriesIds, before: CuratedState
) -> None:
    """Assert the thread row and every curated record survived unchanged.

    The denormalized reading counters are deliberately not asserted here: they
    are derived state that legitimately moves when the reader reads or adopts
    issues. Identity, personal metadata, and curated mappings are not derived,
    so those are what must be byte-for-byte identical.

    Args:
        async_db: Database session owned by the test.
        ids: Series identifiers.
        before: Curated state captured before the removal.
    """
    async_db.expire_all()

    thread = await async_db.get(Thread, ids.thread_id)
    assert thread is not None, "queue removal deleted the thread"
    assert thread.title == ids.title
    assert thread.notes == "Keep the collected covers order"
    assert thread.format == "Comic"
    assert thread.last_rating == 4.5
    assert await _curated_state(async_db, ids) == before


async def _assert_issue_rows_unchanged(async_db: AsyncSession, ids: SeriesIds) -> None:
    """Assert every issue kept its identity, numbering, position, and read state.

    Args:
        async_db: Database session owned by the test.
        ids: Series identifiers.
    """
    async_db.expire_all()
    issues = await _issue_rows(async_db, ids.thread_id)
    assert [issue.id for issue in issues] == [ids.read_issue_id, *ids.unread_issue_ids]
    assert [issue.issue_number for issue in issues] == ["1", "2", "3"]
    assert [issue.position for issue in issues] == [1, 2, 3]
    assert [issue.status for issue in issues] == ["read", "unread", "unread"]
    assert issues[0].read_at == READ_AT
    assert issues[1].read_at is None
    assert issues[2].read_at is None


def _auth_headers(username: str) -> dict[str, str]:
    """Build request headers for an existing test reader.

    Args:
        username: Existing reader username.

    Returns:
        Authorization headers for that reader.
    """
    token = create_access_token(data={"sub": username, "jti": str(uuid4())})
    return {"Authorization": f"Bearer {token}"}


async def _excluded_thread_ids(auth_client: AsyncClient) -> list[int]:
    """Read the reader's excluded library view and return its thread ids."""
    response = await auth_client.get("/api/v1/threads/excluded/threads")
    assert response.status_code == 200
    return [row["id"] for row in response.json()["threads"]]


async def _queue_thread_ids(async_db: AsyncSession, user_id: int) -> list[int]:
    """Read the active queue projection and return its thread ids."""
    page = await list_queue_threads(
        async_db, user_id, search=None, sort="position", page_size=200, page_token=None
    )
    return [row.id for row in page.threads]


async def _completed_thread_ids(auth_client: AsyncClient) -> list[int]:
    """Read the finished shelf and return its thread ids."""
    response = await auth_client.get("/api/v1/threads/completed/threads")
    assert response.status_code == 200
    return [row["id"] for row in response.json()["threads"]]


