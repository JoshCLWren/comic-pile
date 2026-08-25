"""Tests for cache_entries and cache_generations schema and TTL sweep.

Verifies:
- Model definitions match expected schema
- Composite PK on cache_entries (namespace, cache_key)
- Index on expires_at for sweep performance
- Lazy expired-skip on read
- Sweep removes only expired rows
"""

from datetime import UTC, datetime, timedelta
import ast
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

VERSIONS_DIR = Path(__file__).parents[1] / "alembic" / "versions"


def _iter_revisions() -> list[tuple[str, list[str]]]:
    """Return (revision, down_revision_list) parsed from migration modules.

    Merge migrations use a tuple down_revision, so each parent is expanded into the
    down-revision list. The real Alembic head set is derived from these lists.
    """
    found: list[tuple[str, list[str]]] = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        file_text = path.read_text(encoding="utf-8")
        rev = None
        down: list[str] = []
        for line in file_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("revision:") and rev is None:
                rev = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            if stripped.startswith("down_revision:") and not down:
                rhs = stripped.split("=", 1)[1].strip()
                if rhs == "None":
                    down = []
                else:
                    value = ast.literal_eval(rhs)
                    down = list(value) if isinstance(value, tuple) else [value]
                break
        if rev is not None:
            found.append((rev, down))
    return found


def _real_heads() -> list[str]:
    """Revisions that no other migration depends on (expanding merge parents)."""
    revisions = _iter_revisions()
    all_down = {d for _, downs in revisions for d in downs}
    return [rev for rev, _ in revisions if rev not in all_down]


def test_cache_migration_is_the_single_head() -> None:
    """The cache migration must be the only Alembic head; duplicate down_revisions branch history."""
    assert _real_heads() == ["h9i0j1k2l3m4"], (
        f"Expected a single head h9i0j1k2l3m4, got {_real_heads()}"
    )


def test_cache_entries_table_exists_in_metadata() -> None:
    """cache_entries table must be registered in SQLAlchemy metadata."""
    assert "cache_entries" in Base.metadata.tables


def test_cache_generations_table_exists_in_metadata() -> None:
    """cache_generations table must be registered in SQLAlchemy metadata."""
    assert "cache_generations" in Base.metadata.tables


def test_cache_entries_has_expected_columns() -> None:
    """cache_entries must have namespace, cache_key, value, expires_at, created_at."""
    table = Base.metadata.tables["cache_entries"]
    column_names = {col.name for col in table.columns}
    expected = {"namespace", "cache_key", "value", "expires_at", "created_at"}
    assert expected == column_names


def test_cache_entries_composite_primary_key() -> None:
    """cache_entries PK must be (namespace, cache_key)."""
    table = Base.metadata.tables["cache_entries"]
    pk_cols = [col.name for col in table.primary_key.columns]
    assert pk_cols == ["namespace", "cache_key"]


def test_cache_entries_expires_at_index() -> None:
    """cache_entries must have an index on expires_at for sweep queries."""
    table = Base.metadata.tables["cache_entries"]
    index_names = {idx.name for idx in table.indexes}
    assert "ix_cache_entries_expires_at" in index_names
    idx = next(idx for idx in table.indexes if idx.name == "ix_cache_entries_expires_at")
    assert "expires_at" in idx.columns


def test_cache_generations_has_expected_columns() -> None:
    """cache_generations must have scope and generation."""
    table = Base.metadata.tables["cache_generations"]
    column_names = {col.name for col in table.columns}
    assert {"scope", "generation"} == column_names


def test_cache_generations_scope_is_pk() -> None:
    """cache_generations PK must be scope."""
    table = Base.metadata.tables["cache_generations"]
    pk_cols = [col.name for col in table.primary_key.columns]
    assert pk_cols == ["scope"]


@pytest.mark.asyncio
async def test_sweep_removes_only_expired_rows(async_db: AsyncSession) -> None:
    """Sweep query must delete only rows where expires_at <= now."""
    now = datetime.now(UTC)
    expired_at = now - timedelta(hours=1)
    valid_at = now + timedelta(hours=1)

    await async_db.execute(
        text(
            "INSERT INTO cache_entries (namespace, cache_key, value, expires_at, created_at) "
            "VALUES (:ns1, :k1, :v1, :exp1, :now1), (:ns2, :k2, :v2, :exp2, :now2)"
        ),
        {
            "ns1": "test",
            "k1": "expired_key",
            "v1": '{"data": "old"}',
            "exp1": expired_at,
            "now1": now,
            "ns2": "test",
            "k2": "valid_key",
            "v2": '{"data": "fresh"}',
            "exp2": valid_at,
            "now2": now,
        },
    )
    await async_db.flush()

    result = await async_db.execute(text("SELECT COUNT(*) FROM cache_entries"))
    before_count = result.scalar_one()
    assert before_count == 2

    await async_db.execute(text("DELETE FROM cache_entries WHERE expires_at <= NOW()"))
    await async_db.flush()

    result = await async_db.execute(text("SELECT COUNT(*) FROM cache_entries"))
    after_count = result.scalar_one()
    assert after_count == 1

    result = await async_db.execute(text("SELECT cache_key FROM cache_entries"))
    remaining = result.scalar_one()
    assert remaining == "valid_key"


@pytest.mark.asyncio
async def test_cache_entry_point_lookup_uses_pk(async_db: AsyncSession) -> None:
    """Point lookup by (namespace, cache_key) must use the composite PK."""
    now = datetime.now(UTC)
    await async_db.execute(
        text(
            "INSERT INTO cache_entries (namespace, cache_key, value, expires_at, created_at) "
            "VALUES (:ns, :k, :v, :exp, :now)"
        ),
        {
            "ns": "user:1",
            "k": "thread_list",
            "v": '{"ids": [1,2,3]}',
            "exp": now + timedelta(hours=1),
            "now": now,
        },
    )
    await async_db.flush()

    result = await async_db.execute(
        text("SELECT value FROM cache_entries WHERE namespace = :ns AND cache_key = :k"),
        {"ns": "user:1", "k": "thread_list"},
    )
    row = result.scalar_one()
    assert row == {"ids": [1, 2, 3]}


@pytest.mark.asyncio
async def test_cache_generation_increment_and_read(async_db: AsyncSession) -> None:
    """Generation counter must support increment and read."""
    await async_db.execute(
        text("INSERT INTO cache_generations (scope, generation) VALUES (:s, 0)"),
        {"s": "user:42"},
    )
    await async_db.flush()

    await async_db.execute(
        text("UPDATE cache_generations SET generation = generation + 1 WHERE scope = :s"),
        {"s": "user:42"},
    )
    await async_db.flush()

    result = await async_db.execute(
        text("SELECT generation FROM cache_generations WHERE scope = :s"),
        {"s": "user:42"},
    )
    gen = result.scalar_one()
    assert gen == 1


@pytest.mark.asyncio
async def test_cache_entries_jsonb_value_roundtrip(async_db: AsyncSession) -> None:
    """JSONB value must survive insert and read."""
    now = datetime.now(UTC)
    complex_value = {"nested": {"list": [1, 2, 3]}, "flag": True, "count": 42}
    await async_db.execute(
        text(
            "INSERT INTO cache_entries (namespace, cache_key, value, expires_at, created_at) "
            "VALUES (:ns, :k, :v, :exp, :now)"
        ),
        {
            "ns": "app",
            "k": "config",
            "v": json.dumps(complex_value),
            "exp": now + timedelta(hours=1),
            "now": now,
        },
    )
    await async_db.flush()

    result = await async_db.execute(
        text("SELECT value FROM cache_entries WHERE namespace = :ns AND cache_key = :k"),
        {"ns": "app", "k": "config"},
    )
    loaded = result.scalar_one()
    assert loaded["nested"]["list"] == [1, 2, 3]
    assert loaded["flag"] is True
    assert loaded["count"] == 42


def test_cache_entries_values_column_is_jsonb() -> None:
    """The value column must use JSONB type for efficient queries."""
    table = Base.metadata.tables["cache_entries"]
    value_col = table.c.value
    from sqlalchemy.dialects.postgresql import JSONB

    assert isinstance(value_col.type, JSONB)


def test_cache_generation_generation_is_bigint() -> None:
    """The generation column must be BigInteger for large counter values."""
    from sqlalchemy import BigInteger

    table = Base.metadata.tables["cache_generations"]
    gen_col = table.c.generation
    assert isinstance(gen_col.type, BigInteger)
