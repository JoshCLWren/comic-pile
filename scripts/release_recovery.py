#!/usr/bin/env python3
"""Select deployed merged PRs whose exact release-ledger source is missing."""

from __future__ import annotations

import argparse
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

_PRODUCTION_HEALTH_URL = "https://comic-pile.vercel.app/api/v2/health"
_GITHUB_API_BASE = "https://api.github.com"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_MAX_DISCOVERY_PAGES = 3
_DISCOVERY_PAGE_SIZE = 100
# Bounded changed-file page used by `changed_file_names`; a full page may be truncated.
_CHANGED_FILES_PAGE_SIZE = 100
# Test-only paths (`tests/`/`test/` directories, `*.test.*`/`*.spec.*` files). A
# complete bounded file list consisting solely of these proves a developer-only
# diff, which can never be published as a public reader-facing note.
_TEST_FILE_PATTERN = re.compile(
    r"(?:^|/)(?:tests?|__tests__)(?:/|$)|\.(?:test|spec)\.[^/]+$",
    re.IGNORECASE,
)
_MAX_CANDIDATE_BYTES = 32768


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
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RecoveryError("GitHub timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _read_json(request: urllib.request.Request) -> object:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RecoveryError(f"HTTP {exc.code} from release recovery source: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RecoveryError(f"Release recovery request failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Release recovery source returned invalid JSON") from exc


def _github_request(path: str) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ComicPile-release-recovery",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _read_json(urllib.request.Request(f"{_GITHUB_API_BASE}{path}", headers=headers))


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise RecoveryError("repository must use owner/name form")
    return (
        urllib.parse.quote(parts[0], safe=""),
        urllib.parse.quote(parts[1], safe=""),
    )


def _source_from_pull(item: object) -> Source | None:
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
        or _SHA_PATTERN.fullmatch(merge_sha) is None
        or not isinstance(title, str)
    ):
        return None
    return Source(number, merged_at, merge_sha, title)


def _fetch_one(repository: str, number: int) -> Source:
    owner, name = _repository_parts(repository)
    source = _source_from_pull(_github_request(f"/repos/{owner}/{name}/pulls/{number}"))
    if source is None:
        raise RecoveryError(f"PR #{number} is not a merged main PR with valid source provenance")
    return source


def _discover(repository: str, *, since_hours: int) -> list[Source]:
    if since_hours < 1 or since_hours > 168:
        raise RecoveryError("recovery lookback must be between 1 and 168 hours")
    cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
    owner, name = _repository_parts(repository)
    merged: dict[int, Source] = {}
    for page in range(1, _MAX_DISCOVERY_PAGES + 1):
        query = urllib.parse.urlencode(
            {
                "state": "closed",
                "base": "main",
                "sort": "updated",
                "direction": "desc",
                "per_page": _DISCOVERY_PAGE_SIZE,
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
                last_updated = _parse_timestamp(str(item["updated_at"]))
        if len(result) < _DISCOVERY_PAGE_SIZE or (
            last_updated is not None and last_updated <= cutoff
        ):
            break
    else:
        raise RecoveryError(
            "merged-PR discovery exceeded its bounded lookback; no source was selected"
        )
    return sorted(merged.values(), key=lambda source: (_parse_timestamp(source.merged_at), source.number))


def production_revision(payload: object) -> str:
    """Return the native production build SHA only from a healthy identity response."""
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RecoveryError("production health response is not healthy")
    build = payload.get("build")
    if not isinstance(build, dict) or build.get("package") != "comicpile-vercel-native":
        raise RecoveryError("production health response lacks the native build identity")
    revision = build.get("revision")
    if not isinstance(revision, str) or _SHA_PATTERN.fullmatch(revision) is None:
        raise RecoveryError("production health response lacks a valid deployed revision")
    return revision


def _fetch_production_revision() -> str:
    request = urllib.request.Request(
        _PRODUCTION_HEALTH_URL,
        headers={"Accept": "application/json", "User-Agent": "ComicPile-release-recovery"},
    )
    return production_revision(_read_json(request))


def _git_ancestor(ancestor: str, descendant: str) -> bool:
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
    """Select the oldest absent source, failing on ambiguous existing provenance."""
    for source in sources:
        related = [
            row
            for row in existing_rows
            if row[0] == source.number or row[1] == source.merge_commit_sha
        ]
        if not related:
            return source
        if len(related) != 1 or related[0] != (source.number, source.merge_commit_sha):
            raise RecoveryError(f"release-ledger provenance conflict for PR #{source.number}")
    return None


def is_public_publication(payload: object) -> bool:
    """Return True when a candidate defaults to a public, published note."""
    return (
        isinstance(payload, dict)
        and payload.get("visibility", "public") == "public"
        and payload.get("status", "published") == "published"
    )


def test_only_public_violation(payload: object, filenames: Sequence[str]) -> str | None:
    """Return a blocking message when a complete test-only diff is public.

    A full changed-file page may be truncated, so only a strictly smaller,
    non-empty list proves that every changed file is a test file. Provenance
    prose cannot override this: developer-only work is never reader-facing.

    Args:
        payload: Staged release candidate payload.
        filenames: Changed-file names from one bounded GitHub page.

    Returns:
        The blocking message, or None when the candidate stays eligible.
    """
    if not is_public_publication(payload):
        return None
    if not 0 < len(filenames) < _CHANGED_FILES_PAGE_SIZE:
        return None
    if all(_TEST_FILE_PATTERN.search(name) for name in filenames):
        return (
            "merged diff changes only test files; classify this change as "
            "internal instead of publishing a public reader-facing note"
        )
    return None


def changed_file_names(repository: str, number: int) -> list[str]:
    """Return the bounded changed-file names for one pull request.

    Args:
        repository: Owner/name repository string.
        number: Pull request number.

    Returns:
        The changed-file names from one bounded GitHub page.

    Raises:
        RecoveryError: When the GitHub response is not a valid file list.
    """
    owner, name = _repository_parts(repository)
    query = urllib.parse.urlencode({"per_page": _CHANGED_FILES_PAGE_SIZE})
    result = _github_request(f"/repos/{owner}/{name}/pulls/{number}/files?{query}")
    if not isinstance(result, list):
        raise RecoveryError("GitHub changed-file response must be a list")
    filenames: list[str] = []
    for item in result:
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
            raise RecoveryError("GitHub changed-file response returned an invalid entry")
        filenames.append(item["filename"])
    return filenames


def _read_candidate(path: str) -> object:
    candidate = Path(path)
    if (
        candidate.is_symlink()
        or not candidate.is_file()
        or candidate.stat().st_size > _MAX_CANDIDATE_BYTES
    ):
        raise RecoveryError("invalid or oversized release candidate")
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("release candidate is not valid JSON") from exc


def _verify_public(args: argparse.Namespace) -> int:
    payload = _read_candidate(args.candidate)
    if not isinstance(payload, dict):
        raise RecoveryError("release candidate must be a JSON object")
    claimed = payload.get("source_pr_number")
    if isinstance(claimed, int) and not isinstance(claimed, bool) and claimed != args.pr:
        raise RecoveryError("candidate source_pr_number does not match the selected PR")
    if not is_public_publication(payload):
        _write_outputs({"guard": "ok", "reason": "not_public"})
        return 0
    filenames = changed_file_names(args.repository, args.pr)
    violation = test_only_public_violation(payload, filenames)
    if violation is not None:
        raise RecoveryError(violation)
    _write_outputs({"guard": "ok", "changed_files": len(filenames)})
    return 0


def _existing_source_rows(
    repository: str,
    sources: Sequence[Source],
) -> list[tuple[int | None, str | None]]:
    dsn = os.getenv("RELEASE_NEON_DATABASE_URL", "").strip()
    if not dsn:
        raise RecoveryError("RELEASE_NEON_DATABASE_URL is required for ledger discovery")
    from psycopg import connect

    numbers = [source.number for source in sources]
    shas = [source.merge_commit_sha for source in sources]
    with (
        connect(
            dsn,
            connect_timeout=15,
            options="-c default_transaction_read_only=on",
        ) as connection,
        connection.cursor() as cursor,
    ):
        raw_rows = cursor.execute(
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
        ).fetchall()
    rows: list[tuple[int | None, str | None]] = []
    for row in raw_rows:
        if len(row) != 2:
            raise RecoveryError("release-ledger lookup returned an invalid row")
        number, sha = row
        if (
            (number is not None and (not isinstance(number, int) or isinstance(number, bool)))
            or (sha is not None and not isinstance(sha, str))
        ):
            raise RecoveryError("release-ledger lookup returned invalid source provenance")
        rows.append((number, sha))
    return rows


def _write_outputs(outputs: dict[str, object]) -> None:
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
    live_sha = _fetch_production_revision()
    if not _git_ancestor(live_sha, "HEAD"):
        raise RecoveryError("production revision is not on the trusted main history")
    return live_sha


def _select(args: argparse.Namespace) -> int:
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

    selected = select_missing_source(deployed, _existing_source_rows(args.repository, deployed))
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
    if _SHA_PATTERN.fullmatch(args.merge_sha) is None:
        raise RecoveryError("merge SHA must be a full lowercase Git commit SHA")
    live_sha = _verified_live_revision()
    if not _git_ancestor(args.merge_sha, live_sha):
        raise RecoveryError("refusing publication: merged PR is not in live production")
    _write_outputs({"live_sha": live_sha, "merge_sha": args.merge_sha, "deployed": True})
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select", help="select one missing deployed ledger source")
    select.add_argument("--repository", required=True)
    select.add_argument("--pr", type=int)
    select.add_argument("--since-hours", type=int, default=72)
    select.set_defaults(handler=_select)
    verify = commands.add_parser("verify-deployed", help="require a merge SHA in live production")
    verify.add_argument("--merge-sha", required=True)
    verify.set_defaults(handler=_verify_deployed)
    guard = commands.add_parser(
        "verify-public", help="reject a public candidate whose complete diff is test-only"
    )
    guard.add_argument("--candidate", required=True)
    guard.add_argument("--repository", required=True)
    guard.add_argument("--pr", type=int, required=True)
    guard.set_defaults(handler=_verify_public)
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
