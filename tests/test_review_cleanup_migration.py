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
    def __init__(self, row_count: int, calls: list[tuple[str, object]]) -> None:
        self.row_count = row_count
        self.calls = calls

    def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> _ScalarResult:
        statement_text = str(statement)
        if statement_text == "SELECT COUNT(*) FROM reviews":
            return _ScalarResult(self.row_count)
        self.calls.append(("execute", {"sql": statement_text, "parameters": parameters}))
        return _ScalarResult(0)


class _BatchRecorder:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def drop_column(self, column_name: str) -> None:
        self.calls.append(("drop_column", column_name))


class _OperationRecorder:
    def __init__(self, row_count: int = 0) -> None:
        self.calls: list[tuple[str, object]] = []
        self.bind = _BindRecorder(row_count, self.calls)

    def get_bind(self) -> _BindRecorder:
        return self.bind

    def create_table(self, table_name: str, *_columns: object) -> None:
        self.calls.append(("create_table", table_name))

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


def _install_recorder(
    monkeypatch: pytest.MonkeyPatch,
    migration: ModuleType,
    *,
    row_count: int,
) -> _OperationRecorder:
    recorder = _OperationRecorder(row_count=row_count)
    monkeypatch.setattr(migration, "op", recorder)
    return recorder


def _expected_upgrade_calls(row_count: int) -> list[tuple[str, object]]:
    return [
        ("create_table", "migration_data_deletion_audit"),
        (
            "execute",
            {
                "sql": (
                    "INSERT INTO migration_data_deletion_audit "
                    "(migration_revision, resource, row_count) "
                    "VALUES (:migration_revision, :resource, :row_count)"
                ),
                "parameters": {
                    "migration_revision": "7f41d0a9c2e1",
                    "resource": "reviews",
                    "row_count": row_count,
                },
            },
        ),
        ("drop_table", "reviews"),
        ("batch_alter_table", "threads"),
        ("drop_column", "review_url"),
        ("drop_column", "last_review_at"),
    ]


def test_upgrade_records_scope_before_removing_retired_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    recorder = _install_recorder(monkeypatch, migration, row_count=3)
    monkeypatch.setenv(migration.CONFIRMATION_ENV, "3")

    migration.upgrade()

    assert recorder.calls == _expected_upgrade_calls(3)


def test_upgrade_records_empty_reviews_table(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    recorder = _install_recorder(monkeypatch, migration, row_count=0)
    monkeypatch.delenv(migration.CONFIRMATION_ENV, raising=False)

    migration.upgrade()

    assert recorder.calls == _expected_upgrade_calls(0)


def test_upgrade_requires_recorded_row_count(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    recorder = _install_recorder(monkeypatch, migration, row_count=4)
    monkeypatch.delenv(migration.CONFIRMATION_ENV, raising=False)

    with pytest.raises(RuntimeError, match="current count: 4"):
        migration.upgrade()

    assert recorder.calls == []


def test_upgrade_rejects_changed_row_count(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    recorder = _install_recorder(monkeypatch, migration, row_count=5)
    monkeypatch.setenv(migration.CONFIRMATION_ENV, "4")

    with pytest.raises(RuntimeError, match="expected 4, found 5"):
        migration.upgrade()

    assert recorder.calls == []


def test_migration_is_forward_only() -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="restore a database backup"):
        migration.downgrade()
