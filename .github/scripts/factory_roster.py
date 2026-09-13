#!/usr/bin/env python3
"""Shared factory roster I/O, free-pin rules, and expected-worker lock.

The TSV at ``.github/free-model-factories.tsv`` is the live pin list.
``.github/factory-expected-workers.json`` is the generated lock the validator
compares against so retiring a pin updates both files together instead of
hand-editing ``EXPECTED_WORKERS``.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TypedDict

ROSTER_FIELDNAMES = (
    "worker",
    "source",
    "model",
    "minute",
    "scheduler",
    "display_name",
)
SCHEDULE_MINUTES = tuple(range(0, 60, 5))
OPENCODE_ALWAYS_FREE = frozenset({"big-pickle"})
OPENCODE_MUSE_SPARK_RE = re.compile(r"muse-spark", re.IGNORECASE)
CATALOG_SOURCES = frozenset({"opencode-free", "nvidia", "openrouter-free"})
PROTECTED_SOURCES = frozenset({"kilo-auto"})
LOCK_SCHEMA_VERSION = 1


class RosterRow(TypedDict):
    """One fixed-model factory roster row."""

    worker: str
    source: str
    model: str
    minute: str
    scheduler: str
    display_name: str


class RosterLock(TypedDict):
    """Generated expected-worker lock kept in sync by retirement apply."""

    schema_version: int
    expected_workers: list[int]
    retired_workers: list[int]
    retired_models: list[str]


def _repo_root() -> Path:
    """Return the repository root that contains ``.github/``."""
    return Path(__file__).resolve().parents[2]


def default_roster_path() -> Path:
    """Return the factory TSV, preferring a cwd-relative checkout path."""
    cwd = Path(".github/free-model-factories.tsv")
    if cwd.is_file():
        return cwd
    return _repo_root() / ".github" / "free-model-factories.tsv"


def default_lock_path() -> Path:
    """Return the expected-worker lock path."""
    cwd = Path(".github/factory-expected-workers.json")
    if cwd.is_file() or cwd.parent.is_dir():
        return cwd
    return _repo_root() / ".github" / "factory-expected-workers.json"


def opencode_model_is_free(model: str) -> bool:
    """Return whether an OpenCode lane pin is a free-roster model id.

    Args:
        model: Bare OpenCode model id (no ``opencode/`` prefix).

    Returns:
        True for ``big-pickle``, ``*-free``, or muse-spark free/contributor ids.
    """
    name = model.strip().lower()
    if not name or "/" in name:
        return False
    return (
        name in OPENCODE_ALWAYS_FREE
        or name.endswith("-free")
        or bool(OPENCODE_MUSE_SPARK_RE.search(name))
    )


def openrouter_model_is_free(model: str) -> bool:
    """Return whether an OpenRouter lane pin is an explicit free-tier model id.

    Args:
        model: OpenRouter model id.

    Returns:
        True for ``*:free`` ids or the ``openrouter/free`` auto-router.
    """
    name = model.strip()
    if name == "openrouter/free":
        return True
    return bool(name) and name.endswith(":free") and "/" in name


def load_roster_rows(path: Path | None = None) -> list[RosterRow]:
    """Load non-comment roster rows from the factory TSV.

    Args:
        path: Optional TSV path. Defaults to :func:`default_roster_path`.

    Returns:
        Roster rows in file order.
    """
    roster = path or default_roster_path()
    with roster.open(newline="", encoding="utf-8") as handle:
        rows = list(
            csv.DictReader(
                (
                    line
                    for line in handle
                    if line.strip() and not line.lstrip().startswith("#")
                ),
                fieldnames=list(ROSTER_FIELDNAMES),
                delimiter="\t",
            )
        )
    return [
        RosterRow(
            worker=str(row.get("worker") or "").strip(),
            source=str(row.get("source") or "").strip(),
            model=str(row.get("model") or "").strip(),
            minute=str(row.get("minute") or "").strip(),
            scheduler=str(row.get("scheduler") or "").strip(),
            display_name=str(row.get("display_name") or "").strip(),
        )
        for row in rows
        if str(row.get("worker") or "").strip()
    ]


def load_roster_comments(path: Path | None = None) -> list[str]:
    """Return leading ``#`` comment lines from the factory TSV."""
    roster = path or default_roster_path()
    comments: list[str] = []
    for line in roster.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            comments.append(line)
            continue
        if line.strip():
            break
    return comments


def write_roster_rows(
    path: Path,
    rows: Sequence[RosterRow],
    comments: Sequence[str] | None = None,
) -> None:
    """Write roster rows, preserving header comments when provided.

    Args:
        path: Destination TSV.
        rows: Rows to persist, written in worker-number order.
        comments: Optional comment lines to keep at the top of the file.
    """
    ordered = sorted(rows, key=lambda row: int(row["worker"]))
    lines = list(comments or [])
    for row in ordered:
        lines.append("\t".join(row[field] for field in ROSTER_FIELDNAMES))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def roster_worker_ids(rows: Sequence[Mapping[str, str]]) -> set[int]:
    """Return the integer worker ids present on the roster."""
    return {int(row["worker"]) for row in rows}


def schedule_counts(rows: Sequence[Mapping[str, str]]) -> Counter[int]:
    """Count roster rows per dispatcher minute."""
    counts: Counter[int] = Counter()
    for row in rows:
        counts[int(row["minute"])] += 1
    return counts


def schedule_is_balanced(rows: Sequence[Mapping[str, str]]) -> bool:
    """Return whether every schedule minute is used and load differs by at most 1."""
    counts = schedule_counts(rows)
    if set(counts) != set(SCHEDULE_MINUTES):
        return False
    return max(counts.values()) - min(counts.values()) <= 1


def empty_lock() -> RosterLock:
    """Return an empty lock document."""
    return RosterLock(
        schema_version=LOCK_SCHEMA_VERSION,
        expected_workers=[],
        retired_workers=[],
        retired_models=[],
    )


def load_roster_lock(path: Path | None = None) -> RosterLock:
    """Load the expected-worker lock, or an empty lock when the file is absent.

    Args:
        path: Optional lock path.

    Returns:
        Parsed lock document.
    """
    lock_path = path or default_lock_path()
    if not lock_path.is_file():
        return empty_lock()
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return empty_lock()
    expected = payload.get("expected_workers")
    retired_workers = payload.get("retired_workers")
    retired_models = payload.get("retired_models")
    return RosterLock(
        schema_version=int(payload.get("schema_version") or LOCK_SCHEMA_VERSION),
        expected_workers=[int(item) for item in expected] if isinstance(expected, list) else [],
        retired_workers=(
            [int(item) for item in retired_workers] if isinstance(retired_workers, list) else []
        ),
        retired_models=(
            [str(item) for item in retired_models] if isinstance(retired_models, list) else []
        ),
    )


def write_roster_lock(path: Path, lock: RosterLock) -> None:
    """Persist the expected-worker lock as stable JSON."""
    payload = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "expected_workers": sorted({int(item) for item in lock["expected_workers"]}),
        "retired_workers": sorted({int(item) for item in lock["retired_workers"]}),
        "retired_models": sorted({str(item) for item in lock["retired_models"]}),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def expected_workers(
    *,
    lock_path: Path | None = None,
    roster_path: Path | None = None,
) -> set[int]:
    """Return expected worker ids from the lock, falling back to the TSV.

    Args:
        lock_path: Optional lock path.
        roster_path: Optional TSV used only when the lock has no workers.

    Returns:
        Worker ids the validator must observe.
    """
    lock = load_roster_lock(lock_path)
    if lock["expected_workers"]:
        return set(lock["expected_workers"])
    return roster_worker_ids(load_roster_rows(roster_path))


def sync_roster_lock(
    rows: Sequence[RosterRow],
    *,
    lock_path: Path | None = None,
    extra_retired_workers: Iterable[int] = (),
    extra_retired_models: Iterable[str] = (),
) -> RosterLock:
    """Rewrite the lock from remaining rows plus accumulated retirements.

    Args:
        rows: Roster rows after retirement.
        lock_path: Destination lock. Defaults to :func:`default_lock_path`.
        extra_retired_workers: Worker ids removed in this apply.
        extra_retired_models: Model ids removed in this apply.

    Returns:
        The written lock document.
    """
    destination = lock_path or default_lock_path()
    previous = load_roster_lock(destination if destination.is_file() else None)
    lock = RosterLock(
        schema_version=LOCK_SCHEMA_VERSION,
        expected_workers=sorted(roster_worker_ids(rows)),
        retired_workers=sorted(
            set(previous["retired_workers"]) | {int(item) for item in extra_retired_workers}
        ),
        retired_models=sorted(
            set(previous["retired_models"])
            | {str(item).strip() for item in extra_retired_models if str(item).strip()}
        ),
    )
    write_roster_lock(destination, lock)
    return lock
