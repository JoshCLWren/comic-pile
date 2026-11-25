#!/usr/bin/env python3
"""Recover release notes for merged, deployed pull requests the writer missed.

The Release writer workflow runs on merged ``pull_request_target`` events, but a
missed event, a model failure or a failed persistence step strands a release
permanently. This module provides the bounded recovery path:

``select``
    Inspect a bounded window of recently merged ``main`` pull requests, keep
    only those in the live production revision, and emit the oldest one with no
    release-ledger row (or nothing when every source is already recorded).
``verify-deployed``
    Re-check immediately before publication that the selected merge is still
    part of live production, so a rolled-back or failed deployment is never
    announced.
``ground-candidate``
    Classify a staged public candidate as internal when the complete merged diff
    changes only automated tests, so developer-only work never reaches readers.

Every operation is read-only outside the staged candidate file, bounded in the
number of GitHub requests it may make, and idempotent: the ledger insert stays
in the trusted publisher, which already treats a repeated source identity as a
no-op.
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

PRODUCTION_HEALTH_URL = "https://comic-pile.vercel.app/api/v2/health"
GITHUB_API_BASE = "https://api.github.com"
NATIVE_BUILD_PACKAGE = "comicpile-vercel-native"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")

# Bounded discovery: at most three pages of merged PRs and ten pages of changed
# files per run. Recovery therefore cannot become an unbounded historical
# rescan, and it stages at most one source per workflow run.
MAX_DISCOVERY_PAGES = 3
DISCOVERY_PAGE_SIZE = 100
MAX_CHANGED_FILE_PAGES = 10
CHANGED_FILE_PAGE_SIZE = 100
DEFAULT_LOOKBACK_HOURS = 72
MAX_LOOKBACK_HOURS = 168
MAX_CANDIDATE_BYTES = 32768

TEST_DIRECTORY_SEGMENTS = {"test", "tests", "tests_e2e", "__tests__"}
TEST_FILE_PATTERN = re.compile(
    r"(?:^test_.*\.py$|.*_test\.(?:py|rs|go)$|.*\.(?:test|spec)\.[cm]?[jt]sx?$)",
    re.IGNORECASE,
)


class RecoveryError(RuntimeError):
    """A deployment or ledger invariant prevented safe release recovery."""


@dataclass(frozen=True)
class Source:
    """Exact merged pull-request identity used by the release ledger."""

    number: int
    merged_at: str
    merge_commit_sha: str
    title: str


def _parse_timestamp(value: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp that must carry a timezone.

    Args:
        value: GitHub ``merged_at``/``updated_at`` timestamp.

    Returns:
        The timestamp normalized to UTC.

    Raises:
        RecoveryError: The timestamp is malformed or timezone-naive.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryError("GitHub timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RecoveryError("GitHub timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _read_json(request: urllib.request.Request) -> object:
    """Perform one bounded JSON GET.

    Args:
        request: Fully prepared request.

    Returns:
        The decoded JSON payload.

    Raises:
        RecoveryError: The request failed or did not return JSON.
    """
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RecoveryError(
            f"HTTP {exc.code} from release recovery source: {detail[:500]}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RecoveryError(f"Release recovery request failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Release recovery source returned invalid JSON") from exc


def _github_request(path: str) -> object:
    """Read one GitHub REST path with the workflow token when available."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ComicPile-release-recovery",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _read_json(
        urllib.request.Request(f"{GITHUB_API_BASE}{path}", headers=headers)
    )


def _repository_parts(repository: str) -> tuple[str, str]:
    """Split and URL-quote an ``owner/name`` repository identifier."""
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise RecoveryError("repository must use owner/name form")
    return (
        urllib.parse.quote(parts[0], safe=""),
        urllib.parse.quote(parts[1], safe=""),
    )


def _source_from_pull(item: object) -> Source | None:
    """Build a source from a merged pull-request payload, or None if unusable."""
    if not isinstance(item, dict):
        return None
    number = item.get("number")
    merged_at = item.get("merged_at")
    merge_sha = item.get("merge_commit_sha")
    title = item.get("title")
    base = item.get("base")
    if not isinstance(base, dict) or base.get("ref") != "main":
        return None
    if (
        not isinstance(number, int)
        or isinstance(number, bool)
        or number < 1
        or not isinstance(merged_at, str)
        or not isinstance(merge_sha, str)
        or SHA_PATTERN.fullmatch(merge_sha) is None
        or not isinstance(title, str)
    ):
        return None
    return Source(number, merged_at, merge_sha, title)


def _fetch_one(repository: str, number: int) -> Source:
    """Fetch the exact source identity for one merged pull request."""
    owner, name = _repository_parts(repository)
    source = _source_from_pull(
        _github_request(f"/repos/{owner}/{name}/pulls/{number}")
    )
    if source is None:
        raise RecoveryError(
            f"PR #{number} is not a merged main PR with valid source provenance"
        )
    return source


def _discover(repository: str, *, since_hours: int) -> list[Source]:
    """List merged main pull requests inside a bounded recent window.

    Args:
        repository: ``owner/name`` repository identifier.
        since_hours: Lookback in hours, bounded to 1..168.

    Returns:
        Merged sources ordered oldest first.

    Raises:
        RecoveryError: The window exceeded its page bound.
    """
    if since_hours < 1 or since_hours > MAX_LOOKBACK_HOURS:
        raise RecoveryError(
            f"recovery lookback must be between 1 and {MAX_LOOKBACK_HOURS} hours"
        )
    cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
    owner, name = _repository_parts(repository)
    merged: dict[int, Source] = {}
    for page in range(1, MAX_DISCOVERY_PAGES + 1):
        query = urllib.parse.urlencode(
            {
                "state": "closed",
                "base": "main",
                "sort": "updated",
                "direction": "desc",
                "per_page": DISCOVERY_PAGE_SIZE,
                "page": page,
            }
        )
        result = _github_request(f"/repos/{owner}/{name}/pulls?{query}")
        if not isinstance(result, list):
            raise RecoveryError("GitHub pull discovery response must be a list")
        last_updated: datetime | None = None
        for item in result:
            source = _source_from_pull(item)
            if source is not None and _parse_timestamp(source.merged_at) > cutoff:
                merged[source.number] = source
            if isinstance(item, dict) and isinstance(item.get("updated_at"), str):
                last_updated = _parse_timestamp(item["updated_at"])
        if len(result) < DISCOVERY_PAGE_SIZE or (
            last_updated is not None and last_updated <= cutoff
        ):
            break
    else:
        raise RecoveryError(
            "merged-PR discovery exceeded its bounded lookback; no source was selected"
        )
    return sorted(
        merged.values(),
        key=lambda source: (_parse_timestamp(source.merged_at), source.number),
    )


def _changed_files(
    repository: str,
    number: int,
) -> tuple[list[dict[str, object]], bool]:
    """Return a bounded changed-file response and whether it is complete."""
    owner, name = _repository_parts(repository)
    changed: list[dict[str, object]] = []
    for page in range(1, MAX_CHANGED_FILE_PAGES + 1):
        query = urllib.parse.urlencode(
            {"per_page": CHANGED_FILE_PAGE_SIZE, "page": page}
        )
        result = _github_request(f"/repos/{owner}/{name}/pulls/{number}/files?{query}")
        if not isinstance(result, list) or not all(
            isinstance(item, dict) for item in result
        ):
            raise RecoveryError("GitHub changed-file response must be an object list")
        changed.extend(result)
        if len(result) < CHANGED_FILE_PAGE_SIZE:
            return changed, True
    return changed, False


def _is_test_file(filename: str) -> bool:
    """Recognize conventional automated-test paths without product heuristics."""
    parts = [part for part in filename.split("/") if part]
    if not parts:
        return False
    if TEST_DIRECTORY_SEGMENTS.intersection(parts[:-1]):
        return True
    return TEST_FILE_PATTERN.fullmatch(parts[-1]) is not None


def production_revision(payload: object) -> str:
    """Return the native production build SHA from a healthy identity response.

    Args:
        payload: Decoded ``/api/v2/health`` response.

    Returns:
        The deployed revision SHA.

    Raises:
        RecoveryError: The response is not a healthy native build identity.
    """
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RecoveryError("production health response is not healthy")
    build = payload.get("build")
    if (
        not isinstance(build, dict)
        or build.get("package") != NATIVE_BUILD_PACKAGE
    ):
        raise RecoveryError("production health response lacks the native build identity")
    revision = build.get("revision")
    if not isinstance(revision, str) or SHA_PATTERN.fullmatch(revision) is None:
        raise RecoveryError(
            "production health response lacks a valid deployed revision"
        )
    return revision


def _fetch_production_revision() -> str:
    """Read the live production revision from the public health endpoint."""
    request = urllib.request.Request(
        PRODUCTION_HEALTH_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "ComicPile-release-recovery",
        },
    )
    return production_revision(_read_json(request))


def _git_ancestor(ancestor: str, descendant: str) -> bool:
    """Report whether ``ancestor`` is contained in ``descendant``.

    Raises:
        RecoveryError: Git could not answer the ancestry question.
    """
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RecoveryError(f"git ancestry check failed: {result.stderr.strip()[:300]}")


def deployed_sources(
    sources: Sequence[Source],
    live_sha: str,
    *,
    is_ancestor: Callable[[str, str], bool],
) -> list[Source]:
    """Keep only merged PRs included in the actual live production revision."""
    return [source for source in sources if is_ancestor(source.merge_commit_sha, live_sha)]


def select_missing_source(
    sources: Sequence[Source],
    existing_rows: Sequence[tuple[int | None, str | None]],
) -> Source | None:
    """Select the oldest source without a ledger row.

    Args:
        sources: Deployed merged sources ordered oldest first.
        existing_rows: ``(source_pr_number, source_merge_sha)`` ledger pairs.

    Returns:
        The oldest absent source, or None when every source is recorded.

    Raises:
        RecoveryError: Existing provenance is ambiguous for one source.
    """
    for source in sources:
        related = [
            row
            for row in existing_rows
            if row[0] == source.number or row[1] == source.merge_commit_sha
        ]
        if not related:
            return source
        if len(related) != 1 or related[0] != (source.number, source.merge_commit_sha):
            raise RecoveryError(
                f"release-ledger provenance conflict for PR #{source.number}"
            )
    return None


def _existing_source_rows(
    repository: str,
    sources: Sequence[Source],
) -> list[tuple[int | None, str | None]]:
    """Read release-ledger provenance for the candidate sources.

    The connection is read-only so discovery can never write the ledger.

    Args:
        repository: ``owner/name`` repository identifier.
        sources: Candidate sources from the same discovery pass.

    Returns:
        ``(source_pr_number, source_merge_sha)`` pairs for matching rows.

    Raises:
        RecoveryError: The DSN is missing or the lookup returned invalid rows.
    """
    dsn = os.getenv("RELEASE_NEON_DATABASE_URL", "").strip()
    if not dsn:
        raise RecoveryError("RELEASE_NEON_DATABASE_URL is required for ledger discovery")
    # psycopg is installed only in the trusted publisher job, so it is imported
    # lazily to keep this module importable for offline tests and linting.
    psycopg = importlib.import_module("psycopg")
    numbers = [source.number for source in sources]
    shas = [source.merge_commit_sha for source in sources]
    with psycopg.connect(
        dsn,
        connect_timeout=15,
        options="-c default_transaction_read_only=on",
    ) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_pr_number, source_merge_sha
            FROM releases
            WHERE source_repository = %s
              AND (
                  source_pr_number = ANY(%s::integer[])
                  OR source_merge_sha = ANY(%s::text[])
              )
            """,
            (repository, numbers, shas),
        )
        raw_rows = cursor.fetchall()
    rows: list[tuple[int | None, str | None]] = []
    for row in raw_rows:
        number, sha = row
        if (number is not None and (not isinstance(number, int) or isinstance(number, bool))) or (
            sha is not None and not isinstance(sha, str)
        ):
            raise RecoveryError(
                "release-ledger lookup returned invalid source provenance"
            )
        rows.append((number, sha))
    return rows


def ground_candidate(
    payload: dict[str, object],
    *,
    repository: str,
    pr_number: int,
    changed_files: Callable[[str, int], tuple[list[dict[str, object]], bool]],
) -> tuple[dict[str, object], bool]:
    """Convert a complete test-only public candidate into an internal skip.

    The trusted publisher supplies the changed-file loader. Incomplete bounded
    responses are never treated as proof that no product file changed.

    Args:
        payload: Staged release candidate.
        repository: ``owner/name`` repository identifier.
        pr_number: Selected pull-request number.
        changed_files: Loader returning a file page and whether it is complete.

    Returns:
        The (possibly rewritten) candidate and whether it was rewritten.

    Raises:
        RecoveryError: The candidate does not match the selected source.
    """
    if payload.get("source_repository") != repository or payload.get(
        "source_pr_number"
    ) != pr_number:
        raise RecoveryError("candidate does not match the selected source")
    if (
        payload.get("visibility", "public") != "public"
        or payload.get("status", "published") != "published"
    ):
        return payload, False

    changed, complete = changed_files(repository, pr_number)
    filenames = [item.get("filename") for item in changed]
    if (
        not complete
        or not changed
        or not all(isinstance(name, str) and name for name in filenames)
        or not all(_is_test_file(name) for name in filenames if isinstance(name, str))
    ):
        return payload, False

    grounded = copy.deepcopy(payload)
    reason = (
        "The complete merged diff changes only automated tests; "
        "no reader-facing product behavior changed."
    )
    grounded.update(
        {
            "category": "Internal",
            "title": f"Internal change (PR #{pr_number})",
            "summary": reason,
            "body": None,
            "visibility": "internal",
        }
    )
    provenance = grounded.get("provenance_json")
    if not isinstance(provenance, dict):
        raise RecoveryError("public candidate provenance must be an object")
    provenance.update(
        {
            "classification": "internal",
            "reason": reason,
            "classification_reason": reason,
            "reader_reachable": False,
            "user_visible_evidence": "",
            "internal_engineering_terms": ["test-only merged diff"],
        }
    )
    provenance.pop("reader_reachable_path", None)
    return grounded, True


def _write_outputs(outputs: dict[str, object]) -> None:
    """Write step outputs to ``GITHUB_OUTPUT`` and mirror them to stdout."""
    rendered = {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in outputs.items()
    }
    destination = os.getenv("GITHUB_OUTPUT", "").strip()
    if destination:
        with Path(destination).open("a", encoding="utf-8") as output:
            for key, value in rendered.items():
                output.write(f"{key}={value}\n")
    print(json.dumps(rendered, separators=(",", ":"), sort_keys=True))


def _verified_live_revision() -> str:
    """Return live production's revision after proving it is on trusted main."""
    live_sha = _fetch_production_revision()
    if not _git_ancestor(live_sha, "HEAD"):
        raise RecoveryError("production revision is not on the trusted main history")
    return live_sha


def _select(args: argparse.Namespace) -> int:
    """Select at most one deployed merged PR that has no ledger row."""
    live_sha = _verified_live_revision()
    sources = (
        [_fetch_one(args.repository, args.pr)]
        if args.pr is not None
        else _discover(args.repository, since_hours=args.since_hours)
    )
    deployed = deployed_sources(sources, live_sha, is_ancestor=_git_ancestor)
    outputs: dict[str, object] = {
        "needed": False,
        "pr_number": "",
        "merge_sha": "",
        "live_sha": live_sha,
        "deployed_sources": len(deployed),
    }
    if args.pr is not None and not deployed:
        outputs["reason"] = "awaiting_deployment"
        _write_outputs(outputs)
        return 0
    if not deployed:
        outputs["reason"] = "no_deployed_merged_prs"
        _write_outputs(outputs)
        return 0

    selected = select_missing_source(
        deployed, _existing_source_rows(args.repository, deployed)
    )
    if selected is None:
        outputs["reason"] = "already_present"
    else:
        outputs.update(
            {
                "needed": True,
                "pr_number": selected.number,
                "merge_sha": selected.merge_commit_sha,
                "reason": "selected",
            }
        )
    _write_outputs(outputs)
    return 0


def _verify_deployed(args: argparse.Namespace) -> int:
    """Refuse publication unless the merged PR is still in live production."""
    if SHA_PATTERN.fullmatch(args.merge_sha) is None:
        raise RecoveryError("merge SHA must be a full lowercase Git commit SHA")
    live_sha = _verified_live_revision()
    if not _git_ancestor(args.merge_sha, live_sha):
        raise RecoveryError(
            "refusing publication: merged PR is not in live production"
        )
    _write_outputs(
        {"live_sha": live_sha, "merge_sha": args.merge_sha, "deployed": True}
    )
    return 0


def _ground_candidate(args: argparse.Namespace) -> int:
    """Apply test-only grounding to the staged candidate file."""
    path: Path = args.candidate
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CANDIDATE_BYTES:
            raise RecoveryError("invalid or oversized release candidate")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("release candidate is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise RecoveryError("release candidate must be an object")
    grounded, changed = ground_candidate(
        payload,
        repository=args.repository,
        pr_number=args.pr,
        changed_files=_changed_files,
    )
    if changed:
        try:
            path.write_text(
                json.dumps(grounded, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise RecoveryError("grounded release candidate could not be written") from exc
    _write_outputs(
        {
            "pr_number": args.pr,
            "grounded_internal": changed,
            "visibility": grounded.get("visibility", "public"),
        }
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    """Build the recovery command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser(
        "select", help="select one missing deployed ledger source"
    )
    select.add_argument("--repository", required=True)
    select.add_argument("--pr", type=int)
    select.add_argument("--since-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    select.set_defaults(handler=_select)
    verify = commands.add_parser(
        "verify-deployed", help="require a merge SHA in live production"
    )
    verify.add_argument("--merge-sha", required=True)
    verify.set_defaults(handler=_verify_deployed)
    ground = commands.add_parser(
        "ground-candidate",
        help="classify a complete test-only merged diff as internal",
    )
    ground.add_argument("--candidate", required=True, type=Path)
    ground.add_argument("--repository", required=True)
    ground.add_argument("--pr", required=True, type=int)
    ground.set_defaults(handler=_ground_candidate)
    return parser


def main() -> int:
    """Run the requested deployment-gated recovery operation."""
    args = _parser().parse_args()
    if getattr(args, "pr", None) is not None and args.pr < 1:
        raise RecoveryError("PR number must be positive")
    return int(args.handler(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryError as error:
        print(f"release recovery failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
