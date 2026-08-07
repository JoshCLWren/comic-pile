"""Validate ComicPile Markdown links and top-level documentation ownership."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
ALLOWED_ROOT_MARKDOWN = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LOCAL_TESTING.md",
    "README.md",
    "ROLLBACK.md",
    "SECURITY.md",
}
IGNORED_DIRECTORIES = {".git", ".venv", "node_modules"}


def iter_markdown_files(root: Path) -> list[Path]:
    """Return Markdown paths that should participate in documentation checks.

    Args:
        root: Repository root directory.

    Returns:
        Sorted Markdown file paths, excluding generated dependency directories.
    """
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)
    )


def find_broken_local_links(root: Path, markdown_files: list[Path]) -> list[str]:
    """Find Markdown links whose local file targets do not exist.

    Args:
        root: Repository root directory.
        markdown_files: Markdown files to inspect.

    Returns:
        Human-readable broken-link diagnostics.
    """
    broken: list[str] = []
    for markdown_file in markdown_files:
        text = markdown_file.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith(("#", "mailto:")):
                continue

            relative_target = unquote(parsed.path)
            if not relative_target:
                continue

            candidate = (markdown_file.parent / relative_target).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                broken.append(
                    f"{markdown_file.relative_to(root)}: link escapes repository: {target}",
                )
                continue

            if not candidate.exists():
                broken.append(f"{markdown_file.relative_to(root)}: missing target: {target}")
    return broken


def find_unapproved_root_markdown(root: Path) -> list[str]:
    """Find new root Markdown files that bypass the documentation ownership model.

    Args:
        root: Repository root directory.

    Returns:
        Sorted root Markdown filenames that are not explicitly approved.
    """
    return sorted(
        path.name
        for path in root.glob("*.md")
        if path.name not in ALLOWED_ROOT_MARKDOWN
    )


def main() -> int:
    """Run repository Markdown validation.

    Returns:
        Process status code, zero when all checks pass.
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
        *(
            f"root Markdown is not documented in the allowlist: {filename}"
            for filename in find_unapproved_root_markdown(root)
        ),
    ]
    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Validated {len(markdown_files)} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
