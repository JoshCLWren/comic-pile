"""Issue #4008: shared CBL catalog search-index schema checks.

The Python catalog browse API is retired (Rust serves it); these checks keep the
ORM-declared source-list indexes honest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceList



async def _seed_source(
    db: AsyncSession,
    *,
    repository: str = "JoshCLWren/CBL-ReadingLists",
    revision: str = "abc123",
) -> CBLSource:
    source = CBLSource(
        repository=repository,
        revision_sha=revision,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    return source


async def _seed_list(
    db: AsyncSession,
    *,
    source: CBLSource,
    name: str,
    path: str,
    active: bool = True,
    count: int | None = 5,
) -> CBLSourceList:
    row = CBLSourceList(
        source_id=source.id,
        source_path=path,
        name=name,
        declared_issue_count=count,
        content_hash=sha256(f"{name}|{path}".encode()).hexdigest(),
        revision_sha=source.revision_sha,
        active=active,
    )
    db.add(row)
    await db.flush()
    return row


async def _nested_catalog(db: AsyncSession) -> CBLSource:
    """Seed a publisher / nested volume / unsorted catalog with one inactive list."""
    source = await _seed_source(db)
    await _seed_list(
        db,
        source=source,
        name="Mister Miracle 1989",
        path="DC/Mister Miracle (1989)/Mister Miracle.cbl",
    )
    await _seed_list(
        db,
        source=source,
        name="Mister Miracle Annual",
        path="DC/Mister Miracle (1989)/unsorted/Annual.cbl",
    )
    await _seed_list(db, source=source, name="JLI", path="DC/JLI/JLI.cbl")
    await _seed_list(
        db,
        source=source,
        name="Secret Wars",
        path="Marvel/Events/Secret Wars.cbl",
    )
    await _seed_list(
        db,
        source=source,
        name="Secret Wars Crossovers",
        path="Marvel/Events/Tie-ins/Crossovers.cbl",
    )
    await _seed_list(db, source=source, name="Root Reading List", path="Root Reading List.cbl")
    await _seed_list(
        db,
        source=source,
        name="Archived Mister Miracle",
        path="DC/Mister Miracle (1989)/Archived.cbl",
        active=False,
    )
    await _seed_list(
        db,
        source=source,
        name="Archived Only",
        path="Archived Only/Dead.cbl",
        active=False,
    )
    await db.commit()
    return source
























@pytest.mark.asyncio
async def test_folder_prefix_query_uses_the_catalog_prefix_index(
    async_db: AsyncSession,
) -> None:
    """The folder prefix predicate is served by the active/path index.

    Tests build the schema from ORM metadata, so this also proves the index is
    declared on the model rather than only in the migration.
    """
    await _nested_catalog(async_db)
    await async_db.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = (
        (
            await async_db.execute(
                text(
                    "EXPLAIN SELECT id FROM cbl_source_lists "
                    "WHERE active AND source_path LIKE 'DC/%'"
                )
            )
        )
        .scalars()
        .all()
    )
    plan = "\n".join(plan_rows)
    assert "ix_cbl_source_list_active_path" in plan, plan










@pytest.mark.asyncio
async def test_metadata_search_indexes_exist(
    async_db: AsyncSession,
) -> None:
    """Metadata-created schemas retain both migration-managed search indexes."""
    index_rows = (
        (
            await async_db.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'cbl_source_lists'")
            )
        )
        .scalars()
        .all()
    )
    assert {"ix_cbl_source_list_name_trgm", "ix_cbl_source_list_source_path_trgm"} <= set(
        index_rows
    )
    for column in ("name", "source_path"):
        await async_db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (
                await async_db.execute(
                    text(
                        f"EXPLAIN SELECT id FROM cbl_source_lists WHERE {column} ILIKE '%miracle%'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert f"ix_cbl_source_list_{column}_trgm" in plan, plan


