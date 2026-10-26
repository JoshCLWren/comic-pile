"""Data migration that collapses internal whitespace in stored tag keys (#4182).

``normalize_tag_name`` used to trim and lowercase only, so a tag saved as
``Red  Label`` kept ``red  label`` while lookups now ask for ``red label``.
``c42100000001`` must fix those stored keys and merge rows that collapse to the
same uniqueness-scope key without losing assignments.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/c42100000001_normalize_tag_names.py"
)


def _load_migration() -> ModuleType:
    """Import the revision module without depending on Alembic's env setup."""
    spec = importlib.util.spec_from_file_location("normalize_tag_names", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _insert_tag(
    conn: Connection,
    *,
    name: str,
    normalized_name: str,
    scope: str,
    owner_user_id: int | None,
    color: str,
    created_at: datetime,
) -> int:
    """Insert one tag row with an explicitly legacy stored key."""
    tag_id = conn.execute(
        text(
            "INSERT INTO tags "
            "(name, normalized_name, scope, owner_user_id, color, created_at, updated_at) "
            "VALUES (:name, :normalized_name, :scope, :owner_user_id, :color, "
            ":created_at, :created_at) "
            "RETURNING id"
        ),
        {
            "name": name,
            "normalized_name": normalized_name,
            "scope": scope,
            "owner_user_id": owner_user_id,
            "color": color,
            "created_at": created_at,
        },
    ).scalar_one()
    return int(tag_id)


def _assign(conn: Connection, tag_id: int, target_id: int, created_at: datetime) -> None:
    """Assign a tag to an Issue target."""
    conn.execute(
        text(
            "INSERT INTO tag_assignments "
            "(tag_id, target_type, target_id, created_at) "
            "VALUES (:tag_id, 'Issue', :target_id, :created_at)"
        ),
        {"tag_id": tag_id, "target_id": target_id, "created_at": created_at},
    )


def _keys(conn: Connection) -> dict[int, tuple[str, str, int | None]]:
    """Return ``{tag_id: (normalized_name, scope, owner_user_id)}``."""
    rows = conn.execute(
        text("SELECT id, normalized_name, scope, owner_user_id FROM tags")
    ).all()
    return {
        int(tag_id): (normalized_name, scope, owner_user_id)
        for tag_id, normalized_name, scope, owner_user_id in rows
    }


def _assignments(conn: Connection) -> dict[int, set[int]]:
    """Return ``{tag_id: {target ids}}`` for Issue assignments."""
    rows = conn.execute(
        text(
            "SELECT tag_id, target_id FROM tag_assignments "
            "WHERE target_type = 'Issue'"
        )
    ).all()
    grouped: dict[int, set[int]] = {}
    for tag_id, target_id in rows:
        grouped.setdefault(int(tag_id), set()).add(int(target_id))
    return grouped


async def test_migration_merges_whitespace_duplicates_and_keeps_assignments(
    async_db: AsyncSession, default_user: User
) -> None:
    """Legacy keys are normalized; colliding rows merge without losing tags."""
    module = _load_migration()
    connection = await async_db.connection()
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 1, 2, tzinfo=UTC)

    def run(conn: Connection) -> None:
        survivor = _insert_tag(
            conn,
            name="Tagmig Red Label",
            normalized_name="tagmig red label",
            scope="global",
            owner_user_id=None,
            color="#DC2626",
            created_at=early,
        )
        duplicate = _insert_tag(
            conn,
            name="Tagmig Red  Label",
            normalized_name="tagmig red  label",
            scope="global",
            owner_user_id=None,
            color="#2563EB",
            created_at=late,
        )
        # The duplicate shares target 101 with the survivor and adds target 102.
        _assign(conn, survivor, 101, early)
        _assign(conn, duplicate, 101, late)
        _assign(conn, duplicate, 102, late)

        solo = _insert_tag(
            conn,
            name="Tagmig Solo  Tag",
            normalized_name="tagmig solo  tag",
            scope="global",
            owner_user_id=None,
            color="#16A34A",
            created_at=early,
        )
        private_old = _insert_tag(
            conn,
            name="Tagmig Mine  Tag",
            normalized_name="tagmig mine  tag",
            scope="private",
            owner_user_id=default_user.id,
            color="#DB2777",
            created_at=early,
        )
        private_duplicate = _insert_tag(
            conn,
            name="Tagmig Mine Tag",
            normalized_name="tagmig mine tag",
            scope="private",
            owner_user_id=default_user.id,
            color="#9333EA",
            created_at=late,
        )
        _assign(conn, private_old, 201, early)
        _assign(conn, private_duplicate, 202, late)

        # Same key in a different scope is a different uniqueness scope.
        global_shared = _insert_tag(
            conn,
            name="Tagmig Shared  Name",
            normalized_name="tagmig shared  name",
            scope="global",
            owner_user_id=None,
            color="#EA580C",
            created_at=early,
        )
        private_shared = _insert_tag(
            conn,
            name="Tagmig Shared Name",
            normalized_name="tagmig shared name",
            scope="private",
            owner_user_id=default_user.id,
            color="#0891B2",
            created_at=late,
        )

        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

        keys = _keys(conn)
        assert duplicate not in keys
        assert private_duplicate not in keys
        assert keys[survivor] == ("tagmig red label", "global", None)
        assert keys[solo][0] == "tagmig solo tag"
        assert keys[private_old] == ("tagmig mine tag", "private", default_user.id)
        assert keys[global_shared] == ("tagmig shared name", "global", None)
        assert keys[private_shared] == ("tagmig shared name", "private", default_user.id)

        assignments = _assignments(conn)
        assert assignments[survivor] == {101, 102}
        assert duplicate not in assignments
        assert assignments[private_old] == {201, 202}
        assert private_duplicate not in assignments

        # A second run changes nothing (idempotent on an already-migrated DB).
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert _keys(conn) == keys
        assert _assignments(conn) == assignments

    await connection.run_sync(run)
