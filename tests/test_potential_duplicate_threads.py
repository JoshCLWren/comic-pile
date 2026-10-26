"""Advisory duplicate matching remains scoped, bidirectional and non-destructive."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Thread, User
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing", "proposed"),
    [("Spider-Man", "Amazing Spider-Man"), ("Amazing Spider-Man", "Spider-Man")],
)
async def test_title_matches_both_directions(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    existing: str,
    proposed: str,
) -> None:
    """Creating or renaming a longer or shorter title warns about the existing run."""
    thread = Thread(
        user_id=default_user.id,
        title=existing,
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()
    response = await auth_client.post(
        "/api/v1/threads/check-duplicates", json={"title": proposed, "format": "Comic"}
    )
    assert response.status_code == 200
    assert [row["thread_id"] for row in response.json()["matches"]] == [thread.id]
    assert response.json()["matches"][0]["match_type"] == "weak"
    assert thread.title == existing
    excluded = await auth_client.post(
        "/api/v1/threads/check-duplicates",
        json={"title": proposed, "format": "Comic", "exclude_thread_id": thread.id},
    )
    assert excluded.json()["matches"] == []


@pytest.mark.asyncio
async def test_duplicate_warning_does_not_expose_foreign_or_other_formats(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Warnings use owned threads and the requested format only."""
    foreign = User(username="foreign_duplicate_reader")
    async_db.add(foreign)
    await async_db.flush()
    async_db.add_all(
        [
            Thread(
                user_id=foreign.id,
                title="Spider-Man",
                format="Comic",
                issues_remaining=1,
                queue_position=1,
                status="active",
            ),
            Thread(
                user_id=default_user.id,
                title="Spider-Man",
                format="Manga",
                issues_remaining=1,
                queue_position=1,
                status="active",
            ),
        ]
    )
    await async_db.flush()
    response = await auth_client.post(
        "/api/v1/threads/check-duplicates", json={"title": "Amazing Spider-Man", "format": "Comic"}
    )
    assert response.status_code == 200
    assert response.json()["matches"] == []


@pytest.mark.asyncio
async def test_comicvine_volume_match_is_strong_and_links_the_owned_thread(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A confirmed ComicVine series identity reports its actual thread as strong.

    The Add Series flow passes the candidate volume id, so the reader sees the
    real ``thread_id`` of the series that already owns that canonical volume.
    """
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
    )
    async_db.add(identity)
    await async_db.flush()
    thread = Thread(
        user_id=default_user.id,
        title="Spider-Man (2018)",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await async_db.flush()

    response = await auth_client.post(
        "/api/v1/threads/check-duplicates",
        json={
            "title": "Amazing Spider-Man",
            "format": "Comic",
            "comicvine_volume_id": 12345,
        },
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert [row["thread_id"] for row in matches] == [thread.id]
    assert matches[0]["match_type"] == "strong"
    assert matches[0]["comicvine_volume_id"] == 12345
    assert matches[0]["title"] == "Spider-Man (2018)"

    excluded = await auth_client.post(
        "/api/v1/threads/check-duplicates",
        json={
            "title": "Amazing Spider-Man",
            "format": "Comic",
            "comicvine_volume_id": 12345,
            "exclude_thread_id": thread.id,
        },
    )
    assert excluded.status_code == 200
    assert excluded.json()["matches"] == []


@pytest.mark.asyncio
async def test_duplicate_warnings_never_block_distinct_volumes(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Identical titles and formats remain creatable; the warning is advisory."""
    existing = Thread(
        user_id=default_user.id,
        title="Uncanny X-Men",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
    )
    async_db.add(existing)
    await async_db.flush()

    warning = await auth_client.post(
        "/api/v1/threads/check-duplicates",
        json={"title": "Uncanny X-Men", "format": "Comic"},
    )
    assert warning.status_code == 200
    assert [row["thread_id"] for row in warning.json()["matches"]] == [existing.id]

    created = await auth_client.post(
        "/api/v1/threads/",
        json={"title": "Uncanny X-Men", "format": "Comic", "issues_remaining": 3},
    )
    assert created.status_code == 201
    assert created.json()["id"] != existing.id
    assert created.json()["title"] == "Uncanny X-Men"
