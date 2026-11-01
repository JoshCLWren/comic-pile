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
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
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
from app.services.snooze_service import derive_effective_roll_excluded_thread_ids
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


async def _login(client: AsyncClient, username: str) -> dict[str, str]:
    """Authenticate a reader and return its request headers.

    Args:
        client: Unauthenticated client.
        username: Reader to log in as.

    Returns:
        Authorization headers for that reader.
    """
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "password"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


@pytest.mark.asyncio
async def test_remove_from_queue_preserves_records_and_restore_reuses_the_same_rows(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Removing a series loses nothing, and restoring reuses the same rows.

    This is the load-bearing acceptance case for #3807: a series with read and
    unread issues, a rated event, a confirmed series identity, a confirmed
    issue mapping, a strict reading-list entry, and a reader ordering
    dependency must come back with identical identifiers and curated state
    rather than being recreated.
    """
    owner_id = default_user.id
    ids = await _seed_series(async_db, default_user)
    before = await _curated_state(async_db, ids)

    exclude_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert exclude_response.status_code == 200
    assert exclude_response.json()["status"] == "excluded"

    await _assert_issue_rows_unchanged(async_db, ids)
    await _assert_thread_preserved(async_db, ids, before)

    thread = await async_db.get(Thread, ids.thread_id)
    assert thread is not None
    assert thread.status == "excluded"
    assert thread.queue_position == 0

    # It leaves the active queue entirely and becomes discoverable in the
    # excluded library view instead.
    assert ids.thread_id not in await _queue_thread_ids(async_db, owner_id)
    assert await _excluded_thread_ids(auth_client) == [ids.thread_id]

    excluded_page = await auth_client.get("/api/v1/threads/excluded/threads")
    # Unread issues are preserved, never silently marked read by the removal.
    assert excluded_page.json()["threads"][0]["issues_remaining"] == 2

    restore_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/restore")
    assert restore_response.status_code == 200
    assert restore_response.json()["id"] == ids.thread_id

    await _assert_issue_rows_unchanged(async_db, ids)
    await _assert_thread_preserved(async_db, ids, before)

    restored = await async_db.get(Thread, ids.thread_id)
    assert restored is not None
    assert restored.status == "active"
    assert restored.queue_position >= 1
    assert restored.next_unread_issue_id == ids.unread_issue_ids[0]

    assert ids.thread_id in await _queue_thread_ids(async_db, owner_id)
    assert await _excluded_thread_ids(auth_client) == []


@pytest.mark.asyncio
async def test_exclusion_survives_reading_the_final_unread_issue(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Reading every issue must not silently reactivate an excluded series.

    Marking the last unread issue read recomputes the thread lifecycle to
    ``completed``. A durable queue exclusion outranks that recomputation: the
    series has to stay excluded, and therefore restorable, until the reader
    asks for it. Otherwise removal is a one-way trip to the wrong shelf.
    """
    ids = await _seed_series(async_db, default_user)
    before = await _curated_state(async_db, ids)

    exclude_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert exclude_response.status_code == 200

    for issue_id in ids.unread_issue_ids:
        mark_read = await auth_client.post(f"/api/v1/issues/{issue_id}:markRead")
        assert mark_read.status_code == 204

    async_db.expire_all()
    thread = await async_db.get(Thread, ids.thread_id)
    assert thread is not None
    assert thread.status == "excluded"
    assert thread.queue_position == 0
    assert thread.issues_remaining == 0

    # Read state is recorded normally; only the lifecycle status is preserved.
    async_db.expire_all()
    issues = await _issue_rows(async_db, ids.thread_id)
    assert [issue.status for issue in issues] == ["read", "read", "read"]
    assert all(issue.read_at is not None for issue in issues)

    await _assert_thread_preserved(async_db, ids, before)

    # Still excluded, still discoverable, still restorable.
    assert await _excluded_thread_ids(auth_client) == [ids.thread_id]

    restore_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/restore")
    assert restore_response.status_code == 200


@pytest.mark.asyncio
async def test_restore_returns_a_fully_read_series_to_the_finished_shelf(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Restoring a series with nothing left to read must not create a queue ghost.

    An ``active`` thread with an empty reading frontier violates the completion
    invariant that Roll and the queue eligibility predicates rely on, so a fully
    read series returns to the finished shelf with all of its history intact.
    """
    owner_id = default_user.id
    ids = await _seed_series(async_db, default_user)
    before = await _curated_state(async_db, ids)

    exclude_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert exclude_response.status_code == 200

    for issue_id in ids.unread_issue_ids:
        mark_read = await auth_client.post(f"/api/v1/issues/{issue_id}:markRead")
        assert mark_read.status_code == 204

    restore_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/restore")
    assert restore_response.status_code == 200
    assert restore_response.json()["status"] == "completed"

    async_db.expire_all()
    restored = await async_db.get(Thread, ids.thread_id)
    assert restored is not None
    assert restored.status == "completed"
    assert restored.queue_position == 0
    assert restored.next_unread_issue_id is None

    # The curated state the reader protected is still there, and the finished
    # shelf — not the active queue — owns the series again.
    await _assert_thread_preserved(async_db, ids, before)
    assert ids.thread_id in await _completed_thread_ids(auth_client)
    assert ids.thread_id not in await _queue_thread_ids(async_db, owner_id)
    assert await _excluded_thread_ids(auth_client) == []


@pytest.mark.asyncio
async def test_excluded_series_stays_out_of_the_roll_pool(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Roll eligibility honors a durable removal, not only a session snooze."""
    # Capture the owner id up front. expire_all() below drops every loaded
    # attribute off the session, and reading default_user.id afterwards would
    # trigger a synchronous lazy reload inside the greenlet that owns the
    # event loop (MissingGreenlet). The id is a stable fixture value, not
    # derived state.
    user_id = default_user.id
    ids = await _seed_series(async_db, default_user)

    exclude_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert exclude_response.status_code == 200

    async_db.expire_all()
    assert ids.thread_id in await derive_effective_roll_excluded_thread_ids(
        async_db, user_id
    )

    restore_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/restore")
    assert restore_response.status_code == 200

    async_db.expire_all()
    assert ids.thread_id not in await derive_effective_roll_excluded_thread_ids(
        async_db, user_id
    )


@pytest.mark.asyncio
async def test_appending_issues_does_not_reactivate_an_excluded_series(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """CBL sync and provider adoption must not resurrect an excluded series.

    Appending issues recomputes the lifecycle from issue state, the same way a
    reading action does. The durable queue exclusion has to survive that path
    too, otherwise an out-of-band sync silently puts a deliberately removed
    series back into the active queue.
    """
    owner_id = default_user.id
    ids = await _seed_series(async_db, default_user)
    before = await _curated_state(async_db, ids)

    exclude_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert exclude_response.status_code == 200

    from app.services import issue as issue_service

    await issue_service.create_issues(
        async_db,
        thread_id=ids.thread_id,
        current_user_id=owner_id,
        issue_range="4",
        insert_after_issue_id=None,
    )
    await async_db.commit()

    async_db.expire_all()
    thread = await async_db.get(Thread, ids.thread_id)
    assert thread is not None
    assert thread.status == "excluded"
    assert thread.queue_position == 0

    # The newly adopted issue is tracked and the curated records still stand.
    issues = await _issue_rows(async_db, ids.thread_id)
    assert [issue.issue_number for issue in issues] == ["1", "2", "3", "4"]
    await _assert_thread_preserved(async_db, ids, before)
    assert await _excluded_thread_ids(auth_client) == [ids.thread_id]
    assert ids.thread_id not in await _queue_thread_ids(async_db, owner_id)


@pytest.mark.asyncio
async def test_exclusion_is_isolated_per_reader(
    client: AsyncClient,
    async_db: AsyncSession,
    owning_reader: User,
    other_reader: User,
) -> None:
    """One reader's queue exclusion never leaks into another reader's library."""
    _ = other_reader
    ids = await _seed_series(async_db, owning_reader)

    owner_headers = await _login(client, OWNER_USERNAME)
    other_headers = await _login(client, OTHER_USERNAME)

    assert (
        await client.post(f"/api/v1/threads/{ids.thread_id}/exclude", headers=owner_headers)
    ).status_code == 200

    other_library = await client.get(
        "/api/v1/threads/excluded/threads", headers=other_headers
    )
    assert other_library.status_code == 200
    assert ids.thread_id not in [row["id"] for row in other_library.json()["threads"]]

    assert (
        await client.post(f"/api/v1/threads/{ids.thread_id}/exclude", headers=other_headers)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/threads/{ids.thread_id}/restore", headers=other_headers)
    ).status_code == 404

    # The owner's exclusion is still intact after the other reader's attempts.
    owner_library = await client.get(
        "/api/v1/threads/excluded/threads", headers=owner_headers
    )
    assert owner_library.status_code == 200
    assert ids.thread_id in [row["id"] for row in owner_library.json()["threads"]]

    async_db.expire_all()
    thread = await async_db.get(Thread, ids.thread_id)
    assert thread is not None
    assert thread.status == "excluded"


@pytest.mark.asyncio
async def test_queue_removal_is_not_permanent_deletion(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Removal and deletion stay distinct: only deletion destroys reader data."""
    kept = await _seed_series(async_db, default_user, suffix="kept")
    deleted = await _seed_series(async_db, default_user, suffix="deleted")
    assert kept.thread_id != deleted.thread_id

    exclude_response = await auth_client.post(f"/api/v1/threads/{kept.thread_id}/exclude")
    assert exclude_response.status_code == 200

    async_db.expire_all()
    assert await async_db.get(Thread, kept.thread_id) is not None
    assert len(await _issue_rows(async_db, kept.thread_id)) == 3

    delete_response = await auth_client.delete(f"/api/v1/threads/{deleted.thread_id}")
    assert delete_response.status_code == 204

    async_db.expire_all()
    assert await async_db.get(Thread, deleted.thread_id) is None
    assert await _issue_rows(async_db, deleted.thread_id) == []


@pytest.mark.asyncio
async def test_queue_exclusion_transitions_validate_their_precondition(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Both transitions state their precondition instead of silently no-oping."""
    ids = await _seed_series(async_db, default_user)

    # A series that was never removed cannot be restored.
    assert (
        await auth_client.post(f"/api/v1/threads/{ids.thread_id}/restore")
    ).status_code == 400

    exclude_response = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert exclude_response.status_code == 200

    # Removing twice is idempotent rather than an error.
    repeat = await auth_client.post(f"/api/v1/threads/{ids.thread_id}/exclude")
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "excluded"

    assert (await auth_client.post("/api/v1/threads/999999/restore")).status_code == 404
    assert (await auth_client.post("/api/v1/threads/999999/exclude")).status_code == 404