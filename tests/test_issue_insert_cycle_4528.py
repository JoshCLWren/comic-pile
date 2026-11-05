"""The B.P.R.D. numeric insertion must not corrupt an authoritative strict CBL."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from tests.conftest import get_or_create_user_async


async def test_adding_earlier_numbered_issues_rejects_julix_cycle_atomically(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Numeric reseating cannot reverse existing strict placements and persist a cycle."""
    reader = await get_or_create_user_async(async_db)
    thread = Thread(
        user_id=reader.id,
        title="B.P.R.D.: Hell on Earth",
        format="Comic",
        status="active",
        queue_position=1,
        issues_remaining=4,
        total_issues=4,
    )
    async_db.add(thread)
    await async_db.flush()

    # Before insertion, the user's deliberately curated series position agrees
    # with the strict list, despite its nonnumeric #140-141 before #130-131.
    saved_numbers = ("140", "141", "130", "131")
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status="unread",
        )
        for position, number in enumerate(saved_numbers, start=1)
    ]
    async_db.add_all(issues)
    custom_list = CustomCBLList(user_id=reader.id, name="Mignolaverse", mode="strict")
    async_db.add(custom_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(
                list_id=custom_list.id,
                issue_id=issue.id,
                position=position,
            )
            for position, issue in enumerate(issues, start=1)
        ]
    )
    await async_db.commit()

    # The previous natural-order writer would have silently changed all four
    # existing Issue positions to #130, #131, #140, #141 and committed a cycle.
    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={"issue_range": "101-102"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "reading_list_cycle"
    assert any("strict order" in edge["origin"] for edge in detail["path"])
    assert any("series order" in edge["origin"] for edge in detail["path"])

    persisted = (
        await async_db.scalars(
            select(Issue)
            .where(Issue.thread_id == thread.id)
            .order_by(Issue.position)
        )
    ).all()
    assert [issue.issue_number for issue in persisted] == list(saved_numbers)
    assert [issue.position for issue in persisted] == [1, 2, 3, 4]
    assert len(persisted) == 4
    saved_entries = (
        await async_db.scalars(
            select(CustomCBLEntry)
            .where(CustomCBLEntry.list_id == custom_list.id)
            .order_by(CustomCBLEntry.position)
        )
    ).all()
    assert [entry.issue_id for entry in saved_entries] == [issue.id for issue in issues]
