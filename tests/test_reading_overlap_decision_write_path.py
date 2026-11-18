"""Reader-facing overlap decision write path, versioning, and durable schema.

The reader approves one overlap choice per Reading List and exact Comic Vine
volume pair. The choice is durable, owner-scoped, versioned, and survives a
later membership rewrite. The migration that introduces the storage is
executed here so a deployed database can never miss the column or the table.
"""

import ast
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.external_identity import ExternalIdentity
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




#: Source path shared by both revisions of the synthetic CBL in the upsert test.






