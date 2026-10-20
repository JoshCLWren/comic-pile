"""Deterministic change-scope merge guard for factory pull requests.

Incident #3964: a factory PR declared ``Closes #3609`` but changed only a
scratch reproduction test (whose own header said it would be deleted before
commit) plus unrelated ``frontend/pnpm-lock.yaml`` churn. The worker, the
semantic reviewer, Greptile, PR-Agent and CI all passed it, it merged, and the
bug auto-closed with no application fix. Reviewer prompting alone cannot
prevent that, so this module is a pure, model-free gate the review controller
runs inside ``mechanical_merge_gate`` (the single exact-head gate behind every
``factory:ready`` promotion and every drain/dispatcher merge).

Rules (each produces a ``deny`` with a concrete reason, which the controller
routes to ``factory:changes-requested``):

1. Empty fix. A PR that closes/fixes an issue (closing keyword in the body,
   the canonical ``factory/<worker>-<issue>-...`` branch, or GitHub's linked
   closing references) must change at least one non-test application file
   (see :func:`classify_path`). Exempt when every closed issue is labeled
   ``test-only``, when every closed issue is a non-bug docs/ops/testing issue
   (:data:`NON_APP_ISSUE_LABELS`), when the PR body carries
   :data:`NO_APP_CODE_MARKER`, or when the PR body carries
   :data:`MANUAL_ONLY_MARKER` and no closed issue is a bug.
2. Orphan lockfile. A lockfile change (``pnpm-lock.yaml``, ``uv.lock``, ...)
   needs a manifest change (``package.json``/``pyproject.toml``/workspace
   file) in the same directory or below it. Exempt with
   :data:`LOCKFILE_ONLY_MARKER` or when every closed issue is labeled
   ``dependencies``.
3. Scratch files. An added/modified file whose name contains ``Repro`` or
   ``scratch`` as a word, or whose added lines carry a throwaway marker (for
   example a comment saying the file is to be deleted before commit), is
   never mergeable. There is no override: rename it into a real test or
   delete it.

The gate is deterministic and fail-closed: payloads it cannot interpret yield
``retry`` (never ``pass``).
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal, TypedDict

ScopeDecision = Literal["pass", "retry", "deny"]


class ScopeResult(TypedDict):
    decision: ScopeDecision
    reason: str


NO_APP_CODE_MARKER = "<!-- factory-scope:no-app-code-allowed -->"
LOCKFILE_ONLY_MARKER = "<!-- factory-scope:lockfile-only-allowed -->"
MANUAL_ONLY_MARKER = "<!-- factory-execution:manual-only -->"

# An explicit, human-applied statement that the issue's deliverable is tests.
TEST_ONLY_ISSUE_LABELS = frozenset({"test-only"})
# Issues whose deliverable is legitimately not application code, honored only
# when the issue is not also a bug report.
NON_APP_ISSUE_LABELS = frozenset(
    {
        "test-only",
        "testing",
        "docs",
        "documentation",
        "ops",
        "infrastructure",
        "ci-infrastructure",
        "e2e-infrastructure",
        "dependencies",
    }
)
BUG_ISSUE_LABELS = frozenset({"bug", "bug-fix", "user-reported"})
DEPENDENCY_ISSUE_LABELS = frozenset({"dependencies"})

CLOSING_REF_RE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
    r"(?:(?:JoshCLWren/comic-pile)?#)(\d+)\b"
)
FACTORY_BRANCH_ISSUE_RE = re.compile(r"^factory/\d+-(\d+)-")

LOCKFILE_MANIFESTS: Mapping[str, tuple[str, ...]] = {
    "pnpm-lock.yaml": ("package.json", "pnpm-workspace.yaml"),
    "package-lock.json": ("package.json",),
    "npm-shrinkwrap.json": ("package.json",),
    "yarn.lock": ("package.json",),
    "bun.lockb": ("package.json",),
    "uv.lock": ("pyproject.toml",),
    "poetry.lock": ("pyproject.toml",),
    "Pipfile.lock": ("Pipfile",),
}
MANIFEST_NAMES = frozenset(name for manifests in LOCKFILE_MANIFESTS.values() for name in manifests)

# Application code roots. Everything else (docs/, .github/, scripts/, tools/,
# infra/, archive/, benchmark/, skills/, prompts/, tests/ ...) is not app code.
APP_CODE_PREFIXES = (
    "app/",
    "comic_pile/",
    "api/",
    "alembic/versions/",
    "frontend/src/",
    "frontend/public/",
    "static/",
)
# Runtime/build configuration that can legitimately be the whole fix.
APP_CONFIG_FILES = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "frontend/package.json",
        "vercel.json",
        "Dockerfile",
        "alembic.ini",
        "frontend/index.html",
        "frontend/index.tsx",
        "frontend/vite.config.ts",
        "frontend/tailwind.config.ts",
        "frontend/postcss.config.ts",
        "frontend/tsconfig.json",
    }
)
# Test and test-support locations inside otherwise-app roots.
TEST_DIR_SEGMENTS = frozenset(
    {"tests", "test", "tests_e2e", "unit", "__tests__", "__mocks__", "__fixtures__", "e2e"}
)
TEST_FILE_RE = re.compile(
    r"(?:^test_.*\.py$|.*_test\.py$|^conftest\.py$"
    r"|.*\.(?:test|spec|audit|e2e)\.[cm]?[jt]sx?$)"
)
SCRATCH_NAME_RE = re.compile(
    r"(?:Repro(?:duction)?(?![a-z])|Scratch(?![a-z])"
    r"|(?<![A-Za-z])(?:repro(?:duction)?|scratch)(?![a-z]))"
)
SCRATCH_CONTENT_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:remove[sd]?|delete[sd]?|drop(?:ped)?|revert(?:ed)?)\b[^\n]{0,24}?"
    r"\bbefore\s+(?:commit(?:ting)?|merg(?:e|ing)|push(?:ing)?|landing)\b"
    r"|\bscratch\s+(?:repro(?:duction)?|test|file|script)\b"
    r")"
)
# Content markers are only meaningful in source/test files, not prose.
SCANNED_CONTENT_EXTENSIONS = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".sh", ".sql", ".css", ".html"}
)
# Files excluded from the scratch-content scan because they define the scan.
SCOPE_GATE_SELF_PATHS = frozenset(
    {
        ".github/scripts/factory_change_scope.py",
        "tests/test_factory_change_scope.py",
    }
)


def scope_result(decision: ScopeDecision, reason: str) -> ScopeResult:
    return {"decision": decision, "reason": reason}


def is_test_path(path: str) -> bool:
    """Return whether a repository path is a test or test-support file."""
    parts = path.split("/")
    name = parts[-1]
    if TEST_FILE_RE.match(name):
        return True
    return any(segment in TEST_DIR_SEGMENTS for segment in parts[:-1])


def classify_path(path: str) -> str:
    """Classify one changed path: app, test, lockfile, manifest or other."""
    name = posixpath.basename(path)
    if name in LOCKFILE_MANIFESTS:
        return "lockfile"
    if is_test_path(path):
        return "test"
    if path in APP_CONFIG_FILES:
        return "app"
    if name in MANIFEST_NAMES:
        return "manifest"
    if path.startswith(APP_CODE_PREFIXES):
        return "app"
    return "other"


def closing_issue_numbers(
    *,
    body: str,
    branch: str | None,
    linked: Iterable[int] = (),
) -> list[int]:
    """Every issue the PR claims to close, from all three closing sources."""
    numbers = {int(match) for match in CLOSING_REF_RE.findall(body or "")}
    if branch:
        branch_match = FACTORY_BRANCH_ISSUE_RE.match(branch)
        if branch_match:
            numbers.add(int(branch_match.group(1)))
    numbers.update(int(number) for number in linked)
    return sorted(numbers)


def _added_lines(patch: str) -> Iterable[str]:
    for line in (patch or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            yield line[1:]


COMMENT_TOKEN_RE = re.compile(r"(?:(?:^|\s)(?://|#(?=[\s!]|$)|--\s)|/\*|<!--)")


def _in_comment(line: str, position: int) -> bool:
    """Throwaway markers count only inside comments, never in code strings."""
    if line.lstrip().startswith("*"):
        return True
    return COMMENT_TOKEN_RE.search(line[:position]) is not None


def scratch_findings(files: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return a reason per added/modified file that looks like a scratch file."""
    findings: list[str] = []
    for item in files:
        path = str(item.get("filename") or "")
        if not path or str(item.get("status") or "") == "removed":
            continue
        if path.startswith("archive/") or path in SCOPE_GATE_SELF_PATHS:
            continue
        stem = posixpath.basename(path)
        if SCRATCH_NAME_RE.search(stem):
            findings.append(f"`{path}` is named like a scratch/repro file")
            continue
        if posixpath.splitext(stem)[1] not in SCANNED_CONTENT_EXTENSIONS:
            continue
        for line in _added_lines(str(item.get("patch") or "")):
            match = SCRATCH_CONTENT_RE.search(line)
            if match and _in_comment(line, match.start()):
                findings.append(
                    f"`{path}` contains a throwaway marker ({match.group(0).strip()!r})"
                )
                break
    return findings


def orphan_lockfiles(paths: Iterable[str]) -> list[str]:
    """Lockfiles changed without a manifest change in their directory tree."""
    changed = list(paths)
    orphans: list[str] = []
    for path in changed:
        name = posixpath.basename(path)
        manifests = LOCKFILE_MANIFESTS.get(name)
        if manifests is None:
            continue
        root = posixpath.dirname(path)
        prefix = f"{root}/" if root else ""
        justified = any(
            posixpath.basename(other) in manifests
            and (other.startswith(prefix) if prefix else True)
            for other in changed
            if other != path
        )
        if not justified:
            orphans.append(path)
    return orphans


def _labels(issue: Mapping[str, Any]) -> set[str]:
    labels: set[str] = set()
    for label in issue.get("labels") or []:
        if isinstance(label, Mapping) and label.get("name"):
            labels.add(str(label["name"]))
        elif isinstance(label, str):
            labels.add(label)
    return labels


def issue_allows_no_app_code(labels: set[str]) -> bool:
    """Whether an issue's own labels say its deliverable is not app code."""
    if labels & TEST_ONLY_ISSUE_LABELS:
        return True
    if labels & BUG_ISSUE_LABELS:
        return False
    return bool(labels & NON_APP_ISSUE_LABELS)


def evaluate_change_scope(
    *,
    files: object,
    body: str,
    branch: str | None,
    issues: Mapping[int, Mapping[str, Any]],
    linked: Iterable[int] = (),
) -> ScopeResult:
    """Pure change-scope decision for one exact PR head.

    ``files`` is the REST ``pulls/{n}/files`` item list (filename, status,
    patch, previous_filename). ``issues`` maps every closing issue number to
    its REST issue payload (labels are read from it).
    """
    if not isinstance(files, list) or not files:
        return scope_result("retry", "changed-file list was unavailable or empty")
    rows: list[Mapping[str, Any]] = []
    for item in files:
        if not isinstance(item, Mapping) or not item.get("filename"):
            return scope_result("retry", "changed-file list contained an invalid row")
        rows.append(item)
    paths: list[str] = []
    for item in rows:
        paths.append(str(item["filename"]))
        previous = item.get("previous_filename")
        if previous:
            paths.append(str(previous))

    reasons: list[str] = []

    scratch = scratch_findings(rows)
    if scratch:
        reasons.append(
            "scratch/repro files must not merge (" + "; ".join(scratch) + "); "
            "turn them into a real, permanently named regression test or delete them"
        )

    body = body or ""
    closing = closing_issue_numbers(body=body, branch=branch, linked=linked)
    missing = [number for number in closing if number not in issues]
    if missing:
        return scope_result(
            "retry",
            "closing issue labels could not be read for "
            + ", ".join(f"#{number}" for number in missing),
        )
    issue_labels = {number: _labels(issues[number]) for number in closing}

    lock_orphans = orphan_lockfiles(paths)
    lock_exempt = LOCKFILE_ONLY_MARKER in body or (
        bool(closing) and all(labels & DEPENDENCY_ISSUE_LABELS for labels in issue_labels.values())
    )
    if lock_orphans and not lock_exempt:
        reasons.append(
            "lockfile changed without a matching manifest change ("
            + ", ".join(f"`{path}`" for path in lock_orphans)
            + "); revert the unrelated lockfile churn"
        )

    if closing:
        app_paths = [path for path in paths if classify_path(path) == "app"]
        is_bug = any(labels & BUG_ISSUE_LABELS for labels in issue_labels.values())
        exempt = (
            NO_APP_CODE_MARKER in body
            or (MANUAL_ONLY_MARKER in body and not is_bug)
            or all(issue_allows_no_app_code(labels) for labels in issue_labels.values())
        )
        if not app_paths and not exempt:
            refs = ", ".join(f"#{number}" for number in closing)
            reasons.append(
                f"PR closes {refs} but changes no non-test application code "
                "(only tests, lockfiles, docs or tooling changed); implement the fix "
                "for the issue's acceptance criteria in application code, or, if the "
                "fix is already on main, do not close the issue from a test-only PR"
            )

    if reasons:
        return scope_result("deny", "change-scope guard: " + " | ".join(reasons))
    return scope_result("pass", "change scope is consistent with the closed issues")
