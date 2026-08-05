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


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _BindRecorder:
    def __init__(self, row_count: int) -> None:
        self.row_count = row_count

    def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(self.row_count)


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

    def __init__(self, row_count: int = 0) -> None:
        self.calls: list[tuple[str, str]] = []
        self.bind = _BindRecorder(row_count)

    def get_bind(self) -> _BindRecorder:
        return self.bind

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


def test_upgrade_removes_only_retired_reviews_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop only the retired Reviews table and thread metadata."""
    migration = _load_migration()
    recorder = _OperationRecorder(row_count=3)
    setattr(migration, "op", recorder)
    monkeypatch.setenv(migration.CONFIRMATION_ENV, "3")

    migration.upgrade()

    assert recorder.calls == [
        ("drop_table", "reviews"),
        ("batch_alter_table", "threads"),
        ("drop_column", "review_url"),
        ("drop_column", "last_review_at"),
    ]


def test_upgrade_requires_recorded_row_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Abort before mutation when no operator-confirmed count is supplied."""
    migration = _load_migration()
    recorder = _OperationRecorder(row_count=4)
    setattr(migration, "op", recorder)
    monkeypatch.delenv(migration.CONFIRMATION_ENV, raising=False)

    with pytest.raises(RuntimeError, match="current count: 4"):
        migration.upgrade()

    assert recorder.calls == []


def test_upgrade_rejects_changed_row_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Abort before mutation when the live count differs from confirmation."""
    migration = _load_migration()
    recorder = _OperationRecorder(row_count=5)
    setattr(migration, "op", recorder)
    monkeypatch.setenv(migration.CONFIRMATION_ENV, "4")

    with pytest.raises(RuntimeError, match="expected 4, found 5"):
        migration.upgrade()

    assert recorder.calls == []


def test_migration_is_forward_only() -> None:
    """Require backup restoration instead of fabricating deleted review data."""
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="restore a database backup"):
        migration.downgrade()
