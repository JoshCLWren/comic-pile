#!/usr/bin/env python3
"""Generate an exhaustive audit table for tracked Markdown documentation."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


GENERATED_INVENTORY_PATH = "docs/MARKDOWN_INVENTORY.md"


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
    """Return every tracked Markdown source path in deterministic order.

    The generated inventory is intentionally excluded so regenerating it is idempotent rather
    than making the output describe itself and immediately become stale after its first commit.

    Returns:
        Sorted repository-relative Markdown source paths tracked by Git.
    """
    output = _git("ls-files", "*.md")
    return sorted(
        line
        for line in output.splitlines()
        if line and line != GENERATED_INVENTORY_PATH
    )


def last_meaningful_update(path: str) -> str:
    """Return the most recent commit date touching a tracked path.

    Args:
        path: Repository-relative tracked path to inspect.

    Returns:
        The most recent commit date in ISO calendar form, or ``unknown``.
    """
    return _git("log", "-1", "--format=%cs", "--", path) or "unknown"


def default_disposition(path: str) -> tuple[str, str, str, str]:
    """Classify a Markdown path into an explicit audit disposition.

    Args:
        path: Repository-relative Markdown path to classify.

    Returns:
        Purpose, overlap evidence, disposition action, and canonical replacement.
    """
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
    if path in {"CONTRIBUTING.md", "SECURITY.md"}:
        return (
            "Repository contribution or security contract.",
            "GitHub-facing project policy that belongs beside the code.",
            "keep",
            "—",
        )
    if path == "TECH_DEBT.md":
        return (
            "Legacy repository-local technical debt list.",
            "GitHub Issues are the current backlog source of truth.",
            "delete",
            "GitHub Issues",
        )
    if path == "ROLLBACK.md":
        return (
            "Legacy rollback and recovery guidance.",
            (
                "Operational recovery guidance belongs in the maintained docs hub or Wiki, "
                "not a root-level silo."
            ),
            "merge",
            "docs/README.md and ComicPile Wiki troubleshooting",
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
    code_coupled_docs = {
        "docs/API.md",
        "docs/AUTONOMOUS_FACTORY_POLICY.md",
        "docs/DATABASE_SAVE_LOAD.md",
        "docs/FACTORY_GITHUB_VISIBILITY.md",
        "docs/GIT_HOOKS.md",
        "docs/ISSUE_EXECUTION_PROTOCOL.md",
        "docs/PRODUCTION_STARTUP_DIAGNOSTICS.md",
        "docs/REACT_ARCHITECTURE.md",
        "docs/WIKI_HANDOFF.md",
        "docs/prod-clone-workflow.md",
    }
    if path in code_coupled_docs:
        return (
            (
                "Code-coupled repository contract for "
                f"{file_path.stem.replace('_', ' ').replace('-', ' ')}."
            ),
            (
                "Linked from the authoritative docs hub and must change atomically with "
                "repository or operational behavior."
            ),
            "keep",
            "—",
        )
    if path.startswith((".github/", ".agents/", ".claude/")):
        return (
            "Repository automation, contribution, or agent execution guidance.",
            "Code-coupled workflow contract that must change atomically with repository behavior.",
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
    if path.startswith("archive/"):
        return (
            "Historical or exploratory documentation retained for reference.",
            "Not active guidance; archive location already communicates historical ownership.",
            "archive",
            "Git history or ComicPile Wiki historical decisions",
        )
    if path.startswith("docs/issue-plans/"):
        return (
            "Implementation plan retained for a specific GitHub issue.",
            (
                "Potentially historical after the issue closes; preserve as implementation "
                "history rather than active guidance."
            ),
            "archive",
            "Git history or ComicPile Wiki historical decisions",
        )
    if path.startswith("docs/"):
        return (
            f"Repository documentation for {file_path.stem.replace('_', ' ').replace('-', ' ')}.",
            (
                "Human-facing narrative should move out of the active code-coupled documentation "
                "set unless linked by the docs hub."
            ),
            "move to Wiki",
            "ComicPile Wiki",
        )
    if name.lower() == "readme.md":
        return (
            f"Package- or directory-local documentation for {file_path.parent}.",
            (
                "Adjacent package guidance is discoverable where the code lives and can change "
                "atomically with it."
            ),
            "keep",
            "—",
        )
    return (
        "Tracked Markdown documentation outside the canonical docs hub.",
        (
            "Standalone narrative documentation should not create another competing repository "
            "source of truth."
        ),
        "move to Wiki",
        "ComicPile Wiki",
    )


def build_inventory() -> list[InventoryRow]:
    """Build inventory rows covering every tracked Markdown source file.

    Returns:
        One inventory row for each tracked Markdown source path.
    """
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
    """Render inventory rows as the audit table required by issue #879.

    Args:
        rows: Inventory rows to render in table order.

    Returns:
        A complete Markdown table ending with a newline.
    """
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
    """Generate the current tracked-Markdown audit table.

    Returns:
        Process exit status, where zero means generation succeeded.
    """
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