#!/usr/bin/env python3
"""Read the SHA serving the production alias, failing closed on uncertain data.

This is a *read-only* Vercel API call used to reconcile a canceled duplicate
CLI deployment. It must never treat a queued, building, unaliased, failed,
preview, or wrong-project deployment as production.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping

PRODUCTION_ALIAS = "comic-pile.vercel.app"
EXPECTED_ORG = "JoshCLWren"
EXPECTED_REPO = "comic-pile"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def verified_sha(payload: object, project_id: str) -> str | None:
    """Return the SHA only when Vercel confirms the exact live production target."""
    if not isinstance(payload, Mapping):
        return None
    deployment = payload.get("deployment", payload)
    if not isinstance(deployment, Mapping):
        return None
    project = deployment.get("project")
    actual_project_id = deployment.get("projectId")
    if actual_project_id is None and isinstance(project, Mapping):
        actual_project_id = project.get("id")
    if actual_project_id != project_id:
        return None
    if (deployment.get("readyState") or deployment.get("state")) != "READY":
        return None
    if deployment.get("target") != "production" or deployment.get("aliasError") is not None:
        return None
    aliases = deployment.get("alias")
    if not isinstance(aliases, list) or PRODUCTION_ALIAS not in aliases:
        return None
    meta = deployment.get("meta")
    if not isinstance(meta, Mapping):
        return None
    if (
        meta.get("githubCommitRef") != "main"
        or meta.get("githubOrg") != EXPECTED_ORG
        or meta.get("githubRepo") != EXPECTED_REPO
    ):
        return None
    sha = meta.get("githubCommitSha")
    if not isinstance(sha, str) or SHA_PATTERN.fullmatch(sha) is None:
        return None
    return sha


def fetch_production_sha(*, token: str, team_id: str, project_id: str) -> str | None:
    """Inspect the actual production hostname, not the most recent READY row."""
    url = (
        "https://api.vercel.com/v13/deployments/"
        + urllib.parse.quote(PRODUCTION_ALIAS, safe="")
        + "?"
        + urllib.parse.urlencode({"teamId": team_id})
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    return verified_sha(payload, project_id)


def main() -> int:
    """Emit a safe 40-character SHA only when every live-alias check passes."""
    token = os.environ.get("VERCEL_TOKEN", "")
    team_id = os.environ.get("VERCEL_ORG_ID", "")
    project_id = os.environ.get("VERCEL_PROJECT_ID", "")
    if not token or not team_id or not project_id:
        print("Vercel alias verification unavailable: configuration missing", file=sys.stderr)
        return 1
    try:
        sha = fetch_production_sha(token=token, team_id=team_id, project_id=project_id)
    except (OSError, ValueError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"Vercel alias verification unavailable: {type(exc).__name__}", file=sys.stderr)
        return 1
    if sha is None:
        print("Vercel alias did not verify as READY production at the expected project", file=sys.stderr)
        return 1
    print(sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
