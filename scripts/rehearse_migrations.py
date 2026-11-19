#!/usr/bin/env python3
"""Rehearse Alembic migrations against a throwaway Postgres database.

Loads a checked-in prod-shaped fixture, then runs:
  1. alembic upgrade head (from the fixture's revision)
  2. alembic downgrade <base> (fixture revision, or PR base / -1 per new revision)
  3. alembic upgrade head

Never connects to Neon, production, or preview databases. Use an explicit
throwaway DATABASE_URL / MIGRATION_REHEARSAL_DATABASE_URL (or --database-url).

The fixture is a directory containing:
  - manifest.json: {"base_revision": "<alembic revision>", "description": "..."}
  - seed.sql: data/edge-case rows valid at base_revision (inserted after schema
    is migrated to base_revision)

"Fixture revision" means the Alembic revision the seed data is shaped for.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = REPO_ROOT / "tests/fixtures/migration_rehearsal/prod_shaped"


@dataclass(frozen=True)
class StepTiming:
    """Timing and outcome for one rehearsal step."""

    name: str
    seconds: float
    returncode: int


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def _run(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: Path = REPO_ROOT,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"+ {printable}", flush=True)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )


def _run_timed(
    name: str,
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: Path = REPO_ROOT,
) -> StepTiming:
    start = time.perf_counter()
    proc = _run(cmd, env=env, cwd=cwd)
    elapsed = time.perf_counter() - start
    timing = StepTiming(name=name, seconds=elapsed, returncode=proc.returncode)
    print(f"[rehearsal] {name}: {elapsed:.3f}s (rc={proc.returncode})", flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Step {name!r} failed with exit code {proc.returncode}")
    return timing


def _alembic_cmd() -> list[str]:
    override = os.getenv("ALEMBIC_BIN")
    if override:
        return shlex.split(override)
    venv = REPO_ROOT / ".venv/bin/alembic"
    if venv.is_file():
        return [str(venv)]
    return [sys.executable, "-m", "alembic"]


def _psql_env(url: str) -> tuple[dict[str, str], str]:
    """Return (env, libpq_url) for psql/pg_dump commands."""
    parsed = urlparse(url.replace("+asyncpg", "+psycopg").replace("+psycopg", ""))
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError(f"Unsupported database URL scheme for rehearsal: {parsed.scheme!r}")
    libpq = urlunparse(parsed._replace(scheme="postgresql"))
    env = os.environ.copy()
    env["PGCONNECT_TIMEOUT"] = env.get("PGCONNECT_TIMEOUT", "10")
    return env, libpq


def _is_forbidden_url(url: str) -> str | None:
    lowered = url.lower()
    host = (urlparse(lowered).hostname or "").lower()
    if "neon.tech" in host or "neon.build" in host:
        return "Neon/preview database URLs are forbidden for migration rehearsal"
    if "neondb_owner" in lowered or "neon_api_key" in lowered:
        return "Neon credential markers are forbidden for migration rehearsal"
    if os.getenv("NEON_API_KEY") and os.getenv("NEON_API_KEY") in url:
        return "NEON_API_KEY must not appear in rehearsal database URLs"
    return None


def _load_manifest(fixture_dir: Path) -> dict[str, str]:
    path = fixture_dir / "manifest.json"
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if "base_revision" not in data:
        raise ValueError(f"{path} missing base_revision")
    return data


def _reset_database(database_url: str) -> None:
    env, libpq = _psql_env(database_url)
    sql = (
        "DROP SCHEMA public CASCADE; CREATE SCHEMA public; "
        "GRANT ALL ON SCHEMA public TO CURRENT_USER; "
        "GRANT ALL ON SCHEMA public TO public;"
    )
    proc = _run(["psql", libpq, "-v", "ON_ERROR_STOP=1", "-c", sql], env=env)
    if proc.returncode != 0:
        raise RuntimeError("Failed to reset throwaway rehearsal database")


def _load_seed(database_url: str, fixture_dir: Path) -> None:
    seed = fixture_dir / "seed.sql"
    if not seed.is_file():
        raise FileNotFoundError(f"Fixture seed not found: {seed}")
    env, libpq = _psql_env(database_url)
    proc = _run(["psql", libpq, "-v", "ON_ERROR_STOP=1", "-f", str(seed)], env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to load fixture seed: {seed}")


def _alembic_heads(env: dict[str, str]) -> list[str]:
    proc = _run([*_alembic_cmd(), "heads"], env=env, capture=True)
    if proc.returncode != 0:
        raise RuntimeError("Failed to read Alembic heads")
    heads: list[str] = []
    for line in (proc.stdout or "").splitlines():
        match = re.match(r"^([0-9A-Za-z_]+)\s+\(head\)", line.strip())
        if match:
            heads.append(match.group(1))
    return heads


def _alembic_current(env: dict[str, str]) -> str | None:
    proc = _run([*_alembic_cmd(), "current"], env=env, capture=True)
    if proc.returncode != 0:
        raise RuntimeError("Failed to read Alembic current revision")
    for line in (proc.stdout or "").splitlines():
        token = line.strip().split()
        if token:
            return token[0]
    return None


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def _revision_from_migration_path(path: Path) -> str | None:
    """Best-effort revision ID from an Alembic migration filename."""
    name = path.name
    if not name.endswith(".py"):
        return None
    return name.split("_", 1)[0] if "_" in name else name[:-3]


def _down_revisions_in_file(path: Path) -> list[str]:
    """Parse down_revision identifiers from a migration file (best effort)."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    # Handles: down_revision = 'x', down_revision: str | None = "x",
    # down_revision = ('a', 'b') / None
    m = re.search(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", text, re.MULTILINE)
    if not m:
        return []
    expr = m.group(1).split("#", 1)[0].strip()
    if expr == "None":
        return []
    ids = re.findall(r"['\"]([A-Za-z0-9_]+)['\"]", expr)
    return ids


def _detect_pr_downgrade_base(base_ref: str | None) -> str | None:
    """Return Alembic downgrade target for migrations introduced vs base ref.

    If new migration files exist, return the down_revision of the earliest new
    migration in that set (base revision of the PR) when unambiguous.
    If no migration files changed, return None so caller can choose a safe
    rollback (e.g. -1) or current-head behavior.
    """
    if not base_ref:
        return None
    proc = _git(["diff", "--name-only", "--diff-filter=AMR", f"{base_ref}...HEAD", "--", "alembic/versions"])
    if proc.returncode != 0:
        return None
    added_paths = [REPO_ROOT / p.strip() for p in proc.stdout.splitlines() if p.strip().endswith(".py")]
    if not added_paths:
        return None
    added_revs = {r for p in added_paths if (r := _revision_from_migration_path(p))}
    if not added_revs:
        return None
    # Find down revisions that point outside the newly added set (PR base boundary).
    bases: set[str] = set()
    for path in added_paths:
        for down in _down_revisions_in_file(path):
            if down not in added_revs:
                bases.add(down)
    if len(bases) == 1:
        return next(iter(bases))
    # Fallback: downgrade by count of added migrations.
    return f"-{len(added_revs)}"


def _downgrade_target(
    *,
    fixture_revision: str,
    explicit_base: str | None,
    base_ref: str | None,
    step_down: int,
) -> str:
    if explicit_base:
        return explicit_base
    if step_down > 0:
        return f"-{step_down}"
    pr_base = _detect_pr_downgrade_base(base_ref)
    if pr_base is not None:
        return pr_base
    # No new migrations vs base_ref, or no base_ref context: step back one
    # revision to exercise rollback. Callers may pass --base/--downgrade-steps
    # for merge heads or known-safe targets.
    return "-1"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("MIGRATION_REHEARSAL_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="Throwaway Postgres URL (default: $MIGRATION_REHEARSAL_DATABASE_URL or $DATABASE_URL)",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=DEFAULT_FIXTURE_DIR,
        help=f"Fixture directory (default: {DEFAULT_FIXTURE_DIR})",
    )
    parser.add_argument(
        "--base",
        help="Alembic revision to downgrade to between upgrades (overrides defaults)",
    )
    parser.add_argument(
        "--base-ref",
        help="Git base ref/SHA for PR rehearsal context (downgrade defaults to fixture revision unless --base set)",
    )
    parser.add_argument(
        "--downgrade-steps",
        type=int,
        default=0,
        help="Use alembic downgrade -N instead of fixture/base/auto-detected revision",
    )
    parser.add_argument(
        "--skip-downgrade-cycle",
        action="store_true",
        help="Run upgrade-head from fixture only (skip downgrade/upgrade-again); use when downgrade target is known-irreversible in context",
    )
    parser.add_argument(
        "--skip-reset",
        action="store_true",
        help="Do not drop/recreate schema before loading fixture (fixture must be compatible)",
    )
    parser.add_argument(
        "--timing-json",
        type=Path,
        help="Write step timings and metadata as JSON",
    )
    parser.add_argument(
        "--print-metadata",
        action="store_true",
        help="Print fixture and rehearsal metadata",
    )
    parser.add_argument(
        "--migration-budget-seconds",
        type=float,
        default=float(os.getenv("MIGRATION_REHEARSAL_BUDGET_SECONDS", "300")),
        help="Fail if any upgrade step exceeds this budget (default: 300s or $MIGRATION_REHEARSAL_BUDGET_SECONDS)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the migration rehearsal."""
    args = _build_parser().parse_args(argv)
    if not args.database_url:
        _eprint("ERROR: --database-url or MIGRATION_REHEARSAL_DATABASE_URL/DATABASE_URL is required")
        return 2
    forbidden = _is_forbidden_url(args.database_url)
    if forbidden:
        _eprint(f"ERROR: {forbidden}")
        return 2

    fixture_dir = args.fixture_dir.resolve()
    manifest = _load_manifest(fixture_dir)
    fixture_revision = str(manifest["base_revision"])
    heads = _alembic_heads(os.environ.copy())
    head = heads[0] if len(heads) == 1 else None
    if args.print_metadata or True:
        print(
            json.dumps(
                {
                    "fixture_dir": str(fixture_dir),
                    "fixture_revision": fixture_revision,
                    "alembic_heads": heads,
                    "base_ref": args.base_ref,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    env = os.environ.copy()
    env["DATABASE_URL"] = args.database_url
    env.setdefault("TEST_ENVIRONMENT", "true")

    timings: list[StepTiming] = []
    try:
        if not args.skip_reset:
            _reset_database(args.database_url)
        # Bring schema to fixture revision, then load prod-shaped seed data.
        timings.append(
            _run_timed(
                "upgrade_to_fixture",
                [*_alembic_cmd(), "upgrade", fixture_revision],
                env=env,
            )
        )
        _load_seed(args.database_url, fixture_dir)
        timings.append(_run_timed("upgrade_head_1", [*_alembic_cmd(), "upgrade", "head"], env=env))
        if timings[-1].seconds > args.migration_budget_seconds:
            raise RuntimeError(
                f"upgrade_head_1 exceeded migration safety budget: "
                f"{timings[-1].seconds:.3f}s > {args.migration_budget_seconds:.3f}s"
            )
        if not args.skip_downgrade_cycle:
            downgrade_to = _downgrade_target(
                fixture_revision=fixture_revision,
                explicit_base=args.base,
                base_ref=args.base_ref,
                step_down=args.downgrade_steps,
            )
            print(f"[rehearsal] downgrade target: {downgrade_to}", flush=True)
            timings.append(_run_timed("downgrade", [*_alembic_cmd(), "downgrade", downgrade_to], env=env))
            timings.append(_run_timed("upgrade_head_2", [*_alembic_cmd(), "upgrade", "head"], env=env))
            if timings[-1].seconds > args.migration_budget_seconds:
                raise RuntimeError(
                    f"upgrade_head_2 exceeded migration safety budget: "
                    f"{timings[-1].seconds:.3f}s > {args.migration_budget_seconds:.3f}s"
                )
        current = _alembic_current(env)
        if head and current != head:
            raise RuntimeError(f"Expected Alembic head {head!r} after rehearsal, got {current!r}")
    except Exception as exc:
        _eprint(f"ERROR: {exc}")
        _write_timing(args.timing_json, fixture_revision, timings, ok=False, error=str(exc))
        return 1

    _write_timing(args.timing_json, fixture_revision, timings, ok=True, error=None)
    print(
        f"[rehearsal] OK fixture={fixture_revision} head={head or 'unknown'} "
        f"steps={len(timings)}",
        flush=True,
    )
    return 0


def _write_timing(
    path: Path | None,
    fixture_revision: str,
    timings: list[StepTiming],
    *,
    ok: bool,
    error: str | None,
) -> None:
    if path is None:
        return
    payload = {
        "ok": ok,
        "error": error,
        "fixture_revision": fixture_revision,
        "steps": [
            {"name": t.name, "seconds": t.seconds, "returncode": t.returncode} for t in timings
        ],
        "total_seconds": sum(t.seconds for t in timings),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
