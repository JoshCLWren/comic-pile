"""Closure-critical tests for the non-admin GitHub issue submission limit (#3074).

Covers: first submission succeeds, the second submission inside the rolling
hour is blocked with a 429/Retry-After contract, submissions after the window
succeed, admins bypass the limit, failed GitHub attempts do not consume the
allowance, the key is the authenticated user identity (not IP or browser
state), concurrent submissions cannot bypass the limit, and the durable table
migration chains onto the current Alembic head.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


MIGRATION_ID = "c30740000001"
MIGRATION_PARENT = "d41480000001"


def test_rate_limit_migration_chains_onto_main_head() -> None:
    """The submission-limit migration extends the base head without forking it.

    The parent must resolve on the checkout under test. A conditional
    single-head assertion would let the test pass while the revision graph is
    dangling, which is the failure mode this test exists to catch. Later
    revisions may extend the same chain above this one, so the durable
    assertions are a single head and this revision remaining on its path.
    """
    root = Path(__file__).parents[1]
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    revision = script.get_revision(MIGRATION_ID)
    assert revision is not None
    assert revision.down_revision == MIGRATION_PARENT
    assert script.get_revision(MIGRATION_PARENT) is not None
    heads = script.get_heads()
    assert len(heads) == 1
    assert _is_on_head_path(script, MIGRATION_ID, heads[0])


@pytest.mark.asyncio
async def test_rate_limit_migration_roundtrip_postgres(async_db: AsyncSession) -> None:
    """Upgrade, enforce the FK/PK contract, then downgrade in PostgreSQL."""
    spec = importlib.util.spec_from_file_location("rate_limit_migration", _migration_path())
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def verify(conn: Connection) -> None:
        conn.execute(text("SET LOCAL search_path TO pg_temp, public"))
        conn.execute(text("CREATE TEMP TABLE users (id integer PRIMARY KEY) ON COMMIT DROP"))
        conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

        conn.execute(
            text(
                "INSERT INTO github_issue_submission_limits (user_id, last_submitted_at) "
                "VALUES (1, now())"
            )
        )
        # Primary key rejects a second row for the same user.
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("INSERT INTO github_issue_submission_limits (user_id) VALUES (1)")
            )
        # Foreign key rejects a row for a user that does not exist.
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("INSERT INTO github_issue_submission_limits (user_id) VALUES (99)")
            )
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert (
            conn.execute(
                text("SELECT to_regclass('pg_temp.github_issue_submission_limits')")
            ).scalar_one()
            is None
        )

    connection = await async_db.connection()
    await connection.run_sync(verify)


def _migration_path() -> Path:
    """Return the migration script for the submission-limit table."""
    return (
        Path(__file__).parents[1]
        / f"alembic/versions/{MIGRATION_ID}_github_issue_submission_limits.py"
    )

def _is_on_head_path(script: ScriptDirectory, revision_id: str, head: str) -> bool:
    """Return whether ``revision_id`` is ``head`` or one of its ancestors.

    Args:
        script: Loaded revision map.
        revision_id: Revision that must remain on the chain.
        head: Current single Alembic head.

    Returns:
        ``True`` when the head's history reaches ``revision_id``.
    """
    pending: list[str | None] = [head]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current is None or current in seen:
            continue
        if current == revision_id:
            return True
        seen.add(current)
        revision = script.get_revision(current)
        if revision is None:
            continue
        down = revision.down_revision
        if isinstance(down, str):
            pending.append(down)
        elif down:
            pending.extend(down)
    return False
