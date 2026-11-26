"""Validate ComicPile Markdown links and top-level documentation ownership."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
REFERENCE_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\[([^\]]*)\]")
SHORTCUT_REFERENCE_RE = re.compile(r"(?<!!)\[([^\]\n]+)\](?![\[(])")
REFERENCE_DEFINITION_RE = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)
ALLOWED_ROOT_MARKDOWN = {
    "AGENTS.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LOCAL_TESTING.md",
    "README.md",
    "ROLLBACK.md",
    "SECURITY.md",
    "TECH_DEBT.md",
}
IGNORED_DIRECTORIES = {".git", ".venv", ".vercel", "node_modules", "archive"}
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
SETEXT_UNDERLINE_RE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
HTML_ANCHOR_RE = re.compile(
    r"""<(?:a|h[1-6])\b[^>]*\b(?:id|name)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _tracked_markdown_files(root: Path) -> list[Path] | None:
    """Return existing tracked Markdown paths, or ``None`` outside a Git worktree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    files = [root / path for path in result.stdout.split("\0") if path]
    return sorted(path for path in files if path.is_file())


def iter_markdown_files(root: Path) -> list[Path]:
    """Return tracked Markdown paths that participate in documentation checks.

    Historical archive documents are intentionally excluded because they preserve point-in-time
    evidence and may contain dead links or machine-local paths that must not become current
    repository contracts. Git scope excludes untracked/ignored overlays and locally excluded files;
    non-Git fixture roots retain the directory-walk fallback used by unit tests.

    Args:
        root: Repository root to inspect.

    Returns:
        Sorted Markdown paths included in validation.
    """
    candidates = _tracked_markdown_files(root)
    if candidates is None:
        candidates = list(root.rglob("*.md"))
    return sorted(
        path
        for path in candidates
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

    Explicit full and collapsed references are reported when their definition is missing.
    Shortcut references are only links when a matching definition exists, per Markdown syntax;
    otherwise the bracketed text is ordinary prose and must not be treated as a broken link.

    Args:
        text: Markdown document content.

    Returns:
        A pair containing resolved destinations and undefined explicit reference labels.
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
            broken.append(
                f"{markdown_file.relative_to(root)}: undefined reference: {label}",
            )
        targets = [*INLINE_LINK_RE.findall(text), *reference_targets]
        for raw_target in targets:
            error = _validate_target(root, markdown_file, raw_target)
            if error is not None:
                broken.append(error)
    return broken


def _visible_markdown(text: str) -> str:
    """Blank fenced code blocks so illustrative links and headings are ignored.

    Args:
        text: Markdown source as written.

    Returns:
        The same lines with fenced-block content replaced by blank lines.
    """
    visible: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        fence_match = FENCE_RE.match(line)
        if fence_match is not None:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = marker
            elif marker == fence and line.strip().startswith(fence_match.group(1)):
                fence = None
            visible.append("")
            continue
        visible.append("" if fence is not None else line)
    return "\n".join(visible)


def _heading_anchor(heading: str) -> str:
    """Convert a heading to the GitHub-style fragment it publishes.

    Args:
        heading: Heading text without the leading hash marks.

    Returns:
        The lowercase, punctuation-stripped anchor with spaces replaced by hyphens.
    """
    value = re.sub(r"`([^`]+)`", r"\1", heading.strip())
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_~]", "", value)
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return value.strip().lower().replace(" ", "-")


def _document_anchors(path: Path) -> set[str]:
    """Collect real fragment targets published by a Markdown document.

    Args:
        path: Markdown file whose anchors should be collected.

    Returns:
        ATX, setext, and explicit HTML heading anchors, including duplicate suffixes.
    """
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    text = _visible_markdown(path.read_text(encoding="utf-8"))
    lines = text.splitlines()
    for index, line in enumerate(lines):
        heading_match = HEADING_RE.match(line)
        if heading_match is not None:
            heading = heading_match.group(1)
        elif SETEXT_UNDERLINE_RE.match(line) and index > 0:
            previous = lines[index - 1].strip()
            if not previous or HEADING_RE.match(previous) is not None:
                continue
            heading = previous
        else:
            continue
        base = _heading_anchor(heading)
        if not base:
            continue
        duplicate_index = seen.get(base, 0)
        seen[base] = duplicate_index + 1
        anchors.add(base if duplicate_index == 0 else f"{base}-{duplicate_index}")
    anchors.update(name.lower() for name in HTML_ANCHOR_RE.findall(text))
    return anchors


def find_broken_anchors(root: Path, markdown_files: list[Path]) -> list[str]:
    """Find Markdown fragment links that do not resolve in the target document.

    Missing files are already reported by ``find_broken_local_links``; this check
    reports only fragments that point at an existing Markdown file but no published
    heading or anchor. Links inside fenced code blocks are illustrative and do not
    participate in validation. Fragments on non-Markdown files are code or line
    references that this heading-based check cannot validate, so they are skipped.

    Args:
        root: Repository root used for containment and relative paths.
        markdown_files: Markdown files to inspect.

    Returns:
        Validation errors for unresolved local Markdown fragments.
    """
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for markdown_file in markdown_files:
        text = _visible_markdown(markdown_file.read_text(encoding="utf-8"))
        reference_targets, _ = _reference_targets(text)
        for raw_target in [*INLINE_LINK_RE.findall(text), *reference_targets]:
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.fragment:
                continue
            relative = unquote(parsed.path)
            candidate = (
                (markdown_file.parent / relative).resolve()
                if relative
                else markdown_file.resolve()
            )
            if candidate.suffix.casefold() != ".md":
                continue
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if not candidate.is_file():
                continue
            if candidate not in anchor_cache:
                anchor_cache[candidate] = _document_anchors(candidate)
            if unquote(parsed.fragment).casefold() not in anchor_cache[candidate]:
                errors.append(f"{markdown_file.relative_to(root)}: broken anchor: {target}")
    return errors


def find_unapproved_root_markdown(root: Path) -> list[str]:
    """Find tracked root Markdown files that bypass the documentation ownership model.

    Args:
        root: Repository root to inspect.

    Returns:
        Sorted names of unapproved root Markdown files.
    """
    tracked = _tracked_markdown_files(root)
    if tracked is not None:
        candidates = [path for path in tracked if path.parent == root]
    else:
        candidates = list(root.glob("*.md"))
    return sorted(path.name for path in candidates if path.name not in ALLOWED_ROOT_MARKDOWN)


def main() -> int:
    """Run repository Markdown validation.

    Returns:
        Process exit status, where zero means validation passed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to inspect.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    markdown_files = iter_markdown_files(root)

    errors = [
        *find_broken_local_links(root, markdown_files),
        *find_broken_anchors(root, markdown_files),
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
