"""Validate ComicPile Markdown links and top-level documentation ownership."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
REFERENCE_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\[([^\]]*)\]")
SHORTCUT_REFERENCE_RE = re.compile(r"(?<!!)\[([^\]\n]+)\](?![\[(])")
REFERENCE_DEFINITION_RE = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)
ALLOWED_ROOT_MARKDOWN = {
    "AGENTS.md",
    "COMIC_DEPENDENCIES_GUIDE.md",
    "CONTRIBUTING.md",
    "LOCAL_TESTING.md",
    "README.md",
    "ROLLBACK.md",
    "SECURITY.md",
    "TECH_DEBT.md",
    "prd.md",
}
IGNORED_DIRECTORIES = {".git", ".venv", "node_modules", "archive"}


def iter_markdown_files(root: Path) -> list[Path]:
    """Return Markdown paths that should participate in documentation checks.

    Historical archive documents are intentionally excluded because they preserve point-in-time
    evidence and may contain dead links or machine-local paths that must not become current
    repository contracts.

    Args:
        root: Repository root to inspect.

    Returns:
        Sorted Markdown paths included in validation.
    """
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)
    )


def _normalized_reference_label(label: str) -> str:
    """Normalize a Markdown reference label for case-insensitive lookup.

    Args:
        label: Reference label as written in Markdown.

    Returns:
        A normalized reference label.
    """
    return " ".join(label.split()).casefold()


def _reference_targets(text: str) -> tuple[list[str], list[str]]:
    """Resolve destinations used by reference-style Markdown links.

    Args:
        text: Markdown document content.

    Returns:
        Resolved destinations and undefined explicit reference labels.
    """
    definitions = {
        _normalized_reference_label(label): target
        for label, target in REFERENCE_DEFINITION_RE.findall(text)
    }
    text_without_definitions = REFERENCE_DEFINITION_RE.sub("", text)
    targets: list[str] = []
    undefined: list[str] = []

    for visible_text, label in REFERENCE_LINK_RE.findall(text_without_definitions):
        resolved_label = label if label else visible_text
        normalized = _normalized_reference_label(resolved_label)
        target = definitions.get(normalized)
        if target is None:
            undefined.append(resolved_label)
        else:
            targets.append(target)

    for visible_text in SHORTCUT_REFERENCE_RE.findall(text_without_definitions):
        normalized = _normalized_reference_label(visible_text)
        target = definitions.get(normalized)
        if target is not None:
            targets.append(target)

    return targets, undefined


def _validate_target(root: Path, markdown_file: Path, raw_target: str) -> str | None:
    """Validate one Markdown destination against repository boundaries.

    Args:
        root: Repository root used as the containment boundary.
        markdown_file: Markdown file containing the link.
        raw_target: Link destination as written in Markdown.

    Returns:
        A validation error string when invalid, otherwise ``None``.
    """
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith(("#", "mailto:")):
        return None

    relative_target = unquote(parsed.path)
    if not relative_target:
        return None

    candidate = (markdown_file.parent / relative_target).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return f"{markdown_file.relative_to(root)}: link escapes repository: {target}"

    if not candidate.exists():
        return f"{markdown_file.relative_to(root)}: missing target: {target}"
    return None


def find_broken_local_links(root: Path, markdown_files: list[Path]) -> list[str]:
    """Find Markdown links whose local file targets are invalid.

    Args:
        root: Repository root used for containment and relative paths.
        markdown_files: Markdown files to inspect.

    Returns:
        Validation errors for missing references, missing targets, or repository escapes.
    """
    broken: list[str] = []
    for markdown_file in markdown_files:
        text = markdown_file.read_text(encoding="utf-8")
        reference_targets, undefined_references = _reference_targets(text)
        for label in undefined_references:
            broken.append(f"{markdown_file.relative_to(root)}: undefined reference: {label}")
        targets = [*INLINE_LINK_RE.findall(text), *reference_targets]
        for raw_target in targets:
            error = _validate_target(root, markdown_file, raw_target)
            if error is not None:
                broken.append(error)
    return broken


def find_unapproved_root_markdown(root: Path) -> list[str]:
    """Find root Markdown files that bypass the documentation ownership model.

    Args:
        root: Repository root to inspect.

    Returns:
        Sorted names of unapproved root Markdown files.
    """
    return sorted(path.name for path in root.glob("*.md") if path.name not in ALLOWED_ROOT_MARKDOWN)


def main() -> int:
    """Run repository Markdown validation.

    Returns:
        Process exit status, where zero means validation passed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    markdown_files = iter_markdown_files(root)

    errors = [
        *find_broken_local_links(root, markdown_files),
        *(
            f"root Markdown is not documented in the allowlist: {filename}"
            for filename in find_unapproved_root_markdown(root)
        ),
    ]
    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Validated {len(markdown_files)} current Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
