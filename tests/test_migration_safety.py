"""Tests for the fail-closed migration safety gates (issue #3053)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import migration_safety as ms

UNIQUE_MIGRATION = '''
revision: str = "a1b2c3d4e5f6"
down_revision = None

def upgrade() -> None:
    op.create_unique_constraint(
        "uq_plan_issue", "reading_plan_issues", ["plan_id", "issue_id"]
    )
'''

DATA_MIGRATION = '''
revision = "b2c3d4e5f6a7"

def upgrade() -> None:
    op.execute("UPDATE threads SET format = 'unknown' WHERE format IS NULL")
'''

UNIQUE_RAW_SQL = '''
revision = "c3d4e5f6a7b8"

def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_review ON reviews (user_id)")
'''

DESTRUCTIVE_MIGRATION = '''
revision = "d4e5f6a7b8c9"

def upgrade() -> None:
    op.drop_column("threads", "legacy_format")
'''

SAFE_MIGRATION = '''
revision = "e5f6a7b8c9d0"

def upgrade() -> None:
    op.add_column("threads", sa.Column("notes", sa.String(200), nullable=True))
'''


def _unique_manifest() -> dict[str, object]:
    return {
        "revision": "a1b2c3d4e5f6",
        "summary": "enforce uniqueness",
        "risks": ["unique-constraint"],
        "preflight_checks": [
            {
                "name": "no duplicates",
                "condition": "reading_plan_issues has no duplicate pairs",
                "sql": (
                    "SELECT count(*) FROM (SELECT plan_id, issue_id "
                    "FROM reading_plan_issues GROUP BY plan_id, issue_id "
                    "HAVING count(*) > 1) dupes"
                ),
                "expect": {"operator": "equals", "value": 0},
            }
        ],
    }


def _write(repo: Path, relative: str, content: str) -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_repo(tmp_path: Path, source: str, manifest: dict[str, object] | None) -> Path:
    revision = ms.extract_revision(source)
    assert revision is not None
    _write(tmp_path, f"alembic/versions/{revision}_example.py", source)
    if manifest is not None:
        _write(
            tmp_path,
            f"alembic/preflight/{revision}.json",
            json.dumps(manifest),
        )
    (tmp_path / "app").mkdir(exist_ok=True)
    return tmp_path


def test_extract_revision_handles_typed_and_plain_forms() -> None:
    assert ms.extract_revision(UNIQUE_MIGRATION) == "a1b2c3d4e5f6"
    assert ms.extract_revision(DATA_MIGRATION) == "b2c3d4e5f6a7"
    assert ms.extract_revision("no revision here") is None


def test_classify_unique_constraint_ops() -> None:
    assert ms.classify_migration(UNIQUE_MIGRATION).risks == {"unique-constraint"}
    assert ms.classify_migration(UNIQUE_RAW_SQL).risks == {"unique-constraint"}


def test_classify_data_migration() -> None:
    assert ms.classify_migration(DATA_MIGRATION).risks == {"data-migration"}


def test_classify_destructive_extracts_target() -> None:
    risk = ms.classify_migration(DESTRUCTIVE_MIGRATION)
    assert risk.risks == {"destructive"}
    assert risk.dropped_targets == [("threads", "legacy_format")]


def test_classify_safe_migration_has_no_risk() -> None:
    assert ms.classify_migration(SAFE_MIGRATION).risks == set()


def test_select_only_guard_accepts_single_select() -> None:
    ms.require_select_only("SELECT count(*) FROM threads;")
    ms.require_select_only("  with x as (select 1) select * from x  ")


def test_select_only_guard_rejects_writes_and_multi_statements() -> None:
    with pytest.raises(ValueError):
        ms.require_select_only("UPDATE threads SET format = 'x'")
    with pytest.raises(ValueError):
        ms.require_select_only("SELECT 1; DROP TABLE threads")
    with pytest.raises(ValueError):
        ms.require_select_only("DELETE FROM threads")


@pytest.mark.parametrize(
    ("operator", "actual", "value", "expected"),
    [
        ("equals", 0, 0, True),
        ("equals", 1, 0, False),
        ("not-equals", 3, 0, True),
        ("less-than", 2, 3, True),
        ("less-than-or-equal", 3, 3, True),
        ("greater-than", 4, 3, True),
        ("greater-than-or-equal", 3, 3, True),
        ("greater-than-or-equal", 2, 3, False),
    ],
)
def test_evaluate_expectation(
    operator: str, actual: float, value: float, expected: bool
) -> None:
    expect = ms.Expectation.model_validate({"operator": operator, "value": value})
    assert ms.evaluate_expectation(actual, expect) is expected


def test_execute_preflight_checks_pass_and_fail() -> None:
    manifest = _unique_manifest()
    checks = ms.MigrationManifest.model_validate(manifest).preflight_checks
    assert ms.execute_preflight_checks(checks, lambda _sql: 0.0) == []
    violations = ms.execute_preflight_checks(checks, lambda _sql: 2.0)
    assert len(violations) == 1
    assert "MIGRATION PREFLIGHT FAILED" in violations[0]
    assert "no duplicates" in violations[0]


def test_risky_migration_without_manifest_is_blocked(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, UNIQUE_MIGRATION, None)
    violations = ms.validate_migration_static(
        Path("alembic/versions/a1b2c3d4e5f6_example.py"), repo
    )
    assert violations
    assert "preflight manifest" in violations[0]


def test_unique_migration_with_manifest_is_allowed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, UNIQUE_MIGRATION, _unique_manifest())
    violations = ms.validate_migration_static(
        Path("alembic/versions/a1b2c3d4e5f6_example.py"), repo
    )
    assert violations == []


def test_uniqueness_manifest_requires_preflight_checks(tmp_path: Path) -> None:
    manifest = _unique_manifest()
    manifest["preflight_checks"] = []
    repo = _make_repo(tmp_path, UNIQUE_MIGRATION, manifest)
    violations = ms.validate_migration_static(
        Path("alembic/versions/a1b2c3d4e5f6_example.py"), repo
    )
    assert any("at least one preflight check" in violation for violation in violations)


def test_manifest_risks_must_match_detected_risks(tmp_path: Path) -> None:
    manifest = _unique_manifest()
    manifest["risks"] = ["data-migration"]
    manifest["data_migration"] = {
        "idempotent": True,
        "dry_run_sql": "SELECT count(*) FROM threads",
    }
    repo = _make_repo(tmp_path, UNIQUE_MIGRATION, manifest)
    violations = ms.validate_migration_static(
        Path("alembic/versions/a1b2c3d4e5f6_example.py"), repo
    )
    assert any("do not match" in violation for violation in violations)


def test_data_migration_requires_idempotency_evidence(tmp_path: Path) -> None:
    manifest: dict[str, object] = {
        "revision": "b2c3d4e5f6a7",
        "summary": "backfill format",
        "risks": ["data-migration"],
        "data_migration": {
            "idempotent": False,
            "dry_run_sql": "SELECT count(*) FROM threads WHERE format IS NULL",
        },
    }
    repo = _make_repo(tmp_path, DATA_MIGRATION, manifest)
    violations = ms.validate_migration_static(
        Path("alembic/versions/b2c3d4e5f6a7_example.py"), repo
    )
    assert any("idempotent" in violation for violation in violations)


def test_destructive_migration_blocked_while_app_references_column(tmp_path: Path) -> None:
    manifest: dict[str, object] = {
        "revision": "d4e5f6a7b8c9",
        "summary": "drop legacy format column",
        "risks": ["destructive"],
        "destructive": {"target": "threads.legacy_format", "contract_issue": 3035},
    }
    repo = _make_repo(tmp_path, DESTRUCTIVE_MIGRATION, manifest)
    _write(repo, "app/models/thread.py", "legacy_format = Column(String)\n")
    violations = ms.sweep_manifests(repo)
    assert any("still references the column" in violation for violation in violations)


def test_destructive_migration_allowed_after_app_stops_using_column(
    tmp_path: Path,
) -> None:
    manifest: dict[str, object] = {
        "revision": "d4e5f6a7b8c9",
        "summary": "drop legacy format column",
        "risks": ["destructive"],
        "destructive": {"target": "threads.legacy_format", "contract_issue": 3035},
    }
    repo = _make_repo(tmp_path, DESTRUCTIVE_MIGRATION, manifest)
    _write(repo, "app/models/thread.py", "title = Column(String)\n")
    assert ms.sweep_manifests(repo) == []


def test_sweep_rejects_manifest_without_migration(tmp_path: Path) -> None:
    (tmp_path / "alembic" / "versions").mkdir(parents=True)
    (tmp_path / "app").mkdir()
    manifest = _unique_manifest()
    _write(
        tmp_path,
        "alembic/preflight/a1b2c3d4e5f6.json",
        json.dumps(manifest),
    )
    violations = ms.sweep_manifests(tmp_path)
    assert any("no migration file found" in violation for violation in violations)


def test_to_psycopg_url_normalizes_driver_prefixes() -> None:
    assert (
        ms.to_psycopg_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql://u:p@h/db"
    )
    assert (
        ms.to_psycopg_url("postgresql+psycopg://u:p@h/db")
        == "postgresql://u:p@h/db"
    )
    assert ms.to_psycopg_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_detect_changed_migrations_filters_versions(tmp_path: Path) -> None:
    # Use a real temporary git repository so the diff path is exercised.
    import subprocess

    def git(*argv: str) -> None:
        subprocess.run(["git", *argv], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    _write(tmp_path, "alembic/versions/base_one.py", SAFE_MIGRATION)
    _write(tmp_path, "app/keep.py", "x = 1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    _write(tmp_path, "alembic/versions/new_one.py", UNIQUE_MIGRATION)
    _write(tmp_path, "app/keep.py", "x = 2\n")
    git("add", ".")
    git("commit", "-qm", "change")
    changed = ms.detect_changed_migrations("HEAD~1", "HEAD", tmp_path)
    assert changed == [Path("alembic/versions/new_one.py")]
