#!/usr/bin/env python3
"""Fail when repository files contain unresolved Git conflict markers.

This guard is deterministic and offline. It scans tracked text files in the
checked-out tree (the actual candidate content in CI, including PR merge
checkouts) for anchored conflict-marker blocks:

* ``<<<<<<<`` (start, optional branch label)
* ``=======`` (middle separator)
* ``>>>>>>>`` (end, optional branch label)

Detection is stateful so ordinary ``=======`` separators (for example Markdown
setext headings) are not flagged unless they appear inside a conflict block.
Unambiguous start/end markers are always flagged. Missing terminators and
orphan markers are reported.

Approved fixture exclusions are narrow and documented: only files under
``tests/fixtures/conflict-markers/`` whose basename ends with ``.fixture.txt``
or ``.fixture.md`` may be excluded. Lockfiles, YAML/JSON/TOML, code, scripts,
and any other executable or structured-data file cannot be excluded, even if
placed in that directory.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

START_PREFIX = "<" * 7
MID_MARKER = "=" * 7
END_PREFIX = ">" * 7

APPROVED_FIXTURE_DIR = PurePosixPath("tests/fixtures/conflict-markers")
APPROVED_FIXTURE_SUFFIXES = (".fixture.txt", ".fixture.md")

# Extensions/names that must never be excluded from conflict-marker scanning.
PROTECTED_SUFFIXES = {
    ".py",
    ".pyi",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".sh",
    ".bash",
    ".zsh",
    ".sql",
    ".css",
    ".scss",
    ".html",
    ".htm",
    ".xml",
    ".svg",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".lock",
    ".sum",
    ".properties",
    ".env",
    ".dockerfile",
}
PROTECTED_NAMES = {
    "dockerfile",
    "makefile",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "cargo.lock",
    "poetry.lock",
    "uv.lock",
    "composer.lock",
    "gemfile.lock",
    "go.sum",
}


@dataclass(frozen=True)
class Finding:
    """A conflict-marker finding."""

    path: str
    line: int
    message: str
    marker: str

    def render(self) -> str:
        """Render a stable, grep-friendly finding line."""
        return f"{self.path}:{self.line}: {self.message}: {self.marker}"


def is_start_marker(line: str) -> bool:
    """Return whether line is a conflict start marker."""
    if not line.startswith(START_PREFIX):
        return False
    tail = line[len(START_PREFIX) :]
    return tail == "" or tail.startswith(" ")


def is_mid_marker(line: str) -> bool:
    """Return whether line is a conflict middle marker."""
    return line == MID_MARKER


def is_end_marker(line: str) -> bool:
    """Return whether line is a conflict end marker."""
    if not line.startswith(END_PREFIX):
        return False
    tail = line[len(END_PREFIX) :]
    return tail == "" or tail.startswith(" ")


def is_protected_path(path: str) -> bool:
    """Return whether a path must never be excluded from scanning."""
    posix = PurePosixPath(path)
    name = posix.name.lower()
    if name in PROTECTED_NAMES:
        return True
    suffixes = [suffix.lower() for suffix in posix.suffixes]
    return any(suffix in PROTECTED_SUFFIXES for suffix in suffixes)


def is_approved_fixture_exclusion(path: str) -> bool:
    """Return whether path is an explicitly approved fixture exclusion.

    Only narrow, non-protected fixture text files under
    ``tests/fixtures/conflict-markers/`` are allowed.
    """
    posix = PurePosixPath(path)
    if is_protected_path(path):
        return False
    try:
        posix.relative_to(APPROVED_FIXTURE_DIR)
    except ValueError:
        return False
    return posix.name.endswith(APPROVED_FIXTURE_SUFFIXES)


def tracked_files(root: Path) -> list[str]:
    """Return repository-relative tracked files, falling back to a walk."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [
            str(path.relative_to(root).as_posix())
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.parts
        ]
    return [entry.decode("utf-8", errors="surrogateescape") for entry in out.split(b"\0") if entry]


def read_text_lines(root: Path, rel_path: str) -> list[str] | None:
    """Read a file as UTF-8 text lines, or None for binary/unreadable files."""
    path = root / rel_path
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Conflict markers are ASCII; if we can't decode UTF-8, do a lossy scan.
        text = data.decode("utf-8", errors="replace")
    return text.splitlines()


def scan_lines(path: str, lines: list[str]) -> list[Finding]:
    """Scan lines for unresolved Git conflict markers."""
    findings: list[Finding] = []
    in_conflict = False
    saw_mid = False
    start_line = 0
    start_marker = ""

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r")
        if is_start_marker(line):
            if in_conflict:
                findings.append(
                    Finding(
                        path,
                        idx,
                        "nested conflict start marker inside unresolved conflict block",
                        line,
                    )
                )
            in_conflict = True
            saw_mid = False
            start_line = idx
            start_marker = line
            findings.append(Finding(path, idx, "unresolved conflict start marker", line))
            continue

        if is_mid_marker(line):
            if in_conflict:
                saw_mid = True
                findings.append(
                    Finding(path, idx, "unresolved conflict separator marker", line)
                )
            continue

        if is_end_marker(line):
            if in_conflict:
                findings.append(
                    Finding(path, idx, "unresolved conflict end marker", line)
                )
                in_conflict = False
                saw_mid = False
                start_line = 0
                start_marker = ""
            else:
                findings.append(
                    Finding(path, idx, "orphan conflict end marker", line)
                )
            continue

    if in_conflict:
        detail = "conflict block missing end marker"
        if not saw_mid:
            detail = "conflict block missing separator and end marker"
        findings.append(
            Finding(
                path,
                start_line,
                detail,
                start_marker,
            )
        )

    return findings


def scan_paths(root: Path, paths: list[str]) -> list[Finding]:
    """Scan repository-relative paths and return findings."""
    findings: list[Finding] = []
    for rel_path in paths:
        if is_approved_fixture_exclusion(rel_path):
            continue
        lines = read_text_lines(root, rel_path)
        if lines is None:
            continue
        findings.extend(scan_lines(rel_path, lines))
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to scan (default: current directory).",
    )
    parser.add_argument(
        "--paths-from",
        help="Optional newline-delimited file of repo-relative paths to scan.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional repo-relative paths to scan; defaults to git tracked files.",
    )
    return parser.parse_args(argv)


def load_paths(root: Path, args: argparse.Namespace) -> list[str]:
    """Resolve the scan path set from CLI arguments."""
    if args.paths_from:
        raw = Path(args.paths_from).read_text(encoding="utf-8")
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if args.paths:
        return list(args.paths)
    return tracked_files(root)


def main(argv: list[str] | None = None) -> int:
    """Run the conflict-marker guard."""
    args = parse_args(argv)
    root = Path(args.root).resolve()
    paths = load_paths(root, args)
    findings = scan_paths(root, paths)
    if findings:
        print("Unresolved Git conflict markers detected:", file=sys.stderr)
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        print(
            f"{len(findings)} conflict-marker finding(s) in {len({f.path for f in findings})} file(s).",
            file=sys.stderr,
        )
        return 1
    print(f"No unresolved Git conflict markers found in {len(paths)} scanned file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
