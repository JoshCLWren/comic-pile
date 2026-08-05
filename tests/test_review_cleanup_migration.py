"""Regression coverage for the retired Reviews persistence cleanup migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Self

import pytest

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "7f41d0a9c2e1_drop_orphaned_reviews.py"
)


class _BatchRecorder:
    """Record batch table operations in execution order."""

    def __init__(self, calls: list[tuple[str, str]]) -> None:
        self.calls = calls

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def drop_column(self, column_name: str) -> None:
        self.calls.append(("drop_column", column_name))


class _OperationRecorder:
    """Minimal Alembic operation facade used to verify migration intent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def drop_table(self, table_name: str) -> None:
        self.calls.append(("drop_table", table_name))

    def batch_alter_table(self, table_name: str, *, schema: str | None) -> _BatchRecorder:
        assert schema is None
        self.calls.append(("batch_alter_table", table_name))
        return _BatchRecorder(self.calls)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_cleanup_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_removes_only_retired_reviews_persistence() -> None:
    migration = _load_migration()
    recorder = _OperationRecorder()
    migration.op = recorder

    migration.upgrade()

    assert recorder.calls == [
        ("drop_table", "reviews"),
        ("batch_alter_table", "threads"),
        ("drop_column", "review_url"),
        ("drop_column", "last_review_at"),
    ]


def test_migration_is_forward_only() -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="restore a database backup"):
        migration.downgrade()
