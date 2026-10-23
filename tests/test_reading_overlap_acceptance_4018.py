"""Durable acceptance coverage for reader-owned overlap decisions (#4018).

The behavioral implementation landed in #4048. These regressions cover the two
remaining closure-critical behaviors directly:

- a refresh of the shared CBL source catalog must not reset a linked reader's
  approved decision, its version token, or its effective eligibility;
- changing an answer to the opposite direction for the same volume pair must
  replace the earlier choice instead of storing both contradictory decisions.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import CBLBook, CBLList
from app.cbl_sync import sync_cbl_lists
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.custom_cbl_source_link import CustomCBLSourceLink
from app.models.issue import Issue
from app.services.custom_cbl_source_link_service import ensure_first_add_link
from tests.conftest import get_or_create_user_async
from tests.test_reading_overlap_decision_write_path import (
    CONTINUING_VOLUME,
    WAITING_VOLUME,
    _strict_list,
    _thread_blockers,
    _volume_thread,
)

#: Source path shared by both revisions of the synthetic CBL.
SOURCE_PATH = "DC/Overlap Acceptance.cbl"


def _cbl_list(*, content_hash: str, issue_number: str) -> CBLList:
    """Build one synthetic source revision carrying both overlap volumes.

    Args:
        content_hash: Content hash of this revision.
        issue_number: Issue number of the continuing series in this revision.

    Returns:
        Parsed CBL list for the shared source path.
    """
    return CBLList(
        source_path=SOURCE_PATH,
        content_hash=content_hash,
        name="Overlap Acceptance",
        declared_issue_count=2,
        books=(
            CBLBook(
                position=1,
                series="Mister Miracle",
                issue_number="1",
                volume_year=1989,
                publication_year=1989,
                comicvine_series_id="202",
                comicvine_issue_id="4000-2021",
            ),
            CBLBook(
                position=2,
                series="JLI",
                issue_number=issue_number,
                volume_year=1987,
                publication_year=1987,
                comicvine_series_id="101",
                comicvine_issue_id="4000-1011",
            ),
        ),
    )


async def _synced_source_list(
    db: AsyncSession, *, repository: str, revision_sha: str, content_hash: str, issue_number: str
) -> CBLSourceList:
    """Synchronize one synthetic shared source revision and return its list row.

    Args:
        db: Current transaction.
        repository: Stable source repository identity.
        revision_sha: Source revision being synchronized.
        content_hash: Content hash of the revision.
        issue_number: Continuing series issue number in this revision.

    Returns:
        The persisted shared source list row.
    """
    await sync_cbl_lists(
        db,
        repository=repository,
        revision_sha=revision_sha,
        parsed_lists=(
            _cbl_list(content_hash=content_hash, issue_number=issue_number),
        ),
    )
    await db.flush()
    return (
        await db.execute(
            select(CBLSourceList)
            .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
            .where(
                CBLSource.repository == repository,
                CBLSourceList.source_path == SOURCE_PATH,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_source_revision_refresh_preserves_linked_reader_decision(
    auth_client,
    async_db: AsyncSession,
) -> None:
    """A shared catalog refresh never resets a linked reader's approved choice."""
    user = await get_or_create_user_async(async_db)
    _waiting_thread, waiting_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _continuing_thread, continuing_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="JLI",
        queue_position=2,
        volume_external_id="101",
    )
    repository = f"test/overlap-acceptance-{uuid4().hex}"
    first_revision = "a" * 40
    first_content_hash = "a" * 64
    first_source_list = await _synced_source_list(
        async_db,
        repository=repository,
        revision_sha=first_revision,
        content_hash=first_content_hash,
        issue_number="1",
    )
    first_source_list_id = first_source_list.id
    await async_db.commit()

    list_id = await _strict_list(
        auth_client,
        [waiting_issue.id, continuing_issue.id],
        name="Overlap Acceptance",
    )
    async_db.add(
        CustomCBLSourceLink(
            user_id=user.id,
            cbl_source_list_id=first_source_list_id,
            custom_cbl_list_id=list_id,
            source_revision_sha=first_revision,
            source_content_hash=first_content_hash,
        )
    )
    await async_db.commit()
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    before = saved.json()
    assert len(before["decisions"]) == 1
    assert await _thread_blockers(async_db, user.id, continuing_issue.thread_id) == []

    second_revision = "b" * 40
    second_content_hash = "b" * 64
    refreshed = await _synced_source_list(
        async_db,
        repository=repository,
        revision_sha=second_revision,
        content_hash=second_content_hash,
        issue_number="2",
    )
    await async_db.commit()
    assert refreshed.id == first_source_list_id

    stored_source = (
        await async_db.execute(
            select(CBLSourceList).where(CBLSourceList.id == first_source_list_id)
        )
    ).scalar_one()
    assert stored_source.revision_sha == second_revision
    assert stored_source.content_hash == second_content_hash
    entries = list(
        (
            await async_db.execute(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == first_source_list_id)
                .order_by(CBLSourceEntry.position)
            )
        )
        .scalars()
        .all()
    )
    assert [entry.issue_number for entry in entries] == ["1", "2"]

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["decisions"] == before["decisions"]
    assert reloaded.json()["updated_at"] == before["updated_at"]

    continuing = await async_db.get(Issue, continuing_issue.id)
    waiting = await async_db.get(Issue, waiting_issue.id)
    assert continuing is not None and waiting is not None
    assert continuing.status == waiting.status == "unread"
    assert await _thread_blockers(async_db, user.id, continuing.thread_id) == []
    assert await _thread_blockers(async_db, user.id, waiting.thread_id) == []

    repeated = await ensure_first_add_link(
        async_db, user_id=user.id, cbl_source_list_id=first_source_list_id
    )
    await async_db.commit()
    assert repeated.owned_list.id == list_id
    link = (
        await async_db.execute(
            select(CustomCBLSourceLink).where(CustomCBLSourceLink.custom_cbl_list_id == list_id)
        )
    ).scalar_one()
    assert link.source_revision_sha == first_revision
    assert link.source_content_hash == first_content_hash

    after_repeat = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert after_repeat.status_code == 200, after_repeat.text
    assert after_repeat.json()["decisions"] == before["decisions"]
    assert after_repeat.json()["updated_at"] == before["updated_at"]


@pytest.mark.asyncio
async def test_opposite_choice_replaces_the_earlier_decision(
    auth_client,
    async_db: AsyncSession,
) -> None:
    """Changing an answer leaves one decision and flips effective eligibility."""
    user = await get_or_create_user_async(async_db)
    _waiting_thread, waiting_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _continuing_thread, continuing_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="JLI",
        queue_position=2,
        volume_external_id="101",
    )
    await async_db.commit()
    list_id = await _strict_list(auth_client, [waiting_issue.id, continuing_issue.id])
    url = f"/api/v1/custom-cbls/{list_id}/overlap-decisions"

    first = await auth_client.put(
        url,
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert first.status_code == 200, first.text
    first_token = first.json()["updated_at"]
    assert await _thread_blockers(async_db, user.id, continuing_issue.thread_id) == []

    second = await auth_client.put(
        url,
        json={
            "continuing_volume_id": WAITING_VOLUME,
            "waiting_volume_id": CONTINUING_VOLUME,
        },
    )
    assert second.status_code == 200, second.text
    assert [
        (row["continuing_volume_id"], row["waiting_volume_id"])
        for row in second.json()["decisions"]
    ] == [(WAITING_VOLUME, CONTINUING_VOLUME)]
    assert second.json()["updated_at"] > first_token

    assert await _thread_blockers(async_db, user.id, continuing_issue.thread_id)
    assert await _thread_blockers(async_db, user.id, waiting_issue.thread_id) == []

    await async_db.commit()
    reloaded = await auth_client.get(url)
    assert reloaded.status_code == 200, reloaded.text
    assert [
        (row["continuing_volume_id"], row["waiting_volume_id"])
        for row in reloaded.json()["decisions"]
    ] == [(WAITING_VOLUME, CONTINUING_VOLUME)]
    assert reloaded.json()["updated_at"] == second.json()["updated_at"]
