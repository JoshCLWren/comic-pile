#!/usr/bin/env python3
"""Attempt immediate factory-only merges without review or a CI wait.

Only trusted main is executed, the path/ownership allowlist fails closed, and
GitHub receives the exact verified head SHA. GitHub branch protection still
controls whether that immediate merge is permitted for the selected token.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
OWNER_RE = re.compile(r"^factory:(?:local|[1-9][0-9]*)$")
FACTORY_PATHS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^\.github/scripts/(?:factory[-_]|fixed-model[-_]|free-model-factory[-_])[A-Za-z0-9_.-]+\.(?:py|sh|cjs)$",
        r"^\.github/scripts/(?:local-ollama-review|local_review_contract|nvidia-factory-worker|omniroute-factory-worker|stale_pr_decay|hourly_coderabbit_review)\.(?:py|sh|cjs)$",
        r"^\.github/workflows/(?:factory[-_]|fixed-model[-_]|free-model-factory[-_])[A-Za-z0-9_.-]+\.ya?ml$",
        r"^\.github/workflows/local-ollama-review\.ya?ml$",
        r"^\.github/actions/factory-syntax/[A-Za-z0-9_./-]+$",
        r"^\.github/free-model-factories\.tsv$",
        r"^\.github/factory-expected-workers\.json$",
        r"^\.github/factory-roster-snapshot\.json$",
        r"^tests/test_free_model_factories\.py$",
        r"^scripts/(?:factory[-_]|test_factory_)[A-Za-z0-9_.-]+\.py$",
        r"^scripts/tests/(?:test_factory|test_opencode_review_policy|test_select_fcm_nvidia_model)[A-Za-z0-9_.-]*\.py$",
        r"^tests/(?:test_factory|test_fixed_model|test_local_ollama_review_contract|test_auto_ollama_dispatch)[A-Za-z0-9_.-]*\.py$",
        r"^docs/FACTORY[A-Za-z0-9_.-]*\.md$",
        r"^docs/(?:AUTONOMOUS_FACTORY_POLICY|LOCAL_FACTORY_REVIEW)\.md$",
        r"^\.agents/skills/(?:crouton-factory-codex|local-factory-[A-Za-z0-9_-]+)/[A-Za-z0-9_./-]+$",
    )
)
PROTECTED = frozenset(
    {
        ".github/factory-fast-merge.json",
        ".github/workflows/factory-fast-merge.yml",
        ".github/scripts/factory-fast-merge.py",
        "tests/test_factory_fast_merge.py",
    }
)
BLOCKED_LABELS = frozenset(
    {"factory:blocked", "needs-human", "do-not-merge", "security-review"}
)
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def factory_path(path: str) -> bool:
    """Recognize only allowlisted factory paths, excluding the policy itself."""
    if (
        not isinstance(path, str)
        or path in PROTECTED
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        return False
    return any(pattern.fullmatch(path) for pattern in FACTORY_PATHS)


def factory_candidate(
    pr: dict[str, Any], files: list[dict[str, Any]], repo: str,
) -> tuple[bool, str]:
    """Fail closed for product, fork, draft, ownership, or untrusted changes."""
    if pr.get("state") != "open" or pr.get("draft") is not False:
        return False, "PR is not open and ready"
    if pr.get("mergeable") is not True:
        return False, "GitHub has not confirmed mergeability"
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    if base.get("ref") != "main" or base.get("repo", {}).get("full_name") != repo:
        return False, "PR base differs from this repository's main"
    if head.get("repo", {}).get("full_name") != repo:
        return False, "Fork heads are ineligible"
    if not HEAD_RE.fullmatch(str(head.get("sha", ""))):
        return False, "PR head SHA is invalid"
    user = pr.get("user") or {}
    author = user.get("login")
    if author in {"dependabot[bot]", "renovate[bot]"}:
        return False, "Dependency bots are excluded"
    if (
        pr.get("author_association") not in TRUSTED_ASSOCIATIONS
        and author != "github-actions[bot]"
    ):
        return False, "PR author is not a trusted repository collaborator"
    labels = {
        label.get("name")
        for label in pr.get("labels", [])
        if isinstance(label, dict)
    }
    if not {"factory", "factory:unowned"} <= labels:
        return False, "Factory and unowned labels are required"
    if labels & BLOCKED_LABELS or any(
        isinstance(label, str) and OWNER_RE.fullmatch(label)
        for label in labels
    ):
        return False, "Factory PR has an active owner or hold"
    changed = pr.get("changed_files")
    if (
        not isinstance(changed, int)
        or changed < 1
        or changed >= 3000
        or changed != len(files)
    ):
        return False, "Changed file listing is incomplete"
    # A roster edit is one atomic, validated unit. The generator must never
    # fast-merge a standalone lock/snapshot that describes different workers.
    changed_paths = {file.get("filename") for file in files if isinstance(file, dict)}
    roster_files = {
        ".github/free-model-factories.tsv",
        ".github/factory-expected-workers.json",
        ".github/factory-roster-snapshot.json",
    }
    if changed_paths & roster_files and not roster_files <= changed_paths:
        return False, "Factory roster manifest, lock and snapshot must change together"
    for file in files:
        if not isinstance(file, dict):
            return False, "Malformed changed-file entry"
        if not factory_path(file.get("filename", "")):
            return False, f"Outside factory-only allowlist: {file.get('filename')}"
        if file.get("status") == "renamed" and not factory_path(
            file.get("previous_filename", "")
        ):
            return False, "Rename crosses factory boundary"
    return True, "Factory-only PR eligible"


def enabled(path: Path) -> bool:
    """Read the trusted-main repository switch, defaulting to disabled."""
    try:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def gh_api(
    endpoint: str, *, method: str = "GET", fields: dict[str, str] | None = None,
) -> Any:
    """Call GitHub's authenticated REST API without executing PR source."""
    cmd = ["gh", "api", "--method", method, endpoint]
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"GitHub API {method} {endpoint} failed: {result.stderr[:400]}"
        )
    return json.loads(result.stdout)


def pages(endpoint: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """Fetch full page sets, refusing GitHub's 3,000-file truncation boundary."""
    items: list[dict[str, Any]] = []
    for number in range(1, limit + 1):
        separator = "&" if "?" in endpoint else "?"
        page = gh_api(f"{endpoint}{separator}per_page=100&page={number}")
        if not isinstance(page, list) or not all(
            isinstance(item, dict) for item in page
        ):
            raise RuntimeError("GitHub returned an invalid paged response")
        items.extend(page)
        if len(page) < 100:
            return items
    raise RuntimeError("GitHub pagination exceeded safe 3,000-item limit")


def numbers(repo: str, *, pr: int | None, head: str | None) -> list[int]:
    """Select one PR, exact-head PRs, or all open PRs."""
    if pr is not None:
        return [pr]
    if head is not None:
        if not HEAD_RE.fullmatch(head):
            raise ValueError("Invalid CI head SHA")
        data = pages(f"repos/{repo}/commits/{head}/pulls")
    else:
        data = pages(f"repos/{repo}/pulls?state=open")
    return sorted({
        item["number"] for item in data
        if isinstance(item.get("number"), int)
        and not isinstance(item["number"], bool)
        and item["number"] > 0
    })


def handle(repo: str, number: int) -> tuple[bool, str]:
    """Attempt exactly one immediate SHA-pinned merge for an eligible PR."""
    pr = gh_api(f"repos/{repo}/pulls/{number}")
    if not isinstance(pr, dict):
        raise RuntimeError("Invalid pull request response")
    files = pages(f"repos/{repo}/pulls/{number}/files")
    valid, reason = factory_candidate(pr, files, repo)
    if not valid:
        return False, reason
    head = pr["head"]["sha"]
    # Do not poll or wait for CI/review here. A branch-protection refusal is a
    # truthful skip, not permission to forge checks or modify the branch rule.
    try:
        result = gh_api(
            f"repos/{repo}/pulls/{number}/merge",
            method="PUT",
            fields={
                "sha": head,
                "merge_method": "squash",
                "commit_title": f"factory: immediate fast-merge #{number}",
            },
        )
    except RuntimeError as exc:
        return False, f"GitHub rejected immediate merge: {exc}"
    if not isinstance(result, dict) or result.get("merged") is not True:
        raise RuntimeError("GitHub did not confirm PR merge")
    return True, str(result.get("sha", ""))



def dispatch_production(merged_count: int) -> None:
    """Dispatch production after any bot merge, even if later PR handling fails."""
    if merged_count <= 0:
        return
    command = (
        'source .github/scripts/factory-dispatch-production-deploy.sh; '
        'factory_dispatch_production_deploy "$1"'
    )
    result = subprocess.run(
        [
            "bash", "-euo", "pipefail", "-c", command, "factory-fast-merge",
            f"Factory-only Fast Merge merged {merged_count} PR(s)",
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "Post-merge production dispatch failed: " + result.stderr[:400]
        )


def main() -> None:
    """Attempt immediate owner-enabled merges and report results."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pr", type=int)
    group.add_argument("--head")
    parser.add_argument(
        "--config", type=Path, default=Path(".github/factory-fast-merge.json"),
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Invalid repository")
    if args.pr is not None and args.pr <= 0:
        parser.error("PR number must be positive")
    if not enabled(args.config):
        print(json.dumps({"enabled": False, "merged": [], "skipped": []}))
        return
    merged: list[int] = []
    skipped: list[dict[str, Any]] = []
    try:
        for number in numbers(args.repo, pr=args.pr, head=args.head):
            did_merge, reason = handle(args.repo, number)
            if did_merge:
                merged.append(number)
            else:
                skipped.append({"pr": number, "reason": reason})
    finally:
        # GitHub's GITHUB_TOKEN merge emits no push event. Do not lose the
        # deployment if a later PR fails during this same scan.
        dispatch_production(len(merged))
    print(json.dumps({"enabled": True, "merged": merged, "skipped": skipped}))


if __name__ == "__main__":
    main()
