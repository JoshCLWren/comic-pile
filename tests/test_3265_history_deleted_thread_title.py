"""Regression coverage for issue #3265: History timeline after thread deletion.

Events denormalize ``thread_title`` at write time so ``GET /sessions/{id}/details``
keeps naming a thread after its row is deleted. Events recorded before the column
existed still resolve their title from the live thread row.
"""

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread, User

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _event_by_id(details: dict, event_id: int) -> dict:
    """Return the timeline entry for ``event_id``."""
    matches = [item for item in details["events"] if item["id"] == event_id]
    assert matches, f"event {event_id} missing from timeline"
    return matches[0]


async def _new_thread(async_db: AsyncSession, user: User, title: str, position: int) -> Thread:
    """Create a standalone thread for the authenticated user."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=1,
        queue_position=position,
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _delete_thread(async_db: AsyncSession, thread_id: int) -> None:
    """Delete a thread row directly, bypassing ORM cascades.

    ``Thread.events`` uses ``lazy="raise"``, so the ORM cascade cannot be used
    here. Roll events reference the thread through ``selected_thread_id`` with no
    foreign key, so a bulk delete reproduces a real thread deletion.
    """
    await async_db.execute(delete(Thread).where(Thread.id == thread_id))
    await async_db.flush()


@pytest.mark.asyncio
async def test_denormalized_title_survives_thread_deletion(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """A roll event keeps its thread title after the thread row is deleted."""
    user: User = sample_data["user"]
    session: ReadingSession = sample_data["sessions"][0]

    thread = await _new_thread(async_db, user, "Saga", 90)
    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        thread_title=thread.title,
        die=6,
        result=4,
        selection_method="random",
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.flush()

    await _delete_thread(async_db, thread.id)

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200

    entry = _event_by_id(response.json(), event.id)
    assert entry["thread_title"] == "Saga"


@pytest.mark.asyncio
async def test_legacy_event_falls_back_to_live_thread_title(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Events written before the column existed still resolve the live title."""
    session: ReadingSession = sample_data["sessions"][0]
    legacy_event: Event = sample_data["events"][0]
    assert legacy_event.thread_title is None

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200

    entry = _event_by_id(response.json(), legacy_event.id)
    assert entry["thread_title"] == "Superman"


@pytest.mark.asyncio
async def test_legacy_event_without_thread_reports_no_title(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """A legacy event for a deleted thread reports no title instead of failing."""
    user: User = sample_data["user"]
    session: ReadingSession = sample_data["sessions"][0]

    thread = await _new_thread(async_db, user, "Flash", 91)
    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=2,
        selection_method="random",
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.flush()

    await _delete_thread(async_db, thread.id)

    response = await auth_client.get(f"/api/v1/sessions/{session.id}/details")
    assert response.status_code == 200

    entry = _event_by_id(response.json(), event.id)
    assert entry["thread_title"] is None


def test_events_thread_title_column_has_a_migration() -> None:
    """The denormalized column must ship with a migration, or inserts fail."""
    migration_sources = [
        path.read_text() for path in sorted((REPOSITORY_ROOT / "alembic" / "versions").glob("*.py"))
    ]
    adds_thread_title = [
        source
        for source in migration_sources
        if re.search(r'add_column\(\s*"events"', source)
        and re.search(r'sa\.Column\(\s*"thread_title"', source)
    ]
    assert adds_thread_title, "no migration adds events.thread_title"


def test_session_details_resolves_legacy_titles_in_one_query() -> None:
    """The legacy fallback must stay batched instead of one query per event."""
    source = (REPOSITORY_ROOT / "app" / "api" / "session.py").read_text()
    tree = ast.parse(source)
    details = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_session_details"
    )
    thread_selects = [
        node
        for node in ast.walk(details)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select"
        and any(
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "Thread"
            for arg in node.args
            for child in ast.walk(arg)
        )
    ]

    assert len(thread_selects) == 1, "get_session_details must issue one batched thread title query"


def test_every_thread_referencing_event_captures_a_title() -> None:
    """Each event that names a thread must denormalize that thread's title."""
    offenders: list[str] = []
    for path in sorted((REPOSITORY_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Event"
            ):
                continue
            keywords = {keyword.arg for keyword in node.keywords if keyword.arg}
            thread_refs = {"thread_id", "selected_thread_id"} & keywords
            references_a_thread = any(
                keyword.arg in thread_refs
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is None
                for keyword in node.keywords
            )
            if not thread_refs or references_a_thread:
                continue
            if "thread_title" not in keywords:
                offenders.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}")

    assert offenders == [], "events missing a denormalized thread_title: " + ", ".join(offenders)


async def _reorder_events(async_db: AsyncSession) -> list[Event]:
    """Return every recorded reorder event."""
    result = await async_db.execute(select(Event).where(Event.type == "reorder"))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_reorder_event_captures_thread_title(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Reordering a thread records its title so History can still name it."""
    thread: Thread = sample_data["threads"][0]

    response = await auth_client.put(
        f"/api/v1/queue/threads/{thread.id}/position/", json={"new_position": 3}
    )
    assert response.status_code == 200

    reorder_event = next(
        event for event in await _reorder_events(async_db) if event.thread_id == thread.id
    )
    assert reorder_event.thread_title == "Superman"
