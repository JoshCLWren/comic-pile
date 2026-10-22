"""Reader-facing overlap decision write path, versioning, and durable schema.

The reader approves one overlap choice per Reading List and exact Comic Vine
volume pair. The choice is durable, owner-scoped, versioned, and survives a
later membership rewrite. The migration that introduces the storage is
executed here so a deployed database can never miss the column or the table.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import Connection, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic/versions/r40180000001_add_custom_cbl_overlap_decisions.py"
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


@pytest.mark.asyncio
async def test_reader_saves_and_reloads_one_overlap_decision(
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
