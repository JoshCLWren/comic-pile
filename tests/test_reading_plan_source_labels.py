"""Reading Plan source labels resolve names without leaking foreign lists (#3514)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.reading_plan_source_labels import load_reading_plan_source_names
from tests.conftest import get_or_create_user_async


async def _make_issue(
    async_db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_number: str,
) -> Issue:
    """Create one owned unread issue for the source-label fixture."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=1,
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()
    thread.next_unread_issue_id = issue.id
    await async_db.flush()
    return issue


def _node(occurrence_id: str, issue_id: int, position: int) -> dict[str, object]:
    """Build one issue plan node."""
    return {
        "id": occurrence_id,
        "node_type": "issue",
        "ref_id": issue_id,
        "lane_id": "main",
        "position": position,
    }


async def _create_plan(
    auth_client: AsyncClient, name: str, nodes: list[dict[str, object]]
) -> int:
    """Create a plan through the public API and return its id."""
    response = await auth_client.post(
        "/api/v1/continuity-plans/",
        json={
            "name": name,
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": nodes,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


@pytest.mark.asyncio
async def test_plan_list_and_reader_resolve_owned_source_names_without_writing(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Index and membership labels use current owned names, never another reader's."""
    reader = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="other_source_reader")
    owned = CustomCBLList(user_id=reader.id, name="Mignolaverse")
    foreign = CustomCBLList(user_id=other.id, name="Private foreign source")
    async_db.add_all([owned, foreign])
    await async_db.flush()
    owned_ref = f"custom-cbl:{owned.id}"
    foreign_ref = f"custom-cbl:{foreign.id}"
    issue = await _make_issue(
        async_db,
        user_id=reader.id,
        title="Hellboy",
        issue_number="1",
    )
    await async_db.commit()
    plan_id = await _create_plan(
        auth_client,
        "Reading project",
        [
            {
                **_node("hellboy", issue.id, 0),
                "source_paths": [owned_ref, foreign_ref],
            }
        ],
    )
    before_count = await async_db.scalar(select(func.count()).select_from(CustomCBLList))
    before_revision = owned.updated_at
    listed = await auth_client.get("/api/v1/continuity-plans/")
    assert listed.status_code == 200, listed.text
    item = next(row for row in listed.json() if row["id"] == plan_id)
    assert item["source_names"] == {owned_ref: "Mignolaverse"}
    assert set(item["source_paths"]) == {owned_ref, foreign_ref}
    membership = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/membership")
    assert membership.status_code == 200, membership.text
    membership_sources = {row["raw_source_path"]: row for row in membership.json()["sources"]}
    assert membership_sources[owned_ref]["display_name"] == "Mignolaverse"
    assert membership_sources[foreign_ref]["display_name"] is None
    assert "Private foreign source" not in membership.text
    assert await async_db.scalar(select(func.count()).select_from(CustomCBLList)) == before_count
    await async_db.refresh(owned)
    assert owned.updated_at == before_revision
    await async_db.refresh(issue)
    assert issue.status == "unread"

    owned.name = "My revised Mignolaverse"
    await async_db.commit()
    refreshed = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/membership")
    assert refreshed.status_code == 200, refreshed.text
    assert (
        next(row for row in refreshed.json()["sources"] if row["raw_source_path"] == owned_ref)[
            "display_name"
        ]
        == owned.name
    )


@pytest.mark.asyncio
async def test_source_label_lookup_ignores_missing_malformed_and_overflow_ids(
    async_db: AsyncSession,
) -> None:
    """Unusable source references cannot cause unbounded integer bindings."""
    reader = await get_or_create_user_async(async_db)
    labels = await load_reading_plan_source_names(
        async_db,
        user_id=reader.id,
        source_paths=[
            "custom-cbl:0",
            "custom-cbl:-1",
            "custom-cbl:missing",
            "custom-cbl:123456789",
            "custom-cbl:2147483648",
            "custom-cbl:" + "9" * 100,
            "Marvel/Alpha Flight.cbl",
        ],
    )
    assert labels == {}
