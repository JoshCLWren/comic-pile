#!/usr/bin/env python3
"""Neon-first, bounded GitHub discovery reads for trusted factory workflows.

Never cache mutations, PR/issue boundary reads, CI/review decisions, GitHub
Actions liveness, or merge authorization. Those operations must read GitHub
live. A missing, expired, or unavailable Neon record falls back to GitHub.
This script is invoked only by the factory gh shim in trusted controller jobs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import parse_qs


class GitHubReadError(RuntimeError):
    def __init__(self, returncode: int, stderr: str):
        super().__init__("GitHub API read failed")
        self.returncode = returncode
        self.stderr = stderr


def allowed_read(args: list[str], repo: str) -> int | None:
    """Return a bounded TTL only for non-authoritative, read-only list calls."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return None
    if not args or not repo or any(
        a in {"--method", "-X", "--input", "-f", "-F", "--field", "--raw-field", "-H", "--header"}
        or a.startswith(("--method=", "--input=", "-f", "-F", "--field=", "--raw-field=", "-H"))
        for a in args
    ):
        return None
    endpoint = None
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
        elif a in {"--jq", "-q", "--template", "-t", "--hostname"}:
            skip_next = True
        elif a in {"--paginate", "--slurp", "--silent", "-i", "--include"}:
            # Response headers must remain live; never cache --include/-i.
            if a in {"-i", "--include"}:
                return None
        elif a.startswith(("--jq=", "--template=")):
            continue
        elif a.startswith("-"):
            return None
        elif endpoint is None:
            endpoint = a.lstrip("/")
        else:
            return None
    if endpoint is None:
        return None

    prefix = f"repos/{repo}/"
    if not endpoint.startswith(prefix):
        return None
    tail = endpoint[len(prefix):]
    route, _, query = tail.partition("?")
    params = parse_qs(query, keep_blank_values=True)
    if route == "pulls" and params.get("state") == ["all"]:
        return 120
    if route == "pulls" and params.get("state") == ["open"]:
        return 45
    if route == "issues" and params.get("state") == ["open"]:
        return 45
    if route == "issues/comments" and "since" in params:
        return 60
    if route == "issues/1093/comments":
        return 90
    # These endpoints inform ranking and stale-lease discovery, not write
    # authorization. Repeated per-candidate scans previously bypassed Neon.
    # Callers doing a mutation-boundary verification pass an explicit header,
    # which is deliberately excluded by allowed_read above.
    if re.fullmatch(r"issues/[1-9][0-9]*/dependencies/blocked_by", route) and params == {"per_page": ["100"]}:
        return 600
    if re.fullmatch(r"issues/[1-9][0-9]*/comments", route) and params == {"per_page": ["100"]}:
        return 180
    return None


def projected(repo: str, kind: str) -> int:
    """Emit the complete event-fed issue/PR discovery snapshot when fresh."""
    if repo != os.environ.get("GITHUB_REPOSITORY") or kind not in {"issue", "pr"}:
        return 2
    if not os.environ.get("FACTORY_STATE_DSN_FILE"):
        return 2
    from factory_state_projection import projected_json

    items = projected_json(repo, kind)
    if items is None:
        return 2
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        return 2
    print(json.dumps(items, separators=(",", ":")))
    return 0


def api(args: list[str]) -> int:
    """Read a shared, fresh Neon result first for an explicitly safe GET list."""
    real_gh = os.environ.get("FACTORY_REAL_GH", "/usr/bin/gh")
    command = [real_gh, "api", *args]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    ttl = allowed_read(args, repo) if os.environ.get("FACTORY_STATE_DSN_FILE") else None
    if ttl is None:
        return subprocess.call(command)

    from factory_state_cache import cached_json

    # Keys include the full argument vector, and are scoped to the current repo.
    # No tokens, secrets or request headers are cached.
    digest = hashlib.sha256(json.dumps(args, separators=(",", ":")).encode()).hexdigest()
    key = f"factory-github-get-v1:{repo}:{digest}"

    def fetch(_previous: list[dict[str, str]]) -> list[dict[str, str]]:
        response = subprocess.run(command, capture_output=True, text=True, check=False)
        if response.returncode:
            raise GitHubReadError(response.returncode, response.stderr)
        return [{"stdout": response.stdout}]

    try:
        response = cached_json(key, fetch, ttl_seconds=ttl)
    except GitHubReadError as error:
        print(error.stderr, file=sys.stderr, end="")
        return error.returncode
    # A corrupt cache must not be mistaken for an empty successful GitHub read.
    if len(response) != 1 or not isinstance(response[0].get("stdout"), str):
        print("[factory-state] invalid cached GitHub read; retrying live", file=sys.stderr)
        return subprocess.call(command)
    print(response[0]["stdout"], end="")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "projected":
        return projected(argv[1], argv[2])
    if len(argv) >= 3 and argv[:2] == ["api", "--"]:
        return api(argv[2:])
    print("usage: factory_gh_read_through.py projected REPO KIND | api -- ARGS...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
