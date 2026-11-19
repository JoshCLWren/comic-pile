#!/usr/bin/env python3
"""Guard against hand-editing bot-owned route generation artifacts.

Route PRs must touch only ``docs/api/route-fragments/*.json`` source
fragments (excluding the generated rewrite artifact). The following
checked-in files are owned by the post-merge regeneration bot
(``.github/workflows/regenerate-routes.yml``) and must never be hand-edited
in a pull request:

* ``vercel.json`` — redeployed ingress; kept on ``main`` for Vercel
  (do not gitignore it, do not hand-edit it in a PR).
* ``docs/api/v2-route-inventory.json`` — generated inventory view.
* The ``<!-- route-burndown:begin -->`` ... ``<!-- route-burndown:end -->``
  section of ``AGENTS.md`` — generated runtime summary.

Untracked generated artifacts (owner directive 2026-11-19: feature PRs never
edit or commit generated files) are gitignored build outputs that no PR may
add back; deleting them is allowed. ``node scripts/generate_api_artifacts.mjs``
and the route generators produce them in CI, the deploy workflow and locally:

* ``frontend/src/generated/**`` — merged OpenAPI schema, types, native client.
* ``native/contracts/*.openapi.json`` — Rust-generated contracts, except the
  frozen tracked inputs ``python-legacy.openapi.json`` and
  ``roll-bootstrap-v1.openapi.json``.
* ``docs/api/route-fragments/vercel-rewrites.json`` — generated rewrite
  artifact (despite living under the fragments directory, it is not source).

This helper classifies a pull-request diff and fails when any bot-owned
file is present. ``AGENTS.md`` changes outside the generated block are
allowed. The ``route-fragment-guard`` workflow runs this helper on every
pull request; the unit tests in ``tests/test_route_fragment_guard.py``
pin the classifier behavior.
"""

from __future__ import annotations

import argparse
import subprocess
from typing import Final

GENERATED_PATHS: Final = frozenset(
    {
        "vercel.json",
        "docs/api/v2-route-inventory.json",
    }
)
REWRITE_ARTIFACT: Final = "docs/api/route-fragments/vercel-rewrites.json"
GENERATED_CLIENT_PREFIX: Final = "frontend/src/generated/"
CONTRACTS_PREFIX: Final = "native/contracts/"
FROZEN_CONTRACTS: Final = frozenset(
    {
        "native/contracts/python-legacy.openapi.json",
        "native/contracts/roll-bootstrap-v1.openapi.json",
    }
)
SOURCE_FRAGMENT_PREFIX: Final = "docs/api/route-fragments/"
AGENTS_PATH: Final = "AGENTS.md"
AGENTS_BEGIN_PREFIX: Final = "<!-- route-burndown:begin"
AGENTS_END_MARKER: Final = "<!-- route-burndown:end -->"


def is_source_fragment(path: str) -> bool:
    """Return whether ``path`` is a contributor-editable route source.

    Args:
        path: Repository-relative path.

    Returns:
        True for ``docs/api/route-fragments/*.json`` source fragments
        except the generated ``vercel-rewrites.json`` artifact.
    """
    name = path.removeprefix(SOURCE_FRAGMENT_PREFIX)
    if "/" in name or not name.endswith(".json"):
        return False
    if not path.startswith(SOURCE_FRAGMENT_PREFIX):
        return False
    return path != REWRITE_ARTIFACT


def is_generated_path(path: str) -> bool:
    """Return whether ``path`` is a bot-owned generated file.

    Args:
        path: Repository-relative path.

    Returns:
        True for ``vercel.json``, the inventory, and the generated
        rewrite artifact. ``AGENTS.md`` is only generated inside the
        burndown markers, so the bare path is not unconditionally
        generated; see :func:`agents_block_changed`.
    """
    return path in GENERATED_PATHS


def is_untracked_generated_path(path: str) -> bool:
    """Return whether ``path`` is a gitignored generated build artifact.

    Args:
        path: Repository-relative path.

    Returns:
        True for ``frontend/src/generated/**``, Rust-generated
        ``native/contracts/*.openapi.json`` (not the frozen inputs) and the
        rewrite artifact. No PR may add or modify these; deleting is allowed.
    """
    if path == REWRITE_ARTIFACT or path.startswith(GENERATED_CLIENT_PREFIX):
        return True
    name = path.removeprefix(CONTRACTS_PREFIX)
    return (
        path.startswith(CONTRACTS_PREFIX)
        and "/" not in name
        and name.endswith(".openapi.json")
        and path not in FROZEN_CONTRACTS
    )


def extract_agents_block(text: str) -> str | None:
    """Extract the generated burndown block from ``AGENTS.md`` text.

    Args:
        text: Full ``AGENTS.md`` content.

    Returns:
        The block including both markers, or ``None`` when markers are
        missing or out of order.
    """
    begin_index = text.find(AGENTS_BEGIN_PREFIX)
    end_index = text.find(AGENTS_END_MARKER)
    if begin_index == -1 or end_index == -1 or begin_index >= end_index:
        return None
    return text[begin_index : end_index + len(AGENTS_END_MARKER)]


def agents_block_changed(base_text: str, head_text: str) -> bool:
    """Return whether the generated ``AGENTS.md`` block differs.

    Args:
        base_text: Base-revision ``AGENTS.md`` content.
        head_text: Head-revision ``AGENTS.md`` content.

    Returns:
        True when the marked block differs (including a missing block
        on exactly one side). Edits outside the markers return False.
    """
    base_block = extract_agents_block(base_text)
    head_block = extract_agents_block(head_text)
    if base_block is None or head_block is None:
        return base_block != head_block
    return base_block != head_block


def find_generated_violations(
    changed_files: list[str],
    agents_changed: bool,
    deleted_files: frozenset[str] = frozenset(),
) -> list[str]:
    """List bot-owned or untracked generated files present in a PR diff.

    Args:
        changed_files: Repository-relative paths changed by the PR.
        agents_changed: Whether the generated ``AGENTS.md`` block
            changed (True is a violation even though the bare
            ``AGENTS.md`` path is editable outside the markers).
        deleted_files: Paths the PR deletes. Deleting an untracked
            generated artifact is allowed (that is how it leaves git).

    Returns:
        Sorted violation labels; empty when the PR is fragment-only
        (or route-unrelated) and therefore compliant.
    """
    violations = sorted(
        path
        for path in changed_files
        if is_generated_path(path)
        or (is_untracked_generated_path(path) and path not in deleted_files)
    )
    if agents_changed and AGENTS_PATH in changed_files:
        violations.append(f"{AGENTS_PATH} (route-burndown block)")
    return violations


def agents_block_changed_for_refs(base: str, head: str) -> bool:
    """Return whether the head changed the AGENTS burndown block from base.

    The comparison uses the merge base, not the current base-branch tip:
    a PR that edits AGENTS.md outside the markers must not be failed merely
    because main regenerated the block after the branch was created.

    Args:
        base: Base revision (for example the pull-request base SHA).
        head: Head revision.

    Returns:
        True when the generated burndown block differs from the merge base.
    """
    merge_base = _git_text("merge-base", base, head).strip()
    base_text = _git_text("show", f"{merge_base}:{AGENTS_PATH}")
    head_text = _git_text("show", f"{head}:{AGENTS_PATH}")
    return agents_block_changed(base_text, head_text)


def regenerated_agents_only(base_text: str, head_text: str) -> bool:
    """Require all AGENTS.md edits to stay inside the generated route block."""
    base_block = extract_agents_block(base_text)
    head_block = extract_agents_block(head_text)
    if base_block is None or head_block is None:
        return False
    return base_text.replace(base_block, "", 1) == head_text.replace(
        head_block, "", 1
    )


def regenerated_pr_violations(
    changed_files: list[str], base: str, head: str
) -> list[str]:
    """Reject anything outside bot-owned artifacts, including AGENTS guidance."""
    allowed = GENERATED_PATHS | {AGENTS_PATH}
    # The bot never commits untracked generated artifacts.
    violations = sorted(path for path in changed_files if path not in allowed)
    if not changed_files:
        violations.append("regeneration PR has no changed artifacts")
    if AGENTS_PATH in changed_files:
        merge_base = _git_text("merge-base", base, head).strip()
        base_text = _git_text("show", f"{merge_base}:{AGENTS_PATH}")
        head_text = _git_text("show", f"{head}:{AGENTS_PATH}")
        if not regenerated_agents_only(base_text, head_text):
            violations.append(f"{AGENTS_PATH} (changes outside route-burndown block)")
    return violations


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base revision for the three-dot diff (default: origin/main).",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Head revision for the three-dot diff (default: HEAD).",
    )
    parser.add_argument(
        "--allow-generated",
        action="store_true",
        help="Permit only reproducible generated artifacts in the trusted regeneration PR.",
    )
    return parser.parse_args()


def _git_text(*args: str) -> str:
    """Run a git command and return stdout as text.

    Args:
        *args: Arguments to ``git``.

    Returns:
        Stdout text.

    Raises:
        subprocess.CalledProcessError: When git fails.
    """
    return subprocess.check_output(
        ["git", *args], text=True, encoding="utf-8"
    )


def main() -> int:
    """Check a PR diff for bot-owned generated files.

    Returns:
        Process exit code: 0 when no violation, 1 on violation,
        2 when the diff cannot be computed.
    """
    args = parse_args()
    try:
        listing = _git_text("diff", "--name-only", f"{args.base}...{args.head}")
    except subprocess.CalledProcessError as exc:
        print(f"route fragment guard failed to compute diff: {exc}")
        return 2
    changed_files = [line.strip() for line in listing.splitlines() if line.strip()]
    try:
        deleted_listing = _git_text(
            "diff", "--name-only", "--diff-filter=D", f"{args.base}...{args.head}"
        )
    except subprocess.CalledProcessError as exc:
        print(f"route fragment guard failed to compute deletions: {exc}")
        return 2
    deleted_files = frozenset(
        line.strip() for line in deleted_listing.splitlines() if line.strip()
    )
    if args.allow_generated:
        try:
            violations = regenerated_pr_violations(
                changed_files, args.base, args.head
            )
        except subprocess.CalledProcessError as exc:
            print(f"route regeneration guard failed to inspect diff: {exc}")
            return 2
        if violations:
            print("::error::Regeneration PR contains non-generated changes.")
            for violation in violations:
                print(f"  - {violation}")
            return 1
        print("Regeneration artifact scope passed; full CI verifies determinism.")
        return 0
    agents_changed = False
    if AGENTS_PATH in changed_files:
        try:
            agents_changed = agents_block_changed_for_refs(args.base, args.head)
        except subprocess.CalledProcessError as exc:
            print(f"route fragment guard failed to read AGENTS.md: {exc}")
            return 2
    violations = find_generated_violations(changed_files, agents_changed, deleted_files)
    if violations:
        print(
            "::error::PR touches generated files. Edit route fragments only "
            "(docs/api/route-fragments/*.json, excluding vercel-rewrites.json) "
            "and Rust/TS sources. vercel.json, the inventory and the AGENTS.md "
            "block are regenerated post-merge by regenerate-routes.yml; "
            "frontend/src/generated/**, native/contracts/*.openapi.json "
            "(except the frozen inputs) and vercel-rewrites.json are gitignored "
            "build outputs of `node scripts/generate_api_artifacts.mjs`."
        )
        for violation in violations:
            print(f"  - {violation}")
        print(
            "Remove generated files from this PR: `git checkout origin/main -- "
            "vercel.json docs/api/v2-route-inventory.json` and `git rm --cached` "
            "any untracked generated artifact (take main's version on conflict)."
        )
        return 1
    print(
        "Route fragment guard passed: no bot-owned generated files in diff "
        f"({len(changed_files)} changed file(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
