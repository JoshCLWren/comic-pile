#!/usr/bin/env python3
"""Measure frontend/backend coupling in the ComicPile git history.

The script classifies each commit in a rolling window by which repository
surfaces it touches. The output feeds the repository-boundary decision
document for issue #640.

Classification rules:

* ``frontend_only`` — only files under ``frontend/`` change, excluding the
  generated OpenAPI artifacts (``frontend/src/generated/``).
* ``generated_only`` — only generated OpenAPI artifacts change. These are
  mechanical regeneration commits that follow a backend change and are
  treated as a single coupled change with the backend commit that
  triggered them.
* ``backend_only`` — only files under ``app/``, ``api/``, or
  ``comic_pile/`` change.
* ``both_dirs`` — both frontend and backend surfaces change in the same
  commit.
* ``infra_only`` — only files under ``.github/``, ``.githooks/``,
  ``Makefile``, ``pyproject.toml``, ``package.json``, ``uv.lock``,
  ``pnpm-lock.yaml``, ``alembic/``, ``scripts/``, ``tests/``,
  ``tests_e2e/``, ``static/``, or workflow/CI YAML files change.
* ``docs_only`` — only Markdown documentation changes.
* ``other`` — anything else (typically the first commit of a brand new
  surface, image-only changes, or merge commits).

The classification is reproducible so the decision document can be
regenerated at any time and compared against the original snapshot.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FRONTEND_PREFIX = "frontend/"
FRONTEND_GENERATED_PREFIX = "frontend/src/generated/"
BACKEND_PREFIXES = ("app/", "api/", "comic_pile/")
INFRA_FILES = {
    ".github/",
    ".githooks/",
    "Makefile",
    "pyproject.toml",
    "package.json",
    "uv.lock",
    "pnpm-lock.yaml",
    "alembic/",
    "scripts/",
    "tests/",
    "tests_e2e/",
    "static/",
}
DOCS_PREFIX = "docs/"
DOCS_SUFFIX = ".md"

MONTHS_RE = re.compile(r"^(\d+)\s+months?\s+ago$")


@dataclass(frozen=True)
class CommitClassification:
    """Single commit classification record."""

    sha: str
    subject: str
    surfaces: tuple[str, ...]
    file_count: int


def _git(*args: str) -> str:
    """Run a git command from the repository root and return stdout.

    Args:
        args: Arguments passed to ``git``.

    Returns:
        Command stdout with trailing whitespace stripped.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _list_commits(months: int) -> list[str]:
    """Return the SHAs of commits within the requested rolling window.

    Args:
        months: Number of months back from ``HEAD`` to include.

    Returns:
        Commit SHAs in newest-first order.
    """
    since = f"{months} months ago"
    output = _git("log", f"--since={since}", "--pretty=format:%H")
    return [line for line in output.splitlines() if line]


def _commit_files(sha: str) -> list[str]:
    """Return the files touched by a commit.

    Args:
        sha: Commit SHA.

    Returns:
        File paths relative to the repository root.
    """
    output = _git("show", "--name-only", "--pretty=format:", sha)
    return [line for line in output.splitlines() if line]


def _classify(paths: list[str]) -> tuple[str, ...]:
    """Classify the touched surfaces for a single commit.

    Args:
        paths: File paths touched by the commit.

    Returns:
        Sorted tuple of surface labels.
    """
    surfaces: set[str] = set()
    for path in paths:
        if path.startswith(FRONTEND_GENERATED_PREFIX):
            surfaces.add("generated")
        elif path.startswith(FRONTEND_PREFIX):
            surfaces.add("frontend")
        elif any(path.startswith(prefix) for prefix in BACKEND_PREFIXES):
            surfaces.add("backend")
        elif (
            path.startswith(DOCS_PREFIX)
            or path.endswith(DOCS_SUFFIX)
            or path == "README.md"
            or path == "AGENTS.md"
        ):
            surfaces.add("docs")
        elif (
            path in INFRA_FILES
            or any(path.startswith(p) for p in INFRA_FILES if p.endswith("/"))
            or path.endswith((".yml", ".yaml"))
        ):
            surfaces.add("infra")
        else:
            surfaces.add("other")
    return tuple(sorted(surfaces))


def _label_for(surfaces: tuple[str, ...]) -> str:
    """Map a surface set to a human-readable bucket label.

    Args:
        surfaces: Sorted tuple of surface labels.

    Returns:
        Bucket label.
    """
    has_frontend = "frontend" in surfaces or "generated" in surfaces
    has_backend = "backend" in surfaces
    only_generated = surfaces == ("generated",)
    if has_frontend and has_backend:
        return "both_dirs"
    if only_generated:
        return "generated_only"
    if has_frontend:
        return "frontend_only"
    if has_backend:
        return "backend_only"
    if "infra" in surfaces and "docs" not in surfaces:
        return "infra_only"
    if "docs" in surfaces and len(surfaces) == 1:
        return "docs_only"
    return "other"


@dataclass(frozen=True)
class CouplingReport:
    """Aggregated coupling report for one measurement window."""

    months: int
    total_commits: int
    counts: dict[str, int]
    percent: dict[str, float]
    sample_both_dirs: tuple[CommitClassification, ...]
    sample_frontend_only: tuple[CommitClassification, ...]
    sample_backend_only: tuple[CommitClassification, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dictionary representation.

        Returns:
            Dictionary with primitive types only.
        """
        return {
            "months": self.months,
            "total_commits": self.total_commits,
            "counts": dict(self.counts),
            "percent": dict(self.percent),
            "sample_both_dirs": [asdict(c) for c in self.sample_both_dirs],
            "sample_frontend_only": [asdict(c) for c in self.sample_frontend_only],
            "sample_backend_only": [asdict(c) for c in self.sample_backend_only],
        }


def measure(months: int) -> CouplingReport:
    """Build a coupling report for the requested rolling window.

    Args:
        months: Number of months back from ``HEAD`` to include.

    Returns:
        Aggregated report.
    """
    counts: dict[str, int] = {
        "both_dirs": 0,
        "frontend_only": 0,
        "generated_only": 0,
        "backend_only": 0,
        "infra_only": 0,
        "docs_only": 0,
        "other": 0,
    }
    sample_both: list[CommitClassification] = []
    sample_frontend: list[CommitClassification] = []
    sample_backend: list[CommitClassification] = []
    total = 0

    for sha in _list_commits(months):
        files = _commit_files(sha)
        if not files:
            continue
        total += 1
        surfaces = _classify(files)
        label = _label_for(surfaces)
        counts[label] = counts.get(label, 0) + 1
        subject = _git("log", "-n", "1", "--pretty=format:%s", sha)
        record = CommitClassification(
            sha=sha[:7],
            subject=subject,
            surfaces=surfaces,
            file_count=len(files),
        )
        if label == "both_dirs" and len(sample_both) < 10:
            sample_both.append(record)
        elif label == "frontend_only" and len(sample_frontend) < 5:
            sample_frontend.append(record)
        elif label == "backend_only" and len(sample_backend) < 5:
            sample_backend.append(record)

    percent = {
        key: round(value * 100 / total, 1) if total else 0.0
        for key, value in counts.items()
    }
    return CouplingReport(
        months=months,
        total_commits=total,
        counts=counts,
        percent=percent,
        sample_both_dirs=tuple(sample_both),
        sample_frontend_only=tuple(sample_frontend),
        sample_backend_only=tuple(sample_backend),
    )


def _format_text(report: CouplingReport) -> str:
    """Format the report as a human-readable text block.

    Args:
        report: Aggregated report.

    Returns:
        Text rendering suitable for printing or appending to docs.
    """
    lines = [
        f"Coupling report (last {report.months} months)",
        f"Total commits: {report.total_commits}",
        "",
        "Bucket counts:",
    ]
    for key, value in report.counts.items():
        pct = report.percent[key]
        lines.append(f"  {key:>16}: {value:>5}  ({pct:>5.1f}%)")
    lines.append("")
    if report.sample_both_dirs:
        lines.append("Recent commits touching BOTH frontend/ and backend/:")
        for record in report.sample_both_dirs:
            lines.append(f"  {record.sha} {record.subject}")
    return "\n".join(lines)


def _format_markdown(report: CouplingReport) -> str:
    """Format the report as a Markdown table block.

    Args:
        report: Aggregated report.

    Returns:
        Markdown rendering.
    """
    lines = [
        f"### Coupling snapshot (last {report.months} months)",
        "",
        "| Bucket | Commits | Share |",
        "|---|---:|---:|",
    ]
    for key, value in report.counts.items():
        pct = report.percent[key]
        lines.append(f"| `{key}` | {value} | {pct:.1f}% |")
    lines.append("")
    lines.append(f"**Total commits measured:** {report.total_commits}")
    lines.append("")
    if report.sample_both_dirs:
        lines.append("Most recent commits that touch BOTH `frontend/` and backend code:")
        lines.append("")
        for record in report.sample_both_dirs:
            lines.append(f"- `{record.sha}` — {record.subject}")
        lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Rolling window in months (default: 6)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of text.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Emit Markdown instead of text.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point.

    Returns:
        Process exit code.
    """
    args = _parse_args()
    if args.months <= 0:
        print("--months must be a positive integer", file=sys.stderr)
        return 2
    report = measure(args.months)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    elif args.markdown:
        print(_format_markdown(report))
    else:
        print(_format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
