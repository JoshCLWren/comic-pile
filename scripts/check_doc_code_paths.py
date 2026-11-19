"""Fail when current Markdown docs cite repository code paths that do not exist.

The check is offline and deterministic. It inspects inline-backtick file paths in the Markdown
files selected by ``check_markdown_docs.iter_markdown_files`` (Markdown links are validated by
that script). Fenced code blocks are ignored so examples are not treated as contracts.

Resolution rules:

* A path containing ``/`` resolves against the repository root, then the citing document's
  directory, then ``frontend/`` and ``frontend/src/`` (so ``src/App.tsx`` style references in frontend docs work).
* A bare code filename (for example ``lib.rs``) must match the basename of some tracked file.
* Globs, placeholders, URLs, and well-known generated-output locations are skipped.

Historical documents opt out explicitly, so point-in-time paths stay intentional:

* ``<!-- docs-path-check: historical -->`` anywhere in a file skips the whole file.
* ``<!-- docs-path-check: ignore -->`` on a line skips that line.
* Files under ``HISTORICAL_PREFIXES`` are skipped (per-issue plans and changelogs).
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from check_markdown_docs import iter_markdown_files

HISTORICAL_PREFIXES = ("docs/issue-plans/", "docs/changelog")
HISTORICAL_FILE_MARKER = "<!-- docs-path-check: historical -->"
IGNORE_LINE_MARKER = "<!-- docs-path-check: ignore -->"
GENERATED_PREFIXES = (
    "dogfood-output/",
    "frontend/test-results/",
    "test-results/",
    "static/react/",
    "node_modules/",
    "target/",
)
CODE_EXTENSIONS = r"(?:py|rs|tsx?|jsx?|mjs|cjs|sh|sql|css|html|ya?ml|toml|json|md)"
BARE_CODE_EXTENSIONS = {"py", "rs", "ts", "tsx", "js", "jsx", "mjs", "cjs", "sh", "yml", "yaml"}
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
PATH_RE = re.compile(
    rf"^(?:\./)?[A-Za-z0-9_.@\-]+(?:/[A-Za-z0-9_.@\-]+)+\.{CODE_EXTENSIONS}$"
    rf"|^[A-Za-z0-9_\-]+\.{CODE_EXTENSIONS}$"
)
SUFFIX_RE = re.compile(r"(?:::[\w:]+|:\d+(?:-\d+)?|#L?\d+\S*)$")
PLACEHOLDER_RE = re.compile(r"[*{}<>$]|YYYY|NNN|\bXXX")


def tracked_files(root: Path) -> list[str]:
    """Return repository-relative tracked file paths, falling back to a directory walk."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
        return [line for line in result.stdout.splitlines() if line]
    except OSError, subprocess.CalledProcessError:
        return [
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts
        ]


def extract_paths(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, candidate_path)`` pairs from inline code outside fences."""
    found: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or IGNORE_LINE_MARKER in INLINE_CODE_RE.sub("", line):
            continue
        for span in INLINE_CODE_RE.findall(line):
            candidate = SUFFIX_RE.sub("", span.strip())
            if PLACEHOLDER_RE.search(candidate) or not PATH_RE.match(candidate):
                continue
            found.append((number, candidate.removeprefix("./")))
    return found


def path_resolves(
    root: Path, doc: Path, candidate: str, basenames: set[str], tracked: set[str]
) -> bool:
    """Return whether ``candidate`` names an existing file or an intentionally skipped path."""
    if candidate.startswith(GENERATED_PREFIXES):
        return True
    if "/" in candidate:
        bases = (root, doc.parent, root / "frontend", root / "frontend" / "src")
        return any((base / candidate).exists() for base in bases) or candidate in tracked
    extension = candidate.rsplit(".", 1)[-1]
    if extension not in BARE_CODE_EXTENSIONS:
        return True
    return candidate in basenames


def _has_marker(text: str, marker: str) -> bool:
    """Return whether ``marker`` appears as a real comment, not in a code span or fence."""
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and marker in INLINE_CODE_RE.sub("", line):
            return True
    return False


def find_stale_paths(root: Path, markdown_files: list[Path]) -> list[str]:
    """Return one error per documented code path that no longer resolves."""
    tracked = set(tracked_files(root))
    basenames = {name.rsplit("/", 1)[-1] for name in tracked}
    errors: list[str] = []
    for doc in markdown_files:
        relative = doc.relative_to(root).as_posix()
        if relative.startswith(HISTORICAL_PREFIXES):
            continue
        text = doc.read_text(encoding="utf-8")
        if _has_marker(text, HISTORICAL_FILE_MARKER):
            continue
        for number, candidate in extract_paths(text):
            if not path_resolves(root, doc, candidate, basenames, tracked):
                errors.append(f"{relative}:{number}: stale code path: {candidate}")
    return errors


def main() -> int:
    """Run the check and return a process exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    files = iter_markdown_files(root)
    errors = find_stale_paths(root, files)
    for error in errors:
        print(error)
    if errors:
        print(
            f"{len(errors)} stale doc code path(s). Fix the path, remove the section, or mark "
            f"history with `{HISTORICAL_FILE_MARKER}` / `{IGNORE_LINE_MARKER}`."
        )
        return 1
    print(f"Doc code paths resolve in {len(files)} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
