"""Advisory possible-existing-volume checks stay scoped and non-destructive (#3612).

The endpoint behind the Add Series and Edit/Rename advisories must identify
canonical ComicVine identity as a strong match, keep title resemblance clearly
uncertain, never leak another reader's library, and never write, merge, or
delete anything.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping

CHECK_URL = "/api/v1/threads/check-duplicates"


async def _create_thread(
    db: AsyncSession,
    user_id: int,
    title: str,
    *,
    format_value: str = "Comic",
    queue_position: int = 1,
    status: str = "active",
    issues_remaining: int = 3,
    total_issues: int | None = None,
) -> Thread:
    """Create one reader-owned series for a duplicate check.

    Args:
        db: Current transaction.
        user_id: Owner of the series.
        title: Display title.
        format_value: Stored format.
        queue_position: Queue position (unique ordering is not enforced).
        status: Series status.
        issues_remaining: Counter-based remaining issues.
        total_issues: Tracked issue total, or None for counter-based series.

    Returns:
        The flushed thread with a database-assigned ID.
    """
    thread = Thread(
        user_id=user_id,
        title=title,
        format=format_value,
        issues_remaining=issues_remaining,
        queue_position=queue_position,
        status=status,
        total_issues=total_issues,
    )
    db.add(thread)
    await db.flush()
    return thread


async def _confirm_comicvine_series(
    db: AsyncSession,
    thread: Thread,
    volume_id: int,
    *,
    start_year: int | str | None = None,
) -> ExternalIdentity:
    """Attach a confirmed ComicVine series identity to one thread.

    Args:
        db: Current transaction.
        thread: Reader-owned series that tracks the volume.
        volume_id: ComicVine volume identity.
        start_year: Optional stored publication start year.

    Returns:
        The flushed external identity.
    """
    metadata: dict[str, object] = {}
    if start_year is not None:
        metadata["start_year"] = start_year
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=str(volume_id),
        metadata_json=metadata,
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await db.flush()
    return identity


@pytest.mark.asyncio
async def test_same_comicvine_volume_links_the_owned_thread(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A confirmed volume is a strong match that names the reader's real thread."""
    existing = await _create_thread(
        async_db,
        default_user.id,
        "Spider-Man (2018)",
        issues_remaining=2,
    )
    await _confirm_comicvine_series(async_db, existing, 12345, start_year=2018)
    threads_before = await async_db.scalar(select(func.count(Thread.id)))

    response = await auth_client.post(
        CHECK_URL,
        json={
            "title": "Amazing Spider-Man",
            "format": "Comic",
            "comicvine_volume_id": 12345,
        },
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert [match["thread_id"] for match in matches] == [existing.id]
    match = matches[0]
    assert match["match_type"] == "same_comicvine_volume"
    assert match["title"] == "Spider-Man (2018)"
    assert match["comicvine_volume_id"] == 12345
    assert match["start_year"] == 2018
    assert match["format"] == "Comic"
    assert match["status"] == "active"
    assert match["issues_remaining"] == 2
    # Viewing the warning is read-only.
    assert await async_db.scalar(select(func.count(Thread.id))) == threads_before
    refreshed = await async_db.get(Thread, existing.id)
    assert refreshed is not None
    assert refreshed.title == "Spider-Man (2018)"


@pytest.mark.asyncio
async def test_rename_excludes_the_thread_being_edited(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A rename never reports the series being renamed as its own duplicate."""
    editing = await _create_thread(async_db, default_user.id, "Saga")
    await _confirm_comicvine_series(async_db, editing, 4242, start_year=2012)

    response = await auth_client.post(
        CHECK_URL,
        json={
            "title": "Saga",
            "format": "Comic",
            "comicvine_volume_id": 4242,
            "exclude_thread_id": editing.id,
        },
    )

    assert response.status_code == 200
    assert response.json()["matches"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing_title", "proposed_title"),
    [
        ("Spider-Man", "Amazing Spider-Man"),
        ("Amazing Spider-Man", "Spider-Man"),
    ],
)
async def test_title_resemblance_is_an_uncertain_suggestion(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    existing_title: str,
    proposed_title: str,
) -> None:
    """A shared title warns in both directions without asserting identity."""
    existing = await _create_thread(async_db, default_user.id, existing_title)

    response = await auth_client.post(
        CHECK_URL,
        json={"title": proposed_title, "format": "Comic"},
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert [match["thread_id"] for match in matches] == [existing.id]
    assert matches[0]["match_type"] == "similar_title"
    assert matches[0]["comicvine_volume_id"] is None
    assert matches[0]["start_year"] is None


@pytest.mark.asyncio
async def test_identical_titles_remain_creatable_as_separate_volumes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The advisory never blocks a legitimate same-named series."""
    existing = await _create_thread(async_db, default_user.id, "Uncanny X-Men")

    warning = await auth_client.post(
        CHECK_URL,
        json={"title": "Uncanny X-Men", "format": "Comic"},
    )
    assert warning.status_code == 200
    assert [match["thread_id"] for match in warning.json()["matches"]] == [existing.id]

    created = await auth_client.post(
        "/api/v1/threads/",
        json={"title": "Uncanny X-Men", "format": "Comic", "issues_remaining": 5},
    )
    assert created.status_code == 201
    # The issue count differs from the existing series so this exercises the
    # legitimate same-title create path; identical payloads inside the 5s
    # repeated-request window are #3466's separate idempotency contract.
    assert created.json()["id"] != existing.id
    assert created.json()["title"] == "Uncanny X-Men"


@pytest.mark.asyncio
async def test_distinct_volumes_of_one_title_report_their_own_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Different ComicVine volumes stay distinct and a rename is still allowed."""
    first = await _create_thread(async_db, default_user.id, "Spider-Man")
    second = await _create_thread(
        async_db,
        default_user.id,
        "Amazing Spider-Man",
        queue_position=2,
    )
    await _confirm_comicvine_series(async_db, first, 111, start_year="1990")
    await _confirm_comicvine_series(async_db, second, 222, start_year=2018)

    checked = await auth_client.post(
        CHECK_URL,
        json={"title": "Spider-Man", "format": "Comic", "comicvine_volume_id": 111},
    )

    assert checked.status_code == 200
    by_thread = {match["thread_id"]: match for match in checked.json()["matches"]}
    assert by_thread[first.id]["match_type"] == "same_comicvine_volume"
    assert by_thread[first.id]["start_year"] == 1990
    assert by_thread[second.id]["match_type"] == "similar_title"
    # The second run's own volume is context, never the proposed identity.
    assert by_thread[second.id]["comicvine_volume_id"] == 222
    assert by_thread[second.id]["start_year"] == 2018

    renamed = await auth_client.put(
        f"/api/v1/threads/{second.id}",
        json={"title": "Spider-Man"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["id"] == second.id
    assert renamed.json()["title"] == "Spider-Man"


@pytest.mark.asyncio
async def test_other_readers_series_never_appear(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Warnings are scoped to the authenticated reader's own library."""
    foreign = User(username="foreign_duplicate_reader")
    async_db.add(foreign)
    await async_db.flush()
    foreign_thread = await _create_thread(async_db, foreign.id, "Spider-Man")
    await _confirm_comicvine_series(async_db, foreign_thread, 777, start_year=1990)

    by_title = await auth_client.post(
        CHECK_URL,
        json={"title": "Amazing Spider-Man", "format": "Comic"},
    )
    assert by_title.status_code == 200
    assert by_title.json()["matches"] == []

    by_volume = await auth_client.post(
        CHECK_URL,
        json={"title": "Spider-Man", "format": "Comic", "comicvine_volume_id": 777},
    )
    assert by_volume.status_code == 200
    assert by_volume.json()["matches"] == []


@pytest.mark.asyncio
async def test_a_different_format_is_context_not_a_block(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A same-titled edition in another format is shown with its format."""
    existing = await _create_thread(
        async_db,
        default_user.id,
        "Spider-Man",
        format_value="Manga",
    )

    response = await auth_client.post(
        CHECK_URL,
        json={"title": "Spider-Man", "format": "Comic"},
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert [match["thread_id"] for match in matches] == [existing.id]
    assert matches[0]["format"] == "Manga"
    assert matches[0]["match_type"] == "similar_title"

    created = await auth_client.post(
        "/api/v1/threads/",
        json={"title": "Spider-Man", "format": "Comic", "issues_remaining": 1},
    )
    assert created.status_code == 201
    assert created.json()["id"] != existing.id


@pytest.mark.asyncio
async def test_blank_title_returns_no_matches(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An empty candidate is an idle state, not a library-wide suggestion list."""
    await _create_thread(async_db, default_user.id, "Saga")

    response = await auth_client.post(CHECK_URL, json={"title": "   ", "format": "Comic"})

    assert response.status_code == 200
    assert response.json()["matches"] == []


@pytest.mark.asyncio
async def test_invalid_volume_identity_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A non-positive volume or exclusion identity is a client error."""
    await _create_thread(async_db, default_user.id, "Saga")

    bad_volume = await auth_client.post(
        CHECK_URL,
        json={"title": "Saga", "format": "Comic", "comicvine_volume_id": 0},
    )
    assert bad_volume.status_code == 422

    bad_exclusion = await auth_client.post(
        CHECK_URL,
        json={"title": "Saga", "format": "Comic", "exclude_thread_id": -1},
    )
    assert bad_exclusion.status_code == 422
