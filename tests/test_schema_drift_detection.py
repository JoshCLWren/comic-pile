"""Regression tests for test schema drift detection."""

from dataclasses import dataclass

import pytest
from sqlalchemy import UniqueConstraint

import tests.conftest as test_conftest


@dataclass
class FakeInspector:
    """Minimal inspector stub for schema drift tests."""

    table_names: set[str]
    columns: dict[str, list[str]]
    indexes: dict[str, list[str]]
    unique_constraints: dict[str, list[str]]

    def has_table(self, table_name: str) -> bool:
        """Return whether the table exists."""
        return table_name in self.table_names

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        """Return column metadata for a table."""
        return [{"name": column_name} for column_name in self.columns[table_name]]

    def get_indexes(self, table_name: str) -> list[dict[str, str]]:
        """Return index metadata for a table."""
        return [{"name": index_name} for index_name in self.indexes.get(table_name, [])]

    def get_unique_constraints(self, table_name: str) -> list[dict[str, str]]:
        """Return unique constraint metadata for a table."""
        return [
            {"name": constraint_name}
            for constraint_name in self.unique_constraints.get(table_name, [])
        ]


def build_fake_inspector() -> FakeInspector:
    """Build an inspector populated from SQLAlchemy metadata."""
    columns: dict[str, list[str]] = {}
    indexes: dict[str, list[str]] = {}
    unique_constraints: dict[str, list[str]] = {}

    for table_name, table in test_conftest.Base.metadata.tables.items():
        columns[table_name] = [column.name for column in table.columns]
        indexes[table_name] = [index.name for index in table.indexes if index.name is not None]
        unique_constraints[table_name] = [
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint) and constraint.name is not None
        ]

    return FakeInspector(
        table_names=set(test_conftest.Base.metadata.tables),
        columns=columns,
        indexes=indexes,
        unique_constraints=unique_constraints,
    )


def test_has_schema_drift_returns_false_for_matching_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching tables, columns, indexes, and constraints should not trigger drift."""
    fake_inspector = build_fake_inspector()

    def fake_inspect(_conn: object) -> FakeInspector:
        return fake_inspector

    monkeypatch.setattr(test_conftest, "inspect", fake_inspect)

    assert test_conftest._has_schema_drift(object()) is False


def test_has_schema_drift_detects_missing_issue_position_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing indexes should trigger schema recreation."""
    fake_inspector = build_fake_inspector()
    fake_inspector.indexes["issues"].remove("ix_issue_thread_position")

    def fake_inspect(_conn: object) -> FakeInspector:
        return fake_inspector

    monkeypatch.setattr(test_conftest, "inspect", fake_inspect)

    assert test_conftest._has_schema_drift(object()) is True


def test_has_schema_drift_detects_missing_issue_unique_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing unique constraints should trigger schema recreation."""
    fake_inspector = build_fake_inspector()
    fake_inspector.unique_constraints["issues"].remove("uq_issue_thread_number")

    def fake_inspect(_conn: object) -> FakeInspector:
        return fake_inspector

    monkeypatch.setattr(test_conftest, "inspect", fake_inspect)

    assert test_conftest._has_schema_drift(object()) is True
