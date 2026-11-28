#!/usr/bin/env python3
"""Recover release notes for merged, deployed pull requests the writer missed.

The Release writer normally runs once per merged PR. A missed event, a failed
generation, or a failed Neon persistence step can strand a note permanently.
This module provides the bounded, event-driven recovery path:

``select``
    Read a bounded window of recently merged ``main`` pull requests, keep only
    merges contained in the live production revision, and emit the oldest one
    with no release-ledger row (or ``needed=false`` when nothing is missing).
``verify-deployed``
    Re-prove immediately before publication that the selected merge is still
    part of live production, so a rollback or a failed deploy is never
    announced.
``ground-candidate``
    Record a complete test-only merged diff as an internal outcome, so
    developer-only work neither reaches readers nor blocks recovery forever.

Discovery is read-only, bounded (no schedule and no unbounded historical
rescan), and idempotent: the trusted publisher remains the only ledger writer
and treats a repeated source identity as a no-op.
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
PRODUCTION_HEALTH_HOST = urllib.parse.urlsplit(PRODUCTION_HEALTH_URL).hostname or ""
GITHUB_API_HOST = urllib.parse.urlsplit(GITHUB_API_BASE).hostname or ""
GITHUB_API_URL_KIND = "GitHub API URL"
PRODUCTION_HEALTH_URL_KIND = "production health URL"
GENERIC_URL_KIND = "release recovery URL"
NATIVE_BUILD_PACKAGE = "comicpile-vercel-native"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DEFAULT_LOOKBACK_HOURS = 72
MAX_LOOKBACK_HOURS = 168
MAX_DISCOVERY_PAGES = 3
DISCOVERY_PAGE_SIZE = 100
MAX_CANDIDATE_BYTES = 32768
TEST_DIRECTORY_SEGMENTS = {"test", "tests", "tests_e2e", "__tests__"}
TEST_FILE_PATTERN = re.compile(
    r"(?:^test_.*\.py$|.*_test\.(?:py|rs|go)$|.*\.(?:test|spec)\.[cm]?[jt]sx?$)",
    re.IGNORECASE,
)

JsonObject = dict[str, object]
FetchJson = Callable[[str], object]
AncestorCheck = Callable[[str, str], bool]
LedgerLookup = Callable[
    [str, list[int], list[str]], list[tuple[int | None, str | None]]
]


class RecoveryError(RuntimeError):
    """A deployment, provenance, or ledger invariant prevented safe recovery."""


@dataclass(frozen=True)
class Source:
    """Exact merged pull-request identity used by the release ledger."""

    number: int
    merged_at: str
    merge_commit_sha: str
    title: str


def _as_object(value: object, label: str) -> JsonObject:
    """Narrow a decoded JSON value to an object.

    Args:
        value: Decoded JSON value.
        label: Human-readable label used in the error message.

    Returns:
        The JSON object.

    Raises:
        RecoveryError: The value is not a JSON object.
    """
    if not isinstance(value, dict):
        raise RecoveryError(f"{label} must be a JSON object")
    return value


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


def _url_kind(url: str) -> str:
    """Classify a recovery URL as a coarse, secret-free label for errors.

    Args:
        url: Absolute request URL.

    Returns:
        ``production health URL``, ``GitHub API URL``, or a generic label.
        The URL itself is never included, because it may carry a token.
    """
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return GENERIC_URL_KIND
    if host == GITHUB_API_HOST:
        return GITHUB_API_URL_KIND
    if host == PRODUCTION_HEALTH_HOST:
        return PRODUCTION_HEALTH_URL_KIND
    return GENERIC_URL_KIND


def _validate_request_url(url: str, kind: str) -> None:
    """Reject a malformed URL before it reaches the network.

    Args:
        url: Absolute HTTP(S) URL.
        kind: Coarse URL label used in the error.

    Raises:
        RecoveryError: The URL has no usable scheme, host, or valid port.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        _ = parsed.port  # Raises ValueError for a non-numeric port.
    except ValueError:
        raise RecoveryError(f"{kind} URL is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RecoveryError(f"{kind} URL is invalid")


def _is_github_api_url(url: str) -> bool:
    """Report whether a URL targets the canonical GitHub API host.

    Args:
        url: Absolute URL supplied by a caller or an injected loader.

    Returns:
        ``True`` only for a credential-free HTTPS URL on ``api.github.com``.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == GITHUB_API_HOST
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _read_json(
    request: urllib.request.Request, source_name: str | None = None
) -> object:
    """Perform one bounded JSON GET.

    Args:
        request: Fully prepared request.
        source_name: Optional coarse URL label override used in errors.

    Returns:
        The decoded JSON payload.

    Raises:
        RecoveryError: The URL is malformed, the request failed, or the
            response is not valid JSON. Errors name the URL kind, never the
            URL itself, because URLs may carry credentials.
    """
    kind = source_name or _url_kind(request.full_url)
    _validate_request_url(request.full_url, kind)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RecoveryError(f"HTTP {exc.code} from {kind}: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise RecoveryError(
            f"Release recovery request failed for {kind}: {reason}"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"{kind} returned invalid JSON") from exc


def _read_url_json(
    url: str, source_name: str = PRODUCTION_HEALTH_URL_KIND
) -> object:
    """Read one JSON document from an absolute URL.

    Args:
        url: Absolute HTTP URL.
        source_name: Optional coarse URL label override used in errors.

    Returns:
        The decoded JSON payload.
    """
    return _read_json(
        urllib.request.Request(url, headers={"Accept": "application/json"}),
        source_name=source_name,
    )


def _github_request(path_or_url: str) -> object:
    """Read one GitHub REST path or absolute API URL with the workflow token.

    Callers pass either a REST path (``/repos/...``) or the absolute URL built
    by discovery. Accepting both prevents double-prefixing ``GITHUB_API_BASE``,
    which used to request the unresolvable host ``api.github.comhttps``.

    Args:
        path_or_url: REST path beginning with ``/`` or an absolute GitHub API URL.

    Returns:
        The decoded GitHub response.

    Raises:
        RecoveryError: An absolute URL does not target the GitHub API host.
    """
    if path_or_url.startswith("/"):
        url = f"{GITHUB_API_BASE}{path_or_url}"
    elif _is_github_api_url(path_or_url):
        url = path_or_url
    else:
        raise RecoveryError("GitHub API URL is invalid")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ComicPile-release-recovery",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _read_json(
        urllib.request.Request(url, headers=headers),
        source_name=GITHUB_API_URL_KIND,
    )


def _repository_parts(repository: str) -> tuple[str, str]:
    """Split and URL-quote an ``owner/name`` repository identifier.

    Args:
        repository: ``owner/name`` repository identifier.

    Returns:
        The quoted owner and name.

    Raises:
        RecoveryError: The identifier is not in ``owner/name`` form.
    """
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise RecoveryError("repository must use owner/name form")
    return (
        urllib.parse.quote(parts[0], safe=""),
        urllib.parse.quote(parts[1], safe=""),
    )


def _source_from_pull(item: object) -> Source | None:
    """Build a merged main source from a pull payload, or ``None``.

    Args:
        item: One GitHub pull response item.

    Returns:
        The exact source identity when the pull has usable provenance.
    """
    if not isinstance(item, dict):
        return None
    base = item.get("base")
    number = item.get("number")
    merged_at = item.get("merged_at")
    merge_sha = item.get("merge_commit_sha")
    title = item.get("title")
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


def _fetch_one(
    repository: str,
    number: int,
    request_json: FetchJson = _github_request,
) -> Source:
    """Fetch the exact source identity for one merged pull request.

    Args:
        repository: ``owner/name`` repository identifier.
        number: Pull request number.
        request_json: Injectable JSON loader.

    Returns:
        The merged source identity.

    Raises:
        RecoveryError: The pull is not a merged main PR with valid provenance.
    """
    owner, name = _repository_parts(repository)
    source = _source_from_pull(
        request_json(f"{GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{number}")
    )
    if source is None:
        raise RecoveryError(
            f"PR #{number} is not a merged main PR with valid source provenance"
        )
    return source


def _discover(
    repository: str,
    *,
    since_hours: int,
    request_json: FetchJson = _github_request,
) -> list[Source]:
    """List merged main pull requests inside a bounded recent window.

    Args:
        repository: ``owner/name`` repository identifier.
        since_hours: Lookback in hours, bounded to 1..168.
        request_json: Injectable JSON loader.

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
        result = request_json(f"{GITHUB_API_BASE}/repos/{owner}/{name}/pulls?{query}")
        if not isinstance(result, list):
            raise RecoveryError("GitHub pull discovery response must be a list")
        last_updated: datetime | None = None
        for item in result:
            source = _source_from_pull(item)
            if source is not None and _parse_timestamp(source.merged_at) > cutoff:
                merged[source.number] = source
            if isinstance(item, dict) and isinstance(item.get("updated_at"), str):
                last_updated = _parse_timestamp(str(item["updated_at"]))
        if len(result) < DISCOVERY_PAGE_SIZE or (
            last_updated is not None and last_updated <= cutoff
        ):
            break
    else:
        raise RecoveryError(
            "merged-PR discovery exceeded its bounded lookback; no source selected"
        )
    return sorted(
        merged.values(),
        key=lambda source: (_parse_timestamp(source.merged_at), source.number),
    )


def production_revision(payload: object) -> str:
    """Return the native production revision from a healthy identity response.

    Args:
        payload: Decoded ``/api/v2/health`` response.

    Returns:
        The deployed revision SHA.

    Raises:
        RecoveryError: The response is not a healthy native build identity.
    """
    body = _as_object(payload, "production health response")
    if body.get("status") != "ok":
        raise RecoveryError("production health response is not healthy")
    build = _as_object(body.get("build"), "production build identity")
    if build.get("package") != NATIVE_BUILD_PACKAGE:
        raise RecoveryError("production health response lacks the native build identity")
    revision = build.get("revision")
    if not isinstance(revision, str) or SHA_PATTERN.fullmatch(revision) is None:
        raise RecoveryError("production health response lacks a valid deployed revision")
    return revision


def fetch_production_revision(
    health_url: str = PRODUCTION_HEALTH_URL,
    fetch_json: FetchJson = _read_url_json,
) -> str:
    """Read the live production revision from the public health endpoint.

    Args:
        health_url: Production health URL.
        fetch_json: Injectable JSON loader.

    Returns:
        The deployed revision SHA.
    """
    return production_revision(fetch_json(health_url))


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    """Report whether one git commit is contained in another.

    Args:
        ancestor: Candidate merge commit SHA.
        descendant: Deployed revision SHA.

    Returns:
        ``True`` when the merge is in the deployed revision.

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
    is_ancestor: AncestorCheck = git_is_ancestor,
) -> list[Source]:
    """Keep only merged PRs contained in the actual live production revision.

    Args:
        sources: Merged sources from a bounded discovery pass.
        live_sha: Deployed revision SHA.
        is_ancestor: Injectable ancestry check.

    Returns:
        Deployed sources in their original order.
    """
    return [source for source in sources if is_ancestor(source.merge_commit_sha, live_sha)]


def verify_deployed(
    merge_sha: str,
    *,
    health_url: str = PRODUCTION_HEALTH_URL,
    fetch_revision: Callable[[str], str] = fetch_production_revision,
    is_ancestor: AncestorCheck = git_is_ancestor,
) -> str:
    """Re-prove a merge is live in production before using a database credential.

    Args:
        merge_sha: Merge commit SHA being published.
        health_url: Production health URL.
        fetch_revision: Injectable deployed-revision loader.
        is_ancestor: Injectable ancestry check.

    Returns:
        The deployed revision SHA.

    Raises:
        RecoveryError: Production is unhealthy or no longer contains the merge.
    """
    live_sha = fetch_revision(health_url)
    if not is_ancestor(merge_sha, live_sha):
        raise RecoveryError(
            f"merge {merge_sha} is not contained in deployed revision {live_sha}"
        )
    return live_sha


def select_missing_source(
    sources: Sequence[Source],
    existing_rows: Sequence[tuple[int | None, str | None]],
) -> Source | None:
    """Select the oldest deployed source without a ledger row.

    Args:
        sources: Deployed merged sources ordered oldest first.
        existing_rows: ``(source_pr_number, source_merge_sha)`` ledger pairs.

    Returns:
        The oldest absent source, or ``None`` when every source is recorded.

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


def _lookup_existing_rows(
    repository: str,
    numbers: list[int],
    shas: list[str],
) -> list[tuple[int | None, str | None]]:
    """Read matching source identities from the ledger in a read-only transaction.

    Args:
        repository: ``owner/name`` repository identifier.
        numbers: Candidate pull request numbers.
        shas: Candidate merge commit SHAs.

    Returns:
        Existing ``(source_pr_number, source_merge_sha)`` pairs.

    Raises:
        RecoveryError: The DSN is missing or a row has invalid provenance.
    """
    dsn = os.getenv("RELEASE_NEON_DATABASE_URL", "").strip()
    if not dsn:
        raise RecoveryError("RELEASE_NEON_DATABASE_URL is required for ledger discovery")
    # Imported lazily so discovery stays importable without the publisher's
    # database dependency; only the trusted recovery job installs psycopg.
    psycopg = importlib.import_module("psycopg")
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


def select_sources(
    repository: str,
    *,
    since_hours: int = DEFAULT_LOOKBACK_HOURS,
    pr_number: int | None = None,
    request_json: FetchJson = _github_request,
    fetch_revision: Callable[[], str] = fetch_production_revision,
    is_ancestor: AncestorCheck = git_is_ancestor,
    lookup: LedgerLookup = _lookup_existing_rows,
) -> JsonObject:
    """Discover the oldest merged, deployed, unrecorded source.

    Args:
        repository: ``owner/name`` repository identifier.
        since_hours: Bounded discovery lookback in hours.
        pr_number: Restrict selection to one exact merged PR when supplied.
        request_json: Injectable GitHub JSON loader.
        fetch_revision: Injectable production revision loader.
        is_ancestor: Injectable ancestry check.
        lookup: Injectable ledger provenance lookup.

    Returns:
        A summary with ``needed`` and exact source identity outputs.
    """
    if pr_number is not None and pr_number < 1:
        raise RecoveryError("--pr must be positive")
    live_sha = fetch_revision()
    if pr_number is not None:
        candidates = [_fetch_one(repository, pr_number, request_json)]
    else:
        candidates = _discover(repository, since_hours=since_hours, request_json=request_json)
    deployed = deployed_sources(candidates, live_sha, is_ancestor)
    numbers = [source.number for source in deployed]
    shas = [source.merge_commit_sha for source in deployed]
    existing = lookup(repository, numbers, shas)
    missing = select_missing_source(deployed, existing)
    missing_sources = [
        source
        for source in deployed
        if not any(row == (source.number, source.merge_commit_sha) for row in existing)
    ]
    return {
        "needed": missing is not None,
        "pr_number": missing.number if missing else None,
        "merge_sha": missing.merge_commit_sha if missing else None,
        "deployed_revision": live_sha,
        "candidates": len(candidates),
        "deployed_candidates": len(deployed),
        "missing_count": len(missing_sources),
        "missing_pr_numbers": [source.number for source in missing_sources],
    }


def is_test_file(filename: str) -> bool:
    """Recognize conventional automated-test paths without product heuristics.

    Args:
        filename: Changed file path from the merged diff.

    Returns:
        ``True`` when the path is an automated test file.
    """
    parts = [part for part in filename.split("/") if part]
    if not parts:
        return False
    if TEST_DIRECTORY_SEGMENTS.intersection(parts[:-1]):
        return True
    return TEST_FILE_PATTERN.fullmatch(parts[-1]) is not None


def _changed_files(
    repository: str,
    number: int,
    request_json: FetchJson = _github_request,
) -> tuple[list[JsonObject], bool]:
    """Return a bounded changed-file response and whether it was complete.

    Args:
        repository: ``owner/name`` repository identifier.
        number: Pull request number.
        request_json: Injectable JSON loader.

    Returns:
        The changed-file objects and a completeness flag.
    """
    owner, name = _repository_parts(repository)
    query = urllib.parse.urlencode({"per_page": 100, "page": 1})
    result = request_json(
        f"{GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{number}/files?{query}"
    )
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise RecoveryError("GitHub changed-file response must be an object list")
    # The writer validates at most 100 files; never treat a truncated response
    # as proof that no product file changed.
    return result, len(result) < 100


def ground_candidate(
    payload: JsonObject,
    *,
    repository: str,
    pr_number: int,
    changed_files: Callable[[str, int], tuple[list[JsonObject], bool]],
) -> tuple[JsonObject, bool]:
    """Convert a complete test-only public candidate into an internal outcome.

    Args:
        payload: Staged release candidate.
        repository: ``owner/name`` repository identifier.
        pr_number: Selected pull request number.
        changed_files: Loader returning changed files and a completeness flag.

    Returns:
        The possibly rewritten candidate and whether it was rewritten.

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
        or not all(is_test_file(str(name)) for name in filenames)
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
            "status": "published",
        }
    )
    provenance = grounded.get("provenance_json")
    if not isinstance(provenance, dict):
        raise RecoveryError("public candidate provenance must be an object")
    provenance.update(
        {
            "classification": "internal",
            "classification_reason": reason,
            "reason": reason,
            "reader_reachable": False,
            "user_visible_evidence": "",
            "internal_engineering_terms": ["test-only merged diff"],
        }
    )
    provenance.pop("reader_reachable_path", None)
    return grounded, True


def _write_outputs(outputs: JsonObject) -> None:
    """Write step outputs to ``GITHUB_OUTPUT`` and mirror them to stdout.

    Args:
        outputs: Mapping of output names to values.
    """
    rendered: dict[str, str] = {}
    for key, value in outputs.items():
        if isinstance(value, bool):
            rendered[key] = str(value).lower()
        elif isinstance(value, (list, dict)):
            rendered[key] = json.dumps(value, separators=(",", ":"))
        else:
            rendered[key] = str(value)
    destination = os.getenv("GITHUB_OUTPUT", "").strip()
    if destination:
        with Path(destination).open("a", encoding="utf-8") as output:
            for key, value in rendered.items():
                output.write(f"{key}={value}\n")
    print(json.dumps(rendered, sort_keys=True))


def _load_candidate(path: Path) -> JsonObject:
    """Load a bounded staged candidate from disk.

    Args:
        path: Candidate JSON path.

    Returns:
        The candidate object.

    Raises:
        RecoveryError: The candidate is missing, oversized, or not an object.
    """
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CANDIDATE_BYTES:
        raise RecoveryError("invalid or oversized release candidate")
    try:
        return _as_object(json.loads(path.read_text(encoding="utf-8")), "candidate")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("release candidate is not valid JSON") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--repository", required=True)
    select_parser.add_argument("--pr", type=int)
    select_parser.add_argument(
        "--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS
    )
    select_parser.add_argument("--health-url", default=PRODUCTION_HEALTH_URL)

    verify_parser = subparsers.add_parser("verify-deployed")
    verify_parser.add_argument("--repository")
    verify_parser.add_argument("--pr", type=int)
    verify_parser.add_argument("--merge-sha")
    verify_parser.add_argument("--health-url", default=PRODUCTION_HEALTH_URL)

    ground_parser = subparsers.add_parser("ground-candidate")
    ground_parser.add_argument("--candidate", required=True, type=Path)
    ground_parser.add_argument("--repository", required=True)
    ground_parser.add_argument("--pr", required=True, type=int)
    return parser


def main() -> int:
    """Run one bounded release recovery operation."""
    args = _parser().parse_args()
    try:
        if args.command == "select":
            summary = select_sources(
                args.repository,
                since_hours=args.lookback_hours,
                pr_number=args.pr,
                fetch_revision=lambda: fetch_production_revision(args.health_url),
            )
            _write_outputs(summary)
            return 0

        if args.command == "verify-deployed":
            if not args.repository and not args.merge_sha:
                raise RecoveryError("--repository --pr or --merge-sha is required")
            merge_sha = args.merge_sha
            if args.repository:
                if not args.pr or args.pr < 1:
                    raise RecoveryError("--pr must be positive with --repository")
                merge_sha = _fetch_one(args.repository, args.pr).merge_commit_sha
            if not isinstance(merge_sha, str) or SHA_PATTERN.fullmatch(merge_sha) is None:
                raise RecoveryError("a valid merge SHA is required")
            live_sha = verify_deployed(merge_sha, health_url=args.health_url)
            print(json.dumps({"merge_sha": merge_sha, "deployed_revision": live_sha}))
            return 0

        payload = _load_candidate(args.candidate)
        grounded, rewritten = ground_candidate(
            payload,
            repository=args.repository,
            pr_number=args.pr,
            changed_files=_changed_files,
        )
        if rewritten:
            args.candidate.write_text(
                json.dumps(grounded, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps({"rewritten": rewritten}))
        return 0
    except RecoveryError as exc:
        # Emit machine-readable failure outputs so the workflow summary can
        # still report the URL kind and that no source was selected. The text
        # is safe by construction (URL kinds only, no raw URLs or secrets) and
        # is flattened to one line for GITHUB_OUTPUT.
        _write_outputs(
            {
                "needed": False,
                "selection_error": " ".join(str(exc).split()),
                "missing_pr_numbers": [],
            }
        )
        print(f"release recovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
