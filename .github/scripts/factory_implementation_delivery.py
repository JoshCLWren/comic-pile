"""Conservative mechanical evidence that a PR changes executable behavior.

This check is intentionally not a correctness proof. The independent exact-head
reviewer still has to verify each linked-issue requirement and its tests.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from collections.abc import Callable, Iterable
from urllib.parse import quote

DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
BEHAVIORAL_FILENAMES = frozenset({"dockerfile", "containerfile", "makefile", "gnumakefile"})
SOURCE_SUFFIXES = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".sh", ".sql", ".html", ".css", ".scss", ".vue", ".svelte",
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg",
)
TYPE_LINE = re.compile(
    r"(?im)^\s*(?:\*\*)?(?:issue\s+type|deliverable\s+type|"
    r"work\s+type)\s*:(?:\*\*)?\s*(?:\*\*)?"
    r"(docs-only|documentation-only|documentation|investigation|"
    r"planning|prd|acceptance-only|test-only)(?:\*\*)?\s*$"
)
PATCH_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


def is_implementation_issue(issue_body: str | None) -> bool:
    """Classify using a structured declaration, not arbitrary issue prose.

    Args:
        issue_body: Authoritative linked issue description.

    Returns:
        True by default, or False for an explicitly typed non-code ticket.
    """
    body = issue_body or ""
    match = TYPE_LINE.search(body)
    return match is None


def _is_docs_path(path: str) -> bool:
    """Whether the file can only serve as documentation."""
    normalized = path.lower().strip()
    return normalized.startswith("docs/") or normalized.endswith(DOC_SUFFIXES)


def _is_test_path(path: str) -> bool:
    """Whether a file contains tests rather than deliverable production code."""
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("tests/", "frontend/src/test/", "frontend/src/unit/"))
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def substantive_changed_files(changed_files: Iterable[str]) -> list[str]:
    """Find candidate behavioral source files, excluding docs and tests.

    Args:
        changed_files: Paths reported by the reviewed PR diff.

    Returns:
        Source file paths that could contain the requested implementation.
    """
    return [
        path for path in changed_files
        if path.strip()
        and (path.lower().endswith(SOURCE_SUFFIXES)
             or path.lower().rsplit("/", 1)[-1] in BEHAVIORAL_FILENAMES
             or path.lower().endswith((".dockerfile", ".containerfile")))
        and not _is_docs_path(path)
        and not _is_test_path(path)
    ]


class _WithoutDocstrings(ast.NodeTransformer):
    """Remove only actual Python documentation expression nodes."""

    def visit(self, node: ast.AST) -> ast.AST:
        """Strip leading docstrings while preserving behavioral string literals.

        Args:
            node: Python syntax node being traversed.

        Returns:
            Node with only documentation expressions removed.
        """
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        return super().visit(node)


def _code_tokens(source: str, path: str) -> str:
    """Compare complete source, preserving literals and ignoring comments."""
    if path.lower().endswith(".py"):
        tree = _WithoutDocstrings().visit(ast.parse(source))
        return ast.dump(tree, include_attributes=False)
    name = path.lower().rsplit("/", 1)[-1]
    hash_comments = path.lower().endswith((".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg"))
    hash_comments = hash_comments or name in BEHAVIORAL_FILENAMES
    # Match literals before comment delimiters so URLs, SQL strings, and
    # whitespace within values remain behavioral. Full source provides the
    # lexical context even when a changed line is deep inside a block comment.
    comments = r"\#[^\n]*" if hash_comments else r"/\*.*?\*/|//[^\n]*"
    if path.lower().endswith(".sql"):
        comments = r"/\*.*?\*/|--[^\n]*"
    if path.lower().endswith((".html", ".vue", ".svelte")):
        comments += r"|<!--.*?-->"
    pattern = re.compile(
        r"(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`)"
        + r"|(?P<comment>" + comments + r")|(?P<space>\s+)|(?P<code>.)",
        re.DOTALL,
    )
    if path.lower().endswith((".yml", ".yaml")) or name in {"makefile", "gnumakefile"}:
        # Indentation/newlines carry executable structure in these formats.
        code = "".join(match.group() for match in pattern.finditer(source)
                       if match.lastgroup != "comment")
        return repr([line.rstrip() for line in code.splitlines() if line.strip()])
    tokens = [match.group() for match in pattern.finditer(source)
              if match.lastgroup not in {"comment", "space"}]
    return repr(tokens)


def _has_code_delta(patch: str, path: str) -> bool:
    """Compare old/new complete sources, failing closed on incomplete Python."""
    old: list[str] = []
    new: list[str] = []
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("@@"):
            # Production callers provide complete-file context. A partial
            # hunk cannot establish whether its first line is inside a comment.
            if in_hunk or not re.match(r"@@ -[01](?:,\d+)? \+[01](?:,\d+)? @@", line):
                return False
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            new.append(line[1:])
        elif in_hunk and line.startswith("-"):
            old.append(line[1:])
        elif in_hunk and line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
    if not in_hunk:
        return False
    try:
        return _code_tokens("\n".join(old), path) != _code_tokens("\n".join(new), path)
    except (SyntaxError, ValueError):
        return False


def _file_patches(diff_text: str) -> dict[str, str]:
    """Split a unified Git diff into authoritative per-file patches."""
    patches: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for line in diff_text.splitlines():
        header = PATCH_HEADER.match(line)
        if header:
            if current:
                patches[current] = "\n".join(lines)
            current = header.group(2)
            lines = [line]
        elif current:
            lines.append(line)
    if current:
        patches[current] = "\n".join(lines)
    return patches


def pr_delivers_implementation(
    issue_body: str | None,
    changed_files: Iterable[str],
    diff_text: str | None = None,
) -> tuple[bool, str]:
    """Reject non-delivering implementations without judging feature correctness.

    Args:
        issue_body: Exact linked-issue body.
        changed_files: File paths of the current PR head.
        diff_text: Full unified patch for that same PR head, if available.

    Returns:
        Whether the mechanical behavioral-diff prerequisite is satisfied,
        plus an actionable reason. Missing diff never counts as evidence.
    """
    if not is_implementation_issue(issue_body):
        return True, "explicit non-implementation issue type; documentation allowed"
    candidates = substantive_changed_files(changed_files)
    if not candidates:
        return False, "implementation issue has no changed production source files"
    if diff_text is None:
        return False, "unavailable source diff; cannot verify executable changes"
    patches = _file_patches(diff_text)
    for path in candidates:
        if path in patches and _has_code_delta(patches[path], path):
            return True, "production executable code changed; semantic review required"
    return (
        False,
        "only documentation, comments, docstrings or formatting changed "
        "in production source files; executable delivery is unverified",
    )



def _previous_source(current: str, patch: str) -> str:
    """Reverse GitHub's patch against complete head source, validating every hunk."""
    lines = current.splitlines()
    previous: list[str] = []
    cursor = 0
    entries = patch.splitlines()
    index = 0
    while index < len(entries):
        header = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", entries[index])
        if not header:
            raise RuntimeError("missing or malformed source patch hunk")
        start = int(header[3]) - (int(header[4] or 1) > 0)
        if start < cursor or start > len(lines):
            raise RuntimeError("source patch has invalid hunk coordinates")
        previous.extend(lines[cursor:start])
        cursor = start
        old_count = new_count = 0
        index += 1
        while index < len(entries) and not entries[index].startswith("@@"):
            entry = entries[index]
            index += 1
            if entry.startswith("\\ No newline"):
                continue
            if not entry or entry[0] not in " +-":
                raise RuntimeError("unrecognized source patch line")
            if entry[0] in " +":
                if cursor >= len(lines) or lines[cursor] != entry[1:]:
                    raise RuntimeError("source patch does not match immutable head")
                cursor += 1
                new_count += 1
            if entry[0] in " -":
                previous.append(entry[1:])
                old_count += 1
        if old_count != int(header[2] or 1) or new_count != int(header[4] or 1):
            raise RuntimeError("incomplete source patch; cannot verify delivery")
    previous.extend(lines[cursor:])
    return "\n".join(previous)


def complete_pr_diff(
    pr_number: int, expected_head: str, repo: str,
    run: Callable[[list[str]], str],
) -> tuple[list[str], str]:
    """Fetch full source context and reconstruct the PR's original base.

    Args:
        pr_number: Open or merged pull request number.
        expected_head: Commit being reviewed.
        repo: Repository owner/name.
        run: GitHub CLI reader that raises RuntimeError on failure.

    Returns:
        Changed paths and a unified diff with complete source context.

    Raises:
        RuntimeError: If the head changes or complete source is unavailable.
    """
    info = json.loads(run(["api", f"repos/{repo}/pulls/{pr_number}"]))
    if info["head"]["sha"] != expected_head:
        raise RuntimeError("PR head changed during implementation inspection")
    files = json.loads(run([
        "api", "--paginate", "--slurp", f"repos/{repo}/pulls/{pr_number}/files",
    ]))
    records = [record for page in files for record in page]
    paths = [record["filename"] for record in records]
    candidates = set(substantive_changed_files(paths))
    patches: list[str] = []
    for record in records:
        path = record["filename"]
        if path not in candidates or record["status"] == "renamed" and not record.get("changes"):
            continue
        patch = record.get("patch")
        if not isinstance(patch, str) or not patch:
            raise RuntimeError(f"source patch unavailable for {path}")
        new = "" if record["status"] == "removed" else run([
            "api", "-H", "Accept: application/vnd.github.raw+json",
            f"repos/{repo}/contents/{quote(path, safe='/')}?ref={expected_head}",
        ])
        # Reverse the original PR patch rather than comparing against current
        # main, which can already contain the merged head during closure.
        old = _previous_source(new, patch)
        patches.append(
            f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
                [line + "\n" for line in old.splitlines()],
                [line + "\n" for line in new.splitlines()],
                fromfile=f"a/{path}", tofile=f"b/{path}",
                n=max(len(old.splitlines()), len(new.splitlines())) + 1,
            ))
        )
    return paths, "\n".join(patches)
