#!/usr/bin/env python3
"""Generate an exhaustive audit table for tracked Markdown documentation."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InventoryRow:
    """One tracked Markdown file and its default documentation disposition."""

    path: str
    purpose: str
    last_update: str
    overlap: str
    action: str
    replacement: str


def _git(*args: str) -> str:
    """Run a read-only Git command and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def tracked_markdown_files() -> list[str]:
    """Return every tracked Markdown path in deterministic order."""
    output = _git("ls-files", "*.md")
    return sorted(line for line in output.splitlines() if line)


def last_meaningful_update(path: str) -> str:
    """Return the most recent commit date touching a tracked path."""
    return _git("log", "-1", "--format=%cs", "--", path) or "unknown"


def default_disposition(path: str) -> tuple[str, str, str, str]:
    """Classify a Markdown path into a conservative default audit disposition."""
    file_path = Path(path)
    name = file_path.name

    if path == "README.md":
        return (
            "Project landing page and local-development entry point.",
            "Consolidates repository navigation; detailed guidance belongs in docs or Wiki.",
            "keep",
            "docs/README.md",
        )
    if path == "AGENTS.md":
        return (
            "Mandatory engineering rules for coding agents.",
            "Code-coupled contract; must not be duplicated in the Wiki.",
            "keep",
            "—",
        )
    if path == "docs/README.md":
        return (
            "Authoritative index and ownership map for repository documentation.",
            "Canonical repository documentation hub.",
            "keep",
            "—",
        )
    if path == "docs/changelog.md" or path.startswith("docs/changelog.d/"):
        return (
            "Product changelog history or generated changelog fragment.",
            "Canonical What's New source; fragments are assembled into the product surface.",
            "keep",
            "—",
        )
    if path.startswith(".github/"):
        return (
            "GitHub contribution, issue, pull-request, or automation guidance.",
            "Repository workflow contract tied directly to GitHub behavior.",
            "keep",
            "—",
        )
    if path.startswith("prompts/"):
        return (
            "Versioned agent or factory execution prompt.",
            "Automation-critical contract that must change atomically with factory behavior.",
            "keep",
            "—",
        )
    if path.startswith("docs/issue-plans/"):
        return (
            "Implementation plan retained for a specific GitHub issue.",
            "Potentially historical after the issue closes; review against the linked issue.",
            "archive",
            "Git history or Wiki historical decisions",
        )
    if path.startswith("docs/"):
        return (
            f"Repository documentation for {file_path.stem.replace('_', ' ').replace('-', ' ')}.",
            "Review for duplication against docs/README.md and current code before final disposition.",
            "review",
            "docs/README.md or ComicPile Wiki",
        )
    if name.lower() == "readme.md":
        return (
            f"Package- or directory-local documentation for {file_path.parent}.",
            "Keep only when the instructions are coupled to the adjacent code or package.",
            "review",
            "Nearest code-coupled documentation or docs/README.md",
        )
    return (
        "Tracked Markdown documentation outside the canonical docs hub.",
        "Review for consolidation, Wiki migration, or deletion.",
        "review",
        "docs/README.md or ComicPile Wiki",
    )


def build_inventory() -> list[InventoryRow]:
    """Build inventory rows covering every tracked Markdown file."""
    rows: list[InventoryRow] = []
    for path in tracked_markdown_files():
        purpose, overlap, action, replacement = default_disposition(path)
        rows.append(
            InventoryRow(
                path=path,
                purpose=purpose,
                last_update=last_meaningful_update(path),
                overlap=overlap,
                action=action,
                replacement=replacement,
            )
        )
    return rows


def render_markdown(rows: list[InventoryRow]) -> str:
    """Render inventory rows as the audit table required by issue #879."""
    header = (
        "| Path | Purpose | Last meaningful update | Duplicate / contradiction evidence | "
        "Disposition | Canonical replacement |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )
    lines = [header]
    for row in rows:
        values = (
            row.path,
            row.purpose,
            row.last_update,
            row.overlap,
            row.action,
            row.replacement,
        )
        escaped = [value.replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Generate the current tracked-Markdown audit table."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the generated table to this path instead of stdout.",
    )
    args = parser.parse_args()

    rendered = render_markdown(build_inventory())
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
