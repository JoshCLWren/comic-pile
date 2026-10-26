"""Advisory duplicate matching remains scoped, bidirectional and non-destructive."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Thread, User


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
