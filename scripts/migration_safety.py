"""Fail-closed safety gates for risky Alembic migrations (issue #3053).

Two machine-enforced gates keep production delivery autonomous while blocking
unsafe migrations before they touch production data:

* ``check`` — a static pull-request gate. Migrations changed between two refs
  are classified by risk. Constraint, data, and destructive migrations must
  ship a companion manifest under ``alembic/preflight/<revision>.json`` that
  encodes the deterministic preflight/audit evidence for that migration.
* ``preflight`` — a read-only production gate run by ``deploy-production.yml``
  immediately before ``alembic upgrade head``. Every pending migration with a
  manifest has its preflight checks executed inside a read-only transaction;
  any violated precondition fails the deploy before any migration runs, leaving
  production unchanged.

See ``docs/MIGRATION_SAFETY.md`` for the full policy and manifest schema.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RISK_UNIQUE_CONSTRAINT = "unique-constraint"
RISK_DATA_MIGRATION = "data-migration"
RISK_DESTRUCTIVE = "destructive"

RiskName = Literal["unique-constraint", "data-migration", "destructive"]

MIGRATIONS_DIR = Path("alembic") / "versions"
PREFLIGHT_DIR = Path("alembic") / "preflight"

_COMPARE_OPS: dict[str, Callable[[float, float], bool]] = {
    "equals": lambda actual, expected: actual == expected,
    "not-equals": lambda actual, expected: actual != expected,
    "less-than": lambda actual, expected: actual < expected,
    "less-than-or-equal": lambda actual, expected: actual <= expected,
    "greater-than": lambda actual, expected: actual > expected,
    "greater-than-or-equal": lambda actual, expected: actual >= expected,
}


class Expectation(BaseModel):
    """Expected scalar result of a preflight check query."""

    operator: Literal[
        "equals",
        "not-equals",
        "less-than",
        "less-than-or-equal",
        "greater-than",
        "greater-than-or-equal",
    ]
    value: int | float


class PreflightCheck(BaseModel):
    """One deterministic read-only precondition for a migration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    expect: Expectation


class DataMigrationEvidence(BaseModel):
    """Idempotency and dry-run evidence for a data migration."""

    model_config = ConfigDict(extra="forbid")

    idempotent: bool
    dry_run_sql: str = Field(min_length=1)
    reconciliation_sql: str | None = None
    restart_notes: str | None = None


class DestructiveEvidence(BaseModel):
    """Expand/contract evidence for a destructive schema change."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1)
    contract_issue: int = Field(gt=0)


class MigrationManifest(BaseModel):
    """Schema for ``alembic/preflight/<revision>.json`` manifests."""

    model_config = ConfigDict(extra="forbid")

    revision: str = Field(pattern=r"^[0-9a-z_]+$")
    summary: str = Field(min_length=1)
    risks: list[RiskName]
    preflight_checks: list[PreflightCheck] = Field(default_factory=list)
    data_migration: DataMigrationEvidence | None = None
    destructive: DestructiveEvidence | None = None


class MigrationRisk(BaseModel):
    """Static risk classification of a migration source file."""

    risks: set[RiskName]
    dropped_targets: list[tuple[str, str]]


_REVISION_RE = re.compile(r"""^revision(?::\s*str)?\s*=\s*["']([0-9a-z_]+)["']""")
_UNIQUE_OP_RE = re.compile(r"\bop\.create_unique_constraint\s*\(")
_UNIQUE_FLAG_RE = re.compile(r"\bunique\s*=\s*True")
_DROP_COLUMN_RE = re.compile(r"""op\.drop_column\s*\(\s*["'](\w+)["']\s*,\s*["'](\w+)["']""")
_DROP_TABLE_RE = re.compile(r"""\bop\.drop_table\s*\(\s*["'](\w+)["']""")
_EXECUTE_RE = re.compile(r"""\bop\.(?:execute|bulk_insert)\s*\(\s*(?:sa\.text\s*\()?\s*["']{1,3}""")
_DATA_SQL_RE = re.compile(
    r"""\bop\.execute\s*\(\s*(?:sa\.text\s*\()?\s*["']{1,3}\s*(insert|update|delete|truncate|merge)\b""",
    re.IGNORECASE,
)
_UNIQUE_SQL_RE = re.compile(
    r"""\bop\.execute\s*\(\s*(?:sa\.text\s*\()?\s*["']{1,3}\s*create\s+unique""",
    re.IGNORECASE,
)


def extract_revision(source: str) -> str | None:
    """Return the Alembic revision id declared by a migration module.

    Args:
        source: Migration module source text.

    Returns:
        The revision id, or None when the module does not declare one.
    """
    for line in source.splitlines():
        match = _REVISION_RE.match(line)
        if match:
            return match.group(1)
    return None


def classify_migration(source: str) -> MigrationRisk:
    """Classify a migration module's risk surface from its source text.

    Args:
        source: Migration module source text.

    Returns:
        The detected risk classes and any dropped (table, column) targets.
    """
    risks: set[RiskName] = set()
    dropped_targets: list[tuple[str, str]] = []

    if _UNIQUE_OP_RE.search(source) or _UNIQUE_FLAG_RE.search(source) or _UNIQUE_SQL_RE.search(source):
        risks.add(RISK_UNIQUE_CONSTRAINT)
    if _DATA_SQL_RE.search(source) or "op.bulk_insert(" in source:
        risks.add(RISK_DATA_MIGRATION)
    for table, column in _DROP_COLUMN_RE.findall(source):
        risks.add(RISK_DESTRUCTIVE)
        dropped_targets.append((table, column))
    if _DROP_TABLE_RE.search(source):
        risks.add(RISK_DESTRUCTIVE)

    return MigrationRisk(risks=risks, dropped_targets=dropped_targets)


def manifest_path(preflight_dir: Path, revision: str) -> Path:
    """Return the manifest path for a revision.

    Args:
        preflight_dir: Directory containing preflight manifests.
        revision: Alembic revision id.

    Returns:
        Path of ``<preflight_dir>/<revision>.json``.
    """
    return preflight_dir / f"{revision}.json"


def load_manifest(path: Path) -> MigrationManifest:
    """Load and schema-validate one preflight manifest.

    Args:
        path: Manifest JSON path.

    Returns:
        The validated manifest.

    Raises:
        ValueError: When the manifest is unreadable or schema-invalid.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        return MigrationManifest.model_validate(json.loads(raw))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid preflight manifest {path}: {error}") from error


def require_select_only(sql: str) -> None:
    """Reject any SQL that is not a single read-only SELECT statement.

    Args:
        sql: SQL text used in a preflight or dry-run query.

    Raises:
        ValueError: When the SQL is not a single SELECT statement.
    """
    normalized = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^\s*select\b|^\s*with\b", normalized):
        raise ValueError(f"preflight SQL must be a read-only SELECT: {sql!r}")
    if ";" in normalized:
        raise ValueError(f"preflight SQL must be a single statement: {sql!r}")


def evaluate_expectation(actual: float, expect: Expectation) -> bool:
    """Evaluate a scalar result against an expectation.

    Args:
        actual: Scalar value returned by the preflight query.
        expect: Expected comparison.

    Returns:
        True when the precondition holds.
    """
    return _COMPARE_OPS[expect.operator](actual, float(expect.value))


def execute_preflight_checks(
    checks: Sequence[PreflightCheck],
    fetch_scalar: Callable[[str], float],
) -> list[str]:
    """Execute preflight checks against a scalar-fetching executor.

    Args:
        checks: Validated preflight checks to execute in order.
        fetch_scalar: Callable executing a SELECT and returning one scalar.

    Returns:
        Violated precondition descriptions, empty when every check passes.
    """
    violations: list[str] = []
    for check in checks:
        require_select_only(check.sql)
        actual = float(fetch_scalar(check.sql))
        if not evaluate_expectation(actual, check.expect):
            violations.append(
                f"MIGRATION PREFLIGHT FAILED: check {check.name!r} violated precondition "
                f"{check.condition!r} (actual={actual}, expected "
                f"{check.expect.operator} {check.expect.value})"
            )
    return violations


def find_app_references(column: str, app_dir: Path) -> list[str]:
    """Find application-code references to a column slated for removal.

    Args:
        column: Bare column name being dropped.
        app_dir: Application package directory scanned for references.

    Returns:
        ``file:line`` strings for every word-boundary match in app code.
    """
    pattern = re.compile(rf"\b{re.escape(column)}\b")
    hits: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path}:{number}")
    return hits


def detect_changed_migrations(base: str, head: str, repo_root: Path) -> list[Path]:
    """List migration files added or modified between two git refs.

    Args:
        base: Base git ref.
        head: Head git ref.
        repo_root: Repository root used as the git working directory.

    Returns:
        Repo-relative paths of changed files under ``alembic/versions``.
    """
    proc = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=AMR",
            f"{base}...{head}",
            "--",
            str(MIGRATIONS_DIR),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        Path(line)
        for line in proc.stdout.splitlines()
        if line.endswith(".py") and "versions" in line
    ]


def _validate_manifest_risks(
    manifest: MigrationManifest,
    risk: MigrationRisk,
    label: str,
) -> list[str]:
    """Validate a manifest covers the static risks of its migration.

    Args:
        manifest: The validated manifest for the migration revision.
        risk: Static classification of the migration source.
        label: Human label used in violation messages.

    Returns:
        Violation descriptions, empty when the manifest fully covers the risk.
    """
    violations: list[str] = []
    if sorted(set(manifest.risks)) != sorted(risk.risks):
        violations.append(
            f"{label}: manifest risks {sorted(manifest.risks)} do not match the "
            f"migration's detected risks {sorted(risk.risks)}"
        )
    if RISK_UNIQUE_CONSTRAINT in risk.risks and not manifest.preflight_checks:
        violations.append(
            f"{label}: uniqueness migrations must encode at least one preflight "
            "check proving existing rows satisfy the new invariant"
        )
    if RISK_DATA_MIGRATION in risk.risks and manifest.data_migration is None:
        violations.append(
            f"{label}: data migrations must encode idempotency and dry-run "
            "evidence in the manifest's data_migration section"
        )
    if manifest.data_migration is not None and not manifest.data_migration.idempotent:
        violations.append(f"{label}: data migrations must be idempotent/restartable")
    if RISK_DESTRUCTIVE in risk.risks and manifest.destructive is None:
        violations.append(
            f"{label}: destructive migrations must declare expand/contract "
            "evidence in the manifest's destructive section"
        )
    return violations


def validate_migration_static(
    migration_file: Path,
    repo_root: Path,
) -> list[str]:
    """Validate one migration file's safety manifest coverage.

    Args:
        migration_file: Repo-relative migration path.
        repo_root: Repository root.

    Returns:
        Violation descriptions, empty when the migration is gated correctly.
    """
    source = (repo_root / migration_file).read_text(encoding="utf-8")
    revision = extract_revision(source)
    label = str(migration_file)
    if revision is None:
        return [f"{label}: cannot determine the Alembic revision id"]

    risk = classify_migration(source)
    violations: list[str] = []

    path = repo_root / manifest_path(PREFLIGHT_DIR, revision)
    if not risk.risks:
        if path.exists():
            violations.extend(_validate_manifest(risk, load_manifest(path), label, revision))
        return violations
    if not path.exists():
        return [
            f"{label}: risky migration ({', '.join(sorted(risk.risks))}) requires a "
            f"preflight manifest at {manifest_path(PREFLIGHT_DIR, revision)}"
        ]
    manifest = load_manifest(path)
    violations.extend(_validate_manifest(risk, manifest, label, revision))
    return violations


def _validate_manifest(
    risk: MigrationRisk,
    manifest: MigrationManifest,
    label: str,
    revision: str,
    repo_root: Path | None = None,
) -> list[str]:
    """Validate manifest internals shared by changed-migration and sweep paths.

    Args:
        risk: Static classification of the migration source.
        manifest: Validated manifest.
        label: Human label for violation messages.
        revision: Expected revision id.
        repo_root: When provided, run the destructive app-reference scan.

    Returns:
        Violation descriptions.
    """
    violations: list[str] = []
    if manifest.revision != revision:
        violations.append(
            f"{label}: manifest revision {manifest.revision!r} does not match "
            f"the migration revision {revision!r}"
        )
    violations.extend(_validate_manifest_risks(manifest, risk, label))
    for check in manifest.preflight_checks:
        try:
            require_select_only(check.sql)
        except ValueError as error:
            violations.append(f"{label}: {error}")
    if manifest.data_migration is not None:
        try:
            require_select_only(manifest.data_migration.dry_run_sql)
        except ValueError as error:
            violations.append(f"{label}: {error}")
        if manifest.data_migration.reconciliation_sql is not None:
            try:
                require_select_only(manifest.data_migration.reconciliation_sql)
            except ValueError as error:
                violations.append(f"{label}: {error}")
    if repo_root is not None and manifest.destructive is not None:
        target = manifest.destructive.target
        if "." not in target:
            violations.append(
                f"{label}: destructive target {target!r} must be in 'table.column' form"
            )
        else:
            column = target.rsplit(".", 1)[1]
            hits = find_app_references(column, repo_root / "app")
            if hits:
                sample = ", ".join(hits[:5])
                more = f" and {len(hits) - 5} more" if len(hits) > 5 else ""
                violations.append(
                    f"{label}: destructive migration drops {target!r} but application "
                    f"code still references the column ({sample}{more}); expand/contract "
                    "requires the application to stop depending on the old shape first"
                )
    return violations


def sweep_manifests(repo_root: Path) -> list[str]:
    """Validate every manifest against its migration and the application tree.

    Args:
        repo_root: Repository root.

    Returns:
        Violation descriptions for all stored manifests.
    """
    violations: list[str] = []
    for path in sorted((repo_root / PREFLIGHT_DIR).glob("*.json")):
        manifest = load_manifest(path)
        migration_file = repo_root / MIGRATIONS_DIR
        candidates = sorted(migration_file.glob(f"{manifest.revision}_*.py"))
        if not candidates:
            violations.append(
                f"{path}: no migration file found for revision {manifest.revision!r}"
            )
            continue
        source = candidates[0].read_text(encoding="utf-8")
        risk = classify_migration(source)
        violations.extend(
            _validate_manifest(risk, manifest, str(path), manifest.revision, repo_root)
        )
    return violations


def to_psycopg_url(db_url: str) -> str:
    """Normalize a database URL for the synchronous psycopg driver.

    Args:
        db_url: Database URL, possibly driver-qualified.

    Returns:
        A bare ``postgresql://`` URL psycopg accepts.
    """
    url = db_url.strip()
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _applied_revisions(fetch_scalar: Callable[[str], object]) -> set[str]:
    """Read the set of applied Alembic revisions from the target database.

    Args:
        fetch_scalar: Callable returning rows for a query.

    Returns:
        Applied revision ids, or empty when alembic_version does not exist.
    """
    rows = fetch_scalar("select version_num from alembic_version")
    if not isinstance(rows, list):
        return set()
    return {str(row[0]) for row in rows}


def run_preflight(db_url: str, repo_root: Path, pending_only: bool = True) -> list[str]:
    """Run read-only preflight checks against the target database.

    Args:
        db_url: Target database URL (production in the deploy workflow).
        repo_root: Repository root containing ``alembic/preflight``.
        pending_only: Skip manifests whose revision is already applied.

    Returns:
        Violated precondition descriptions, empty when deployment may proceed.
    """
    import psycopg

    violations: list[str] = []
    manifests: list[MigrationManifest] = []
    for path in sorted((repo_root / PREFLIGHT_DIR).glob("*.json")):
        try:
            manifests.append(load_manifest(path))
        except ValueError as error:
            violations.append(str(error))
    if violations:
        return violations

    with psycopg.connect(to_psycopg_url(db_url), autocommit=False) as conn:
        conn.execute("SET default_transaction_read_only = on")

        def fetch_scalar(sql: str) -> float:
            row = conn.execute(sql).fetchone()
            if row is None:
                raise ValueError(f"preflight query returned no rows: {sql!r}")
            return float(row[0])

        applied: set[str] = set()
        if pending_only:
            try:
                rows = conn.execute("select version_num from alembic_version").fetchall()
                applied = {str(row[0]) for row in rows}
            except psycopg.errors.UndefinedTable:
                conn.rollback()
                applied = set()

        for manifest in manifests:
            if pending_only and manifest.revision in applied:
                continue
            print(f"Running preflight for migration {manifest.revision}: {manifest.summary}")
            violations.extend(execute_preflight_checks(manifest.preflight_checks, fetch_scalar))
            if manifest.data_migration is not None:
                dry_run = fetch_scalar(manifest.data_migration.dry_run_sql)
                print(
                    f"Data migration {manifest.revision} dry-run evidence: "
                    f"rows-affected={dry_run:g}"
                )
                if manifest.data_migration.reconciliation_sql is not None:
                    remaining = fetch_scalar(manifest.data_migration.reconciliation_sql)
                    print(
                        f"Data migration {manifest.revision} reconciliation evidence: "
                        f"unreconciled={remaining:g}"
                    )
    return violations


def _cmd_check(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    violations: list[str] = []
    if args.base:
        changed = detect_changed_migrations(args.base, args.head, repo_root)
        if not changed:
            print("No migration files changed; migration safety gate is not engaged.")
        for migration_file in changed:
            violations.extend(validate_migration_static(migration_file, repo_root))
    violations.extend(sweep_manifests(repo_root))
    for violation in violations:
        print(f"::error::{violation}")
    if violations:
        print(f"Migration safety static gate FAILED with {len(violations)} violation(s).")
        return 1
    print("Migration safety static gate passed.")
    return 0


def _cmd_preflight(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    violations = run_preflight(args.db_url, repo_root, pending_only=not args.all)
    for violation in violations:
        print(f"::error::{violation}")
    if violations:
        print(
            f"MIGRATION PREFLIGHT FAILED with {len(violations)} violated precondition(s). "
            "Deploy is blocked BEFORE any migration runs; production is unchanged."
        )
        return 1
    print("Migration preflight passed; production data satisfies every precondition.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the migration safety gate CLI.

    Args:
        argv: Optional argument vector; defaults to ``sys.argv``.

    Returns:
        Process exit code: 0 when gates pass, 1 on any violated precondition.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Static merge-readiness gate for migration changes")
    check.add_argument("--base", default=None, help="Base git ref for the pull request")
    check.add_argument("--head", default="HEAD", help="Head git ref")
    check.add_argument("--repo", default=".", help="Repository root")
    check.set_defaults(func=_cmd_check)

    preflight = sub.add_parser(
        "preflight", help="Read-only production preflight before alembic upgrade"
    )
    preflight.add_argument("--db-url", required=True, help="Target database URL")
    preflight.add_argument("--repo", default=".", help="Repository root")
    preflight.add_argument(
        "--all",
        action="store_true",
        help="Run every manifest, not only pending revisions",
    )
    preflight.set_defaults(func=_cmd_preflight)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
