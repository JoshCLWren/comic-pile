#!/usr/bin/env python3
"""Generate an exhaustive audit table for tracked Markdown documentation."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


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


def _linked_markdown_targets(root: Path) -> set[str]:
    """Return repository Markdown targets linked from canonical entry points."""
    targets: set[str] = set()
    for source in (
        "README.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "LOCAL_TESTING.md",
        "docs/README.md",
    ):
        source_path = root / source
        if not source_path.is_file():
            continue
        text = source_path.read_text(encoding="utf-8")
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text):
            parsed = urlsplit(target.strip().split(maxsplit=1)[0].strip("<>"))
            if parsed.scheme or parsed.netloc or not parsed.path.endswith(".md"):
                continue
            candidate = (source_path.parent / unquote(parsed.path)).resolve()
            try:
                relative = candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                targets.add(relative.as_posix())
    return targets


def _has_historical_marker(text: str) -> bool:
    """Return whether a real historical marker exists outside inline/fenced code."""
    fence: str | None = None
    marker = "<!-- docs-path-check: historical -->"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker_chars = stripped[:3]
            if fence is None:
                fence = marker_chars
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is None and stripped == marker:
            return True
    return False


def _content_disposition(path: str, text: str, default_action: str) -> tuple[str, str, str]:
    """Apply explicit historical/superseded markers before path defaults."""
    if _has_historical_marker(text):
        return (
            "Point-in-time record; body is preserved for provenance, not current instructions.",
            "historical — preserve",
            "Git history / ComicPile Wiki historical decisions",
        )
    lines = text.splitlines()
    heading = "\n".join(lines[:12]).casefold()
    title = lines[0].casefold() if lines else ""
    if "superseded" in heading or "status:** historical" in heading:
        return (
            "Superseded record; follow the document's current-replacement notice.",
            "superseded — preserve with link",
            "See supersession notice in document",
        )
    if "historical" in title or "status:** point-in-time" in heading:
        return (
            "Point-in-time record; body is preserved for provenance, not current instructions.",
            "historical — preserve",
            "Git history / ComicPile Wiki historical decisions",
        )
    if path.startswith(("docs/recovery/", "docs/reports/", "docs/issue-plans/")):
        return (
            "Dated recovery/report evidence; preserve without treating it as active guidance.",
            "historical — preserve",
            "Git history / ComicPile Wiki historical decisions",
        )
    return (
        "Linked from a canonical entry point; must change atomically with repository behavior."
        if default_action == "keep"
        else "Content audit required before changing ownership or moving this document.",
        default_action,
        "—" if default_action == "keep" else "Canonical docs hub / ComicPile Wiki",
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
    if path in {"CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "LOCAL_TESTING.md", "SECURITY.md"}:
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
            "Frozen historical changelog source retained only for provenance.",
            "Release notes now publish through the database-backed release ledger.",
            "historical — preserve",
            "Database-backed release ledger",
        )
    code_coupled_docs = {
        "docs/API.md",
        "docs/API_V1_CANONICAL.md",
        "docs/CBL_CATALOG_API.md",
        "docs/CBL_CATALOG_CONSUMER_CENSUS.md",
        "docs/CBL_COLLECTION_EXCLUSIONS.md",
        "docs/CBL_COMICVINE_LOOKUP.md",
        "docs/CBL_CREATE_CYCLE_FEEDBACK.md",
        "docs/CBL_SERIES_NAMING.md",
        "docs/CBL_SOURCE_LABELS.md",
        "docs/CHATGPT_FACTORY_PROMPT.md",
        "docs/COMICVINE_RUNTIME_FALLBACK.md",
        "docs/CREATOR_SUMMARY_READ.md",
        "docs/DATABASE_SAVE_LOAD.md",
        "docs/FRONTEND_OPENAPI_TYPES.md",
        "docs/FRONTEND_VISUAL_GRAMMAR.md",
        "docs/GIT_HOOKS.md",
        "docs/ISSUE_CARD_MOUNT_INVENTORY.md",
        "docs/ISSUE_EXECUTION_PROTOCOL.md",
        "docs/NAVIGATION_ENTRY_POINTS.md",
        "docs/PLAYWRIGHT_VERSION_POLICY.md",
        "docs/PRODUCTION_PROFILE.md",
        "docs/PRODUCTION_STARTUP_DIAGNOSTICS.md",
        "docs/PRODUCT_ACCEPTANCE_PROTOCOL.md",
        "docs/REACT_ARCHITECTURE.md",
        "docs/REACT_INTERACTION_POLICY.md",
        "docs/READING_LIST_EXECUTION_ADR.md",
        "docs/RELEASE_COLLECTION_EXCLUSIONS.md",
        "docs/REPOSITORY_STRUCTURE_DECISION.md",
        "docs/RUST_FACTORY_ENDPOINT_PATTERN.md",
        "docs/VERCEL_ARCHITECTURE.md",
        "docs/VERCEL_DEPLOYMENT.md",
        "docs/frontend-request-audit-4499.md",
        "docs/images/README.md",
        "docs/WIKI_HANDOFF.md",
        "docs/api/AIP_V2_SHAPE_GUARD.md",
        "docs/api/PASSWORD_POLICY.md",
        "docs/api/READING_LIST_AUTHORING.md",
        "docs/prod-clone-workflow.md",
        "docs/rate_limiting.md",
        "frontend/AGENTS.md",
        "frontend/docs/CLASS_NAME_LAYOUT_GUARD.md",
        "frontend/src/test/UI_AUDIT.md",
        "tools/oxlint/anti-slop/UPSTREAM.md",
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
    if path.startswith("scripts/__fixtures__/route-burndown/"):
        return (
            "Generated route-generator test fixture.",
            "Regenerate with the owning script; not active documentation.",
            "generated — test fixture",
            "scripts/generate_route_burndown.mjs",
        )
    if path.startswith(("docs/manual-qa/", "docs/testing/")):
        return (
            "Active QA or test-maintenance contract.",
            "Code-coupled guidance that must change with product behavior and test tooling.",
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
            "Implementation history; preserve rather than treating it as active guidance.",
            "historical — preserve",
            "Git history or ComicPile Wiki historical decisions",
        )
    if path.startswith("docs/"):
        return (
            f"Repository documentation for {file_path.stem.replace('_', ' ').replace('-', ' ')}.",
            "No automatic Wiki disposition; classify from content and canonical incoming links.",
            "review — classify",
            "Canonical docs hub / ComicPile Wiki",
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
        One inventory row for each tracked Markdown source path. The generated
        inventory itself is excluded so regeneration remains idempotent.
    """
    root = Path(__file__).resolve().parents[1]
    linked = _linked_markdown_targets(root)
    rows: list[InventoryRow] = []
    for path in tracked_markdown_files():
        purpose, overlap, action, replacement = default_disposition(path)
        text = (root / path).read_text(encoding="utf-8")
        overlap, action, replacement = _content_disposition(path, text, action)
        if path in linked and action == "review — classify":
            action = "keep"
            overlap = "Linked from a canonical entry point; keep versioned with the code."
            replacement = "—"
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