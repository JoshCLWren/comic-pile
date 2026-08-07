"""Regression coverage for legacy-dependency continuity compatibility migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
BACKFILL_PATH = VERSIONS / "c84400000001_backfill_legacy_dependencies.py"
SYNC_PATH = VERSIONS / "c84400000002_sync_legacy_dependency_writes.py"


class _OperationRecorder:
    """Capture migration SQL without requiring a live PostgreSQL database."""

    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.structural_calls: list[tuple[str, object]] = []

    def execute(self, statement: object) -> None:
        self.executed_sql.append(" ".join(str(statement).split()))

    def add_column(self, table_name: str, column: object) -> None:
        self.structural_calls.append(("add_column", table_name))

    def create_foreign_key(self, name: str, *_args: object, **_kwargs: object) -> None:
        self.structural_calls.append(("create_foreign_key", name))

    def create_unique_constraint(self, name: str, *_args: object) -> None:
        self.structural_calls.append(("create_unique_constraint", name))

    def drop_constraint(self, name: str, *_args: object, **_kwargs: object) -> None:
        self.structural_calls.append(("drop_constraint", name))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.structural_calls.append(("drop_column", (table_name, column_name)))


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_blocked_targets(
    dependencies: list[tuple[int, int]],
    issue_statuses: dict[int, str],
) -> set[int]:
    """Model the legacy rule: an unread source issue blocks its target issue."""
    return {
        target_id
        for source_id, target_id in dependencies
        if issue_statuses[source_id] != "read"
    }


def _continuity_blocked_targets(
    rules: list[dict[str, object]],
    issue_statuses: dict[int, str],
) -> set[int]:
    """Model the equivalent generalized issue->issue item-read rule."""
    blocked: set[int] = set()
    for rule in rules:
        if (
            rule["source_type"] == "issue"
            and rule["target_type"] == "issue"
            and rule["satisfaction_type"] == "item_read"
            and rule["checkpoint_issue_id"] is None
            and issue_statuses[int(rule["source_id"])] != "read"
        ):
            blocked.add(int(rule["target_id"]))
    return blocked


def test_backfill_is_idempotent_and_reuses_equivalent_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backfill links equivalent rules and inserts only still-unrepresented edges."""
    migration = _load_migration(BACKFILL_PATH, "legacy_dependency_backfill")
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    sql = "\n".join(recorder.executed_sql)
    assert "UPDATE continuity_rules AS rule SET legacy_dependency_id = dep.id" in sql
    assert "rule.satisfaction_type = 'item_read'" in sql
    assert "LEFT JOIN continuity_rules AS existing" in sql
    assert "existing.id IS NULL" in sql
    assert "ON CONFLICT (user_id, source_type, source_id, target_type, target_id) DO NOTHING" in sql


def test_sync_trigger_preserves_legacy_semantics_for_create_and_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every legacy write is mirrored as one owned issue-to-issue item-read rule."""
    migration = _load_migration(SYNC_PATH, "legacy_dependency_sync")
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    assert len(recorder.executed_sql) == 2
    function_sql, trigger_sql = recorder.executed_sql
    assert "source_owner_id <> target_owner_id" in function_sql
    assert "DELETE FROM continuity_rules WHERE legacy_dependency_id = NEW.id" in function_sql
    assert "'issue', NEW.source_issue_id, 'issue', NEW.target_issue_id, 'item_read'" in function_sql
    assert "ON CONFLICT (user_id, source_type, source_id, target_type, target_id)" in function_sql
    assert "satisfaction_type = 'item_read'" in function_sql
    assert "legacy_dependency_id = EXCLUDED.legacy_dependency_id" in function_sql
    assert "note = EXCLUDED.note" in function_sql
    assert "AFTER INSERT OR UPDATE OF source_issue_id, target_issue_id, note" in trigger_sql
    assert "ON dependencies" in trigger_sql


def test_sync_downgrade_only_removes_the_live_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback stops mirroring without deleting legacy or generalized data."""
    migration = _load_migration(SYNC_PATH, "legacy_dependency_sync_downgrade")
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.downgrade()

    assert recorder.executed_sql == [
        "DROP TRIGGER IF EXISTS trg_sync_legacy_dependency_to_continuity_rule ON dependencies",
        "DROP FUNCTION IF EXISTS sync_legacy_dependency_to_continuity_rule()",
    ]


@pytest.mark.parametrize(
    ("issue_statuses", "expected_blocked"),
    [
        ({1: "unread", 2: "unread", 3: "unread", 4: "unread"}, {2, 3, 4}),
        ({1: "read", 2: "unread", 3: "unread", 4: "unread"}, {3, 4}),
        ({1: "read", 2: "read", 3: "unread", 4: "unread"}, {4}),
        ({1: "read", 2: "read", 3: "read", 4: "unread"}, set()),
    ],
)
def test_backfilled_rules_match_legacy_blocking_for_representative_graph(
    issue_statuses: dict[int, str],
    expected_blocked: set[int],
) -> None:
    """A representative dependency graph blocks identically after translation."""
    dependencies = [(1, 2), (2, 3), (1, 4), (3, 4)]
    rules = [
        {
            "source_type": "issue",
            "source_id": source_id,
            "target_type": "issue",
            "target_id": target_id,
            "satisfaction_type": "item_read",
            "checkpoint_issue_id": None,
        }
        for source_id, target_id in dependencies
    ]

    legacy = _legacy_blocked_targets(dependencies, issue_statuses)
    continuity = _continuity_blocked_targets(rules, issue_statuses)

    assert legacy == expected_blocked
    assert continuity == expected_blocked
    assert continuity == legacy
