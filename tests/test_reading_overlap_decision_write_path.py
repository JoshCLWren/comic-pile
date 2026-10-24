"""Reader-facing overlap decision write path, versioning, and durable schema.

The reader approves one overlap choice per Reading List and exact Comic Vine
volume pair. The choice is durable, owner-scoped, versioned, and survives a
later membership rewrite. The migration that introduces the storage is
executed here so a deployed database can never miss the column or the table.
"""

import ast
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import Connection, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import CBLBook, CBLList
from app.cbl_sync import sync_cbl_lists
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.custom_cbl import CustomCBLList
from app.models.custom_cbl_source_link import CustomCBLSourceLink
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.custom_cbl_source_link_service import ensure_first_add_link
from tests.conftest import get_or_create_user_async

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic/versions/r40180000001_add_custom_cbl_overlap_decisions.py"
)

#: The overlap decision service. Every statement it runs belongs to a
#: repository, so a service that builds its own writes is a layering defect.
OVERLAP_DECISION_SERVICE_PATH = (
    Path(__file__).parents[1] / "app/services/reading_overlap_decisions.py"
)

#: Canonical keys of the two Comic Vine volumes used by the fixture.
CONTINUING_VOLUME = "comicvine:101"
WAITING_VOLUME = "comicvine:202"


async def _volume_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    volume_external_id: str,
) -> tuple[Thread, Issue]:
    """Create one owned Thread with exactly one confirmed Comic Vine volume.

    Args:
        db: Current transaction.
        user_id: Reader who owns the Thread.
        title: Thread title.
        queue_position: Stable queue position of the Thread.
        volume_external_id: Comic Vine series identifier of the Thread.

    Returns:
        The created Thread and its single unread Issue.
    """
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=queue_position,
        status="active",
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    identity = (
        await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
                ExternalIdentity.external_id == volume_external_id,
            )
        )
    ).scalar_one_or_none()
    if identity is None:
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id=volume_external_id,
        )
        db.add(identity)
        await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="test",
        )
    )
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    return thread, issue


async def _strict_list(
    auth_client: AsyncClient, issue_ids: list[int], name: str = "Overlap"
) -> int:
    """Create one owned strict Reading List with the given membership.

    Args:
        auth_client: Authenticated API client.
        issue_ids: Ordered membership of the new list.
        name: Name of the new list.

    Returns:
        The identifier of the created Reading List.
    """
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={"name": name, "issue_ids": issue_ids, "mode": "strict"},
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"])


async def _list_row(db: AsyncSession, list_id: int) -> CustomCBLList:
    """Read one Reading List row straight from the database.

    Args:
        db: Current transaction.
        list_id: Reading List identifier.

    Returns:
        The stored Reading List row with its persisted timestamps.
    """
    return (
        await db.execute(
            select(CustomCBLList)
            .where(CustomCBLList.id == list_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _thread_blockers(
    db: AsyncSession, user_id: int, thread_id: int
) -> list[object]:
    """Return one Thread's canonical blockers from the shadow eligibility report.

    Args:
        db: Current transaction.
        user_id: Reader whose shadow inputs are evaluated.
        thread_id: Thread whose blockers are reported.

    Returns:
        The Thread's blocker rows; an empty list means the Thread is eligible.
    """
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_shadow_service import compare_reading_eligibility

    result = compare_reading_eligibility(await load_shadow_inputs(db, user_id))
    rows = result["threads"]
    assert isinstance(rows, list)
    for row in rows:
        if row["thread_id"] == thread_id:
            blockers = row["blockers"]
            assert isinstance(blockers, list)
            return blockers
    raise AssertionError(f"Thread {thread_id} is missing from the shadow report")


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_prefix", ["", "4050-"])
async def test_reader_saves_and_reloads_one_overlap_decision(
    stored_prefix: str,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A saved choice is durable, owner-scoped, and visible to the reader."""
    user = await get_or_create_user_async(async_db)
    _waiting_thread, waiting_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id=f"{stored_prefix}202",
    )
    _continuing_thread, continuing_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="JLI",
        queue_position=2,
        volume_external_id=f"{stored_prefix}101",
    )
    await async_db.commit()
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )

    empty = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert empty.status_code == 200, empty.text
    assert empty.json()["decisions"] == []
    assert {row["volume_id"] for row in empty.json()["candidate_volumes"]} == {
        CONTINUING_VOLUME,
        WAITING_VOLUME,
    }

    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert len(body["decisions"]) == 1
    decision = body["decisions"][0]
    assert decision["continuing_volume_id"] == CONTINUING_VOLUME
    assert decision["waiting_volume_id"] == WAITING_VOLUME
    assert decision["id"] > 0

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["decisions"] == body["decisions"]
    assert reloaded.json()["updated_at"] == body["updated_at"]


@pytest.mark.asyncio
async def test_saved_decision_changes_the_effective_reading_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The approved pair relaxes only the strict-order edge it names."""
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_shadow_service import compare_reading_eligibility

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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )

    before = await load_shadow_inputs(async_db, user.id)
    assert before.lists[0].overlap_decisions == ()
    before_result = compare_reading_eligibility(before)
    before_rows = before_result["threads"]
    assert isinstance(before_rows, list)
    before_blocked = [
        row["blockers"]
        for row in before_rows
        if row["thread_id"] == _continuing_thread.id
    ]
    assert before_blocked[0]

    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text

    after = await load_shadow_inputs(async_db, user.id)
    assert len(after.lists[0].overlap_decisions) == 1
    assert after.lists[0].overlap_decisions[0].continuing_volume_id == CONTINUING_VOLUME
    after_result = compare_reading_eligibility(after)
    after_rows = after_result["threads"]
    assert isinstance(after_rows, list)
    after_blocked = [
        row["blockers"]
        for row in after_rows
        if row["thread_id"] == _continuing_thread.id
    ]
    assert not after_blocked[0]


@pytest.mark.asyncio
async def test_membership_upsert_preserves_the_saved_decision(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A later membership rewrite never resets an approved choice."""
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    token = saved.json()["updated_at"]

    updated = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}",
        json={
            "name": "Overlap",
            "issue_ids": [waiting_issue.id, continuing_issue.id],
            "mode": "strict",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated_at"] != token

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert reloaded.status_code == 200, reloaded.text
    assert len(reloaded.json()["decisions"]) == 1
    assert reloaded.json()["updated_at"] == token


@pytest.mark.asyncio
async def test_stale_version_token_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A write based on an outdated token never overwrites a newer approval."""
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    first = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert first.status_code == 200, first.text
    stale_token = first.json()["updated_at"]

    second = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
            "expected_updated_at": stale_token,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["updated_at"] != stale_token

    stale = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
            "expected_updated_at": stale_token,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "reading_overlap_version_conflict"


@pytest.mark.asyncio
async def test_deleting_a_decision_advances_the_version_token(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Removing an approval clears it and publishes a new version token."""
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    decision_id = saved.json()["decisions"][0]["id"]

    removed = await auth_client.delete(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions/{decision_id}"
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["decisions"] == []
    assert removed.json()["updated_at"] != saved.json()["updated_at"]

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert reloaded.json()["decisions"] == []


@pytest.mark.asyncio
async def test_saving_a_decision_leaves_the_list_revision_untouched(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A decision change advances only the decision token, never the list revision.

    The list's own ``updated_at`` is its membership revision. A reader who only
    approves an overlap choice has not edited the list, so the revision must not
    move: the newest-first picker orders by that revision.
    """
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    before = await _list_row(async_db, list_id)
    before_revision = before.updated_at
    before_token = before.overlap_decisions_updated_at

    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text

    after = await _list_row(async_db, list_id)
    assert after.updated_at == before_revision, (
        "an approved overlap choice must not rewrite the list's own revision"
    )
    assert after.overlap_decisions_updated_at > before_token
    assert after.overlap_decisions_updated_at == datetime.fromisoformat(
        saved.json()["updated_at"]
    )


@pytest.mark.asyncio
async def test_deleting_a_decision_leaves_the_list_revision_untouched(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Removing an approval advances only the decision token, never the revision."""
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    before = await _list_row(async_db, list_id)
    before_revision = before.updated_at
    before_token = before.overlap_decisions_updated_at

    removed = await auth_client.delete(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions/{saved.json()['decisions'][0]['id']}"
    )
    assert removed.status_code == 200, removed.text

    after = await _list_row(async_db, list_id)
    assert after.updated_at == before_revision, (
        "removing an approved overlap choice must not rewrite the list's own revision"
    )
    assert after.overlap_decisions_updated_at > before_token


@pytest.mark.asyncio
async def test_a_decision_change_keeps_the_list_in_the_picker_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An approved choice never moves its Reading List in the newest-first picker."""
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
    older_list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id], name="Older"
    )
    newer_list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id], name="Newer"
    )

    before = await auth_client.get("/api/v1/custom-cbls")
    assert before.status_code == 200, before.text
    before_order = [row["id"] for row in before.json()]
    assert before_order.index(newer_list_id) < before_order.index(older_list_id)

    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{older_list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text

    after = await auth_client.get("/api/v1/custom-cbls")
    assert after.status_code == 200, after.text
    after_order = [row["id"] for row in after.json()]
    assert after_order == before_order, (
        "an approved overlap choice must not reorder the Reading List picker"
    )


def test_the_overlap_decision_service_delegates_its_writes_to_a_repository() -> None:
    """The overlap write path must not build or run its own statements.

    Repositories own all query construction and persistence for a model family.
    A service that builds ``update(CustomCBLList)`` itself puts the list write
    outside the repository boundary, so the token advance belongs to
    ``app/repositories/reading_overlap_decision_repository.py``.
    """
    tree = ast.parse(OVERLAP_DECISION_SERVICE_PATH.read_text(encoding="utf-8"))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                if module_name.startswith("sqlalchemy") and alias.name in {
                    "delete",
                    "insert",
                    "select",
                    "update",
                }:
                    findings.append(
                        f"{OVERLAP_DECISION_SERVICE_PATH}:{node.lineno}: imports "
                        f"{module_name}.{alias.name}"
                    )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in {"execute", "add", "add_all", "delete", "merge"}:
                    findings.append(
                        f"{OVERLAP_DECISION_SERVICE_PATH}:{node.lineno}: calls "
                        f"{node.func.attr}()"
                    )
            elif isinstance(node.func, ast.Name) and node.func.id in {
                "delete",
                "insert",
                "select",
                "update",
            }:
                findings.append(
                    f"{OVERLAP_DECISION_SERVICE_PATH}:{node.lineno}: calls {node.func.id}()"
                )
    assert not findings, (
        "the overlap decision service must delegate every statement to a repository:\n"
        + "\n".join(findings)
    )


@pytest.mark.asyncio
async def test_unusable_overlap_choices_are_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A self-overlap or an unknown volume never reaches storage."""
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    url = f"/api/v1/custom-cbls/{list_id}/overlap-decisions"

    same = await auth_client.put(
        url,
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": CONTINUING_VOLUME,
        },
    )
    assert same.status_code == 422, same.text

    unknown = await auth_client.put(
        url,
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": "comicvine:999",
        },
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["detail"]["code"] == "reading_overlap_unknown_volume"

    other_provider = await auth_client.put(
        url,
        json={
            "continuing_volume_id": "marvel:101",
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert other_provider.status_code == 422, other_provider.text

    assert (await auth_client.get(url)).json()["decisions"] == []


@pytest.mark.asyncio
async def test_one_reader_never_sees_or_changes_another_readers_choice(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Owner scope holds at the API boundary, not only in the database."""
    from app.auth import create_access_token
    from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
    from httpx import ASGITransport

    from app.main import app

    owner = await get_or_create_user_async(async_db)
    _waiting_thread, waiting_issue = await _volume_thread(
        async_db,
        user_id=owner.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _continuing_thread, continuing_issue = await _volume_thread(
        async_db,
        user_id=owner.id,
        title="JLI",
        queue_position=2,
        volume_external_id="101",
    )
    await async_db.commit()
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text

    other = await get_or_create_user_async(async_db, username="other_reader")
    _other_waiting, other_waiting_issue = await _volume_thread(
        async_db,
        user_id=other.id,
        title="Other Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _other_continuing, other_continuing_issue = await _volume_thread(
        async_db,
        user_id=other.id,
        title="Other JLI",
        queue_position=2,
        volume_external_id="101",
    )
    await async_db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as other_client:
        csrf_token = generate_csrf_token()
        other_client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
        other_client.headers.update({CSRF_HEADER_NAME: csrf_token})
        token = create_access_token(data={"sub": other.username, "jti": "other"})
        other_client.headers.update({"Authorization": f"Bearer {token}"})

        created = await other_client.post(
            "/api/v1/custom-cbls",
            json={
                "name": "Other overlap",
                "issue_ids": [other_waiting_issue.id, other_continuing_issue.id],
                "mode": "strict",
            },
        )
        assert created.status_code == 201, created.text
        other_list_id = int(created.json()["id"])

        other_set = await other_client.get(
            f"/api/v1/custom-cbls/{other_list_id}/overlap-decisions"
        )
        assert other_set.status_code == 200, other_set.text
        assert other_set.json()["decisions"] == []

        foreign = await other_client.put(
            f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
            json={
                "continuing_volume_id": CONTINUING_VOLUME,
                "waiting_volume_id": WAITING_VOLUME,
            },
        )
        assert foreign.status_code == 404, foreign.text

        foreign_read = await other_client.get(
            f"/api/v1/custom-cbls/{list_id}/overlap-decisions"
        )
        assert foreign_read.status_code == 404, foreign_read.text

    owner_set = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert len(owner_set.json()["decisions"]) == 1


@pytest.mark.asyncio
async def test_two_readers_sharing_sources_save_different_choices(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Readers sharing the same Comic Vine sources reach different eligible Issues.

    Both readers map their own Threads onto the same confirmed Comic Vine
    volumes. Each saves the opposite overlap choice, so the eligible Issue of
    one reader stays blocked for the other, and neither write disturbs the
    other reader's stored decision or eligibility.
    """
    from app.auth import create_access_token
    from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
    from app.main import app
    from httpx import ASGITransport

    first = await get_or_create_user_async(async_db)
    _first_waiting, first_waiting_issue = await _volume_thread(
        async_db,
        user_id=first.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _first_continuing, first_continuing_issue = await _volume_thread(
        async_db,
        user_id=first.id,
        title="JLI",
        queue_position=2,
        volume_external_id="101",
    )
    second = await get_or_create_user_async(async_db, username="sharing_reader")
    _second_waiting, second_waiting_issue = await _volume_thread(
        async_db,
        user_id=second.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _second_continuing, second_continuing_issue = await _volume_thread(
        async_db,
        user_id=second.id,
        title="JLI",
        queue_position=2,
        volume_external_id="101",
    )
    await async_db.commit()

    first_list_id = await _strict_list(
        auth_client, [first_waiting_issue.id, first_continuing_issue.id], name="First"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as second_client:
        csrf_token = generate_csrf_token()
        second_client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
        second_client.headers.update({CSRF_HEADER_NAME: csrf_token})
        second_token = create_access_token(data={"sub": second.username, "jti": "second"})
        second_client.headers.update({"Authorization": f"Bearer {second_token}"})
        created = await second_client.post(
            "/api/v1/custom-cbls",
            json={
                "name": "Second",
                "issue_ids": [second_waiting_issue.id, second_continuing_issue.id],
                "mode": "strict",
            },
        )
        assert created.status_code == 201, created.text
        second_list_id = int(created.json()["id"])

        first_saved = await auth_client.put(
            f"/api/v1/custom-cbls/{first_list_id}/overlap-decisions",
            json={
                "continuing_volume_id": CONTINUING_VOLUME,
                "waiting_volume_id": WAITING_VOLUME,
            },
        )
        assert first_saved.status_code == 200, first_saved.text
        second_saved = await second_client.put(
            f"/api/v1/custom-cbls/{second_list_id}/overlap-decisions",
            json={
                "continuing_volume_id": WAITING_VOLUME,
                "waiting_volume_id": CONTINUING_VOLUME,
            },
        )
        assert second_saved.status_code == 200, second_saved.text

        first_reloaded = await auth_client.get(
            f"/api/v1/custom-cbls/{first_list_id}/overlap-decisions"
        )
        assert first_reloaded.status_code == 200, first_reloaded.text
        assert [
            (row["continuing_volume_id"], row["waiting_volume_id"])
            for row in first_reloaded.json()["decisions"]
        ] == [(CONTINUING_VOLUME, WAITING_VOLUME)]
        second_reloaded = await second_client.get(
            f"/api/v1/custom-cbls/{second_list_id}/overlap-decisions"
        )
        assert second_reloaded.status_code == 200, second_reloaded.text
        assert [
            (row["continuing_volume_id"], row["waiting_volume_id"])
            for row in second_reloaded.json()["decisions"]
        ] == [(WAITING_VOLUME, CONTINUING_VOLUME)]

    first_continuing_blockers = await _thread_blockers(
        async_db, first.id, first_continuing_issue.thread_id
    )
    first_waiting_blockers = await _thread_blockers(
        async_db, first.id, first_waiting_issue.thread_id
    )
    second_continuing_blockers = await _thread_blockers(
        async_db, second.id, second_continuing_issue.thread_id
    )
    second_waiting_blockers = await _thread_blockers(
        async_db, second.id, second_waiting_issue.thread_id
    )
    assert first_continuing_blockers == [], (
        "the reader who approved the overlap must reach the continuing volume"
    )
    assert first_waiting_blockers == []
    assert second_continuing_blockers, (
        "the other reader's opposite choice must keep the same volume blocked"
    )
    assert second_waiting_blockers == []


@pytest.mark.asyncio
async def test_a_removal_that_would_create_a_cycle_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Cycle checks reject the write and leave the stored choice untouched.

    The saved overlap waives the strict-order edge between the two volumes, so
    a reverse prerequisite is legal while the choice exists. Removing the
    choice would restore the waived edge and close a cycle: the delete must be
    rejected with the decision and its version token intact.
    """
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    decision_id = saved.json()["decisions"][0]["id"]
    token = saved.json()["updated_at"]

    prerequisite = await auth_client.post(
        "/api/v1/prerequisites/",
        json={
            "source_issue_id": continuing_issue.id,
            "target_issue_id": waiting_issue.id,
        },
    )
    assert prerequisite.status_code == 201, prerequisite.text

    rejected = await auth_client.delete(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions/{decision_id}",
        params={"expected_updated_at": token},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["code"] == "reading_list_cycle"

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert reloaded.status_code == 200, reloaded.text
    assert [row["id"] for row in reloaded.json()["decisions"]] == [decision_id]
    assert reloaded.json()["updated_at"] == token

    removed_prerequisite = await auth_client.delete(
        f"/api/v1/prerequisites/{prerequisite.json()['id']}"
    )
    assert removed_prerequisite.status_code == 204, removed_prerequisite.text

    removed = await auth_client.delete(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions/{decision_id}"
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["decisions"] == []


@pytest.mark.asyncio
async def test_opposite_choice_replaces_the_earlier_decision(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Changing the answer stores exactly the reader's latest direction.

    Keeping both directions would waive both strict-order edges, so the
    evaluator would honor neither answer. The reverse save must replace the
    earlier choice and flip effective eligibility, and a reload must show only
    the latest direction.
    """
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
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
    assert second.json()["updated_at"] != first_token

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


@pytest.mark.asyncio
async def test_a_reversal_that_would_create_a_cycle_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A rejected reversal leaves the original choice and version untouched.

    The saved overlap waives the strict-order edge between the two volumes.
    Reversing the answer would restore that edge while an explicit prerequisite
    points the other way, closing a cycle. The replacement must be validated
    against that projected graph and rejected with the stored choice intact.
    """
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
    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id]
    )
    url = f"/api/v1/custom-cbls/{list_id}/overlap-decisions"
    saved = await auth_client.put(
        url,
        json={
            "continuing_volume_id": CONTINUING_VOLUME,
            "waiting_volume_id": WAITING_VOLUME,
        },
    )
    assert saved.status_code == 200, saved.text
    decision_id = saved.json()["decisions"][0]["id"]
    token = saved.json()["updated_at"]

    prerequisite = await auth_client.post(
        "/api/v1/prerequisites/",
        json={
            "source_issue_id": continuing_issue.id,
            "target_issue_id": waiting_issue.id,
        },
    )
    assert prerequisite.status_code == 201, prerequisite.text

    rejected = await auth_client.put(
        url,
        json={
            "continuing_volume_id": WAITING_VOLUME,
            "waiting_volume_id": CONTINUING_VOLUME,
            "expected_updated_at": token,
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["code"] == "reading_list_cycle"

    reloaded = await auth_client.get(url)
    assert reloaded.status_code == 200, reloaded.text
    assert [
        (row["id"], row["continuing_volume_id"], row["waiting_volume_id"])
        for row in reloaded.json()["decisions"]
    ] == [(decision_id, CONTINUING_VOLUME, WAITING_VOLUME)]
    assert reloaded.json()["updated_at"] == token

    removed_prerequisite = await auth_client.delete(
        f"/api/v1/prerequisites/{prerequisite.json()['id']}"
    )
    assert removed_prerequisite.status_code == 204, removed_prerequisite.text

    reversed_choice = await auth_client.put(
        url,
        json={
            "continuing_volume_id": WAITING_VOLUME,
            "waiting_volume_id": CONTINUING_VOLUME,
            "expected_updated_at": token,
        },
    )
    assert reversed_choice.status_code == 200, reversed_choice.text
    assert [
        (row["continuing_volume_id"], row["waiting_volume_id"])
        for row in reversed_choice.json()["decisions"]
    ] == [(WAITING_VOLUME, CONTINUING_VOLUME)]


@pytest.mark.asyncio
async def test_migration_adds_the_column_table_and_constraints(
    async_db: AsyncSession,
) -> None:
    """The deployed schema gains the version token, the table, and its guards."""
    spec = importlib.util.spec_from_file_location("cbl_overlap_decisions_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(conn: Connection) -> None:
        conn.execute(text("CREATE SCHEMA overlap_migration_scratch"))
        conn.execute(text("SET search_path TO overlap_migration_scratch"))
        conn.execute(
            text("CREATE TABLE users (id int PRIMARY KEY)"),
        )
        conn.execute(
            text("CREATE TABLE external_identities (id int PRIMARY KEY)"),
        )
        conn.execute(
            text(
                "CREATE TABLE custom_cbl_lists ("
                "id int PRIMARY KEY, user_id int NOT NULL REFERENCES users(id))"
            ),
        )
        conn.execute(text("INSERT INTO users VALUES (7)"))
        conn.execute(text("INSERT INTO custom_cbl_lists VALUES (1, 7)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

        columns = conn.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'overlap_migration_scratch' "
                "AND table_name = 'custom_cbl_lists' "
                "AND column_name = 'overlap_decisions_updated_at'"
            )
        ).all()
        assert len(columns) == 1
        assert columns[0][1] == "NO"

        backfilled = conn.execute(
            text(
                "SELECT overlap_decisions_updated_at FROM custom_cbl_lists WHERE id = 1"
            )
        ).scalar()
        assert backfilled is not None

        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'overlap_migration_scratch' "
                "AND table_name = 'custom_cbl_overlap_decisions'"
            )
        ).all()
        assert tables == [("custom_cbl_overlap_decisions",)]

        constraints = conn.execute(
            text(
                "SELECT constraint_name, constraint_type FROM information_schema."
                "table_constraints WHERE table_schema = 'overlap_migration_scratch' "
                "AND table_name = 'custom_cbl_overlap_decisions'"
            )
        ).all()
        names = {row[0] for row in constraints}
        assert "fk_custom_cbl_overlap_decision_owner_list" in names
        assert "ck_custom_cbl_overlap_decision_distinct_volumes" in names
        assert "uq_custom_cbl_overlap_decision_pair" in names

        list_constraints = conn.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = 'overlap_migration_scratch' "
                "AND table_name = 'custom_cbl_lists'"
            )
        ).all()
        assert ("uq_custom_cbl_lists_id_user",) in list_constraints

        conn.execute(text("DROP SCHEMA overlap_migration_scratch CASCADE"))
        conn.execute(text("SET search_path TO public"))

    connection = await async_db.connection()
    await connection.run_sync(run)


@pytest.mark.asyncio
async def test_stored_decision_cannot_cross_reader_or_list_ownership(
    async_db: AsyncSession,
) -> None:
    """The composite owner-scoped foreign key rejects a foreign attachment."""
    owner = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="foreign_reader")
    owner_list = CustomCBLList(user_id=owner.id, name="Owned", mode="strict")
    other_list = CustomCBLList(user_id=other.id, name="Foreign", mode="strict")
    async_db.add_all([owner_list, other_list])
    await async_db.flush()
    identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="101"
    )
    waiting = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="202"
    )
    async_db.add_all([identity, waiting])
    await async_db.flush()
    await async_db.commit()

    from app.models.custom_cbl import CustomCBLOverlapDecision

    async_db.add(
        CustomCBLOverlapDecision(
            user_id=other.id,
            list_id=owner_list.id,
            continuing_external_identity_id=identity.id,
            waiting_external_identity_id=waiting.id,
        )
    )
    with pytest.raises(Exception) as error:
        await async_db.commit()
    assert "fk_custom_cbl_overlap_decision_owner_list" in str(error.value)
    await async_db.rollback()


@pytest.mark.asyncio
async def test_source_refresh_preserves_linked_reader_overlap_decision(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Refreshing shared provenance never resets a linked reader's approval."""
    user = await get_or_create_user_async(async_db)
    _, waiting_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="Mister Miracle",
        queue_position=1,
        volume_external_id="202",
    )
    _, continuing_issue = await _volume_thread(
        async_db,
        user_id=user.id,
        title="JLI",
        queue_position=2,
        volume_external_id="101",
    )
    issue_ids = [waiting_issue.id, continuing_issue.id]
    continuing_thread_id = continuing_issue.thread_id
    user_id = user.id
    source = CBLSource(
        repository="test/overlap-refresh",
        revision_sha="a" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/JLI.cbl",
        name="JLI",
        revision_sha="a" * 40,
        content_hash="a" * 64,
        declared_issue_count=2,
    )
    async_db.add(source_list)
    await async_db.flush()
    source_list_id = source_list.id
    await async_db.commit()
    list_id = await _strict_list(auth_client, issue_ids)
    async_db.add(
        CustomCBLSourceLink(
            user_id=user_id,
            cbl_source_list_id=source_list_id,
            custom_cbl_list_id=list_id,
            source_revision_sha="a" * 40,
            source_content_hash="a" * 64,
        )
    )
    await async_db.commit()
    saved = await auth_client.put(
        f"/api/v1/custom-cbls/{list_id}/overlap-decisions",
        json={"continuing_volume_id": CONTINUING_VOLUME, "waiting_volume_id": WAITING_VOLUME},
    )
    assert saved.status_code == 200, saved.text
    before = saved.json()
    before_blockers = await _thread_blockers(async_db, user_id, continuing_thread_id)
    assert before_blockers == []

    # A shared catalog refresh advances source provenance, not reader approval.
    await async_db.refresh(source)
    await async_db.refresh(source_list)
    source.revision_sha = "b" * 40
    source_list.revision_sha = "b" * 40
    source_list.content_hash = "b" * 64
    await async_db.commit()
    async_db.expire_all()

    reloaded = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/overlap-decisions")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["decisions"] == before["decisions"]
    assert reloaded.json()["updated_at"] == before["updated_at"]
    continuing = await async_db.get(Issue, issue_ids[1])
    waiting = await async_db.get(Issue, issue_ids[0])
    assert continuing is not None and waiting is not None
    assert continuing.status == waiting.status == "unread"
    assert await _thread_blockers(async_db, user_id, continuing.thread_id) == []
    link = (
        await async_db.execute(
            select(CustomCBLSourceLink).where(CustomCBLSourceLink.custom_cbl_list_id == list_id)
        )
    ).scalar_one()
    assert link.source_revision_sha == "a" * 40
    assert link.source_content_hash == "a" * 64


#: Source path shared by both revisions of the synthetic CBL in the upsert test.
SHARED_SOURCE_PATH = "DC/Overlap Sync.cbl"


def _shared_source_list(*, content_hash: str, issue_number: str) -> CBLList:
    """Build one synthetic shared-source revision carrying both overlap volumes.

    Args:
        content_hash: Content hash of this revision.
        issue_number: Issue number of the continuing series in this revision.

    Returns:
        Parsed CBL list for the shared source path.
    """
    return CBLList(
        source_path=SHARED_SOURCE_PATH,
        content_hash=content_hash,
        name="Overlap Sync",
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
    db: AsyncSession,
    *,
    repository: str,
    revision_sha: str,
    content_hash: str,
    issue_number: str,
) -> CBLSourceList:
    """Synchronize one synthetic shared-source revision and return its list row.

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
            _shared_source_list(content_hash=content_hash, issue_number=issue_number),
        ),
    )
    await db.flush()
    return (
        await db.execute(
            select(CBLSourceList)
            .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
            .where(
                CBLSource.repository == repository,
                CBLSourceList.source_path == SHARED_SOURCE_PATH,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_shared_source_upsert_preserves_linked_reader_decision(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A real shared-catalog upsert never resets a linked reader's approval.

    The narrower provenance test above changes revision fields directly. This
    regression drives the actual ``sync_cbl_lists`` path: the source list keeps
    its identity while its entries advance, the reader's decision and version
    token survive, effective eligibility does not change, and the reader's
    approved source snapshot is retained.
    """
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
    repository = f"test/overlap-sync-{uuid4().hex}"
    first_revision = "a" * 40
    first_content_hash = "a" * 64
    first_source_list = await _synced_source_list(
        async_db,
        repository=repository,
        revision_sha=first_revision,
        content_hash=first_content_hash,
        issue_number="1",
    )
    source_list_id = first_source_list.id
    await async_db.commit()

    list_id = await _strict_list(
        auth_client, [waiting_issue.id, continuing_issue.id], name="Overlap Sync"
    )
    async_db.add(
        CustomCBLSourceLink(
            user_id=user.id,
            cbl_source_list_id=source_list_id,
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
    assert refreshed.id == source_list_id

    stored_source = (
        await async_db.execute(
            select(CBLSourceList).where(CBLSourceList.id == source_list_id)
        )
    ).scalar_one()
    assert stored_source.revision_sha == second_revision
    assert stored_source.content_hash == second_content_hash
    entries = list(
        (
            await async_db.execute(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == source_list_id)
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
        async_db, user_id=user.id, cbl_source_list_id=source_list_id
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
