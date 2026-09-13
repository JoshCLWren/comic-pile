#!/usr/bin/env python3
"""Prune stale Vercel deployments after a ComicPile production deploy.

Keep policy (keep-N=2 production Ready)
---------------------------------------
Never delete the live production alias target. Also keep the most recent
READY production deployment that is not that alias (one rollback candidate).
Delete every other terminal deployment, including leftover preview rows and
ERROR/CANCELED/FAILED records that still consume Functions Storage.

Safety
------
* Deletes use ``DELETE /v13/deployments/{dpl_...}`` only.
* The project name or project id is never a delete target.
* ``vercel remove <project>`` is never invoked (with or without ``--safe``).
* In-progress deployments are left untouched.
* Deletion runs in batches of at most 200 (Vercel CLI bulk-delete limit)
  with backoff on ``429`` / ``5xx``.

Usage::

    python scripts/prune_vercel_deployments.py --dry-run
    python scripts/prune_vercel_deployments.py --fail-soft
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

API_BASE = "https://api.vercel.com"
DEFAULT_PROJECT_NAME = "comic-pile"
DELETE_BATCH_SIZE = 200
LIST_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 30.0
USER_AGENT = "comic-pile-ci/prune-vercel-deployments"
DEPLOYMENT_ID_RE = re.compile(r"^dpl_[A-Za-z0-9_]+$")
IN_PROGRESS_STATES = frozenset({"BUILDING", "INITIALIZING", "QUEUED", "DEPLOYING", "UPLOADING"})
DELETABLE_STATES = frozenset({"READY", "ERROR", "CANCELED", "FAILED", "BLOCKED"})
PROTECTED_DELETE_MARKERS = (
    "current production",
    "aliased",
    "cannot be removed",
    "production deployment",
)
PROTECTED_DELETE_STATUSES = frozenset({400, 403, 409})


class PruneError(RuntimeError):
    """A prune-policy or Vercel API failure that stops deletion."""


@dataclass(frozen=True)
class Deployment:
    """One Vercel deployment record used by the keep/delete policy.

    Attributes:
        uid: Deployment id (``dpl_...``).
        url: Deployment hostname, if Vercel supplied one.
        created: Creation timestamp in milliseconds.
        state: Ready/terminal state string.
        target: ``production``, ``preview``, or ``None``.
    """

    uid: str
    url: str | None
    created: int
    state: str
    target: str | None

    @property
    def is_production(self) -> bool:
        """Return whether this deployment targeted production."""
        return self.target == "production"

    @property
    def is_ready(self) -> bool:
        """Return whether this deployment reached READY."""
        return self.state == "READY"

    @property
    def is_in_progress(self) -> bool:
        """Return whether this deployment is still building or queued."""
        return self.state in IN_PROGRESS_STATES


@dataclass(frozen=True)
class DeleteOutcome:
    """Result of one attempted deployment delete.

    Attributes:
        uid: Deployment id that was requested.
        ok: Whether the deployment is gone or already absent.
        status: HTTP status from Vercel, or ``0`` when not applicable.
        protected: Whether Vercel refused because the row is aliased/live.
        message: Short diagnostic for logs.
    """

    uid: str
    ok: bool
    status: int
    protected: bool
    message: str


@dataclass(frozen=True)
class PruneResult:
    """Summary of one prune run.

    Attributes:
        live_id: Current production alias target.
        rollback_id: Previous READY production id, if one exists.
        kept: Deployment ids the policy refused to delete.
        deleted: Ids successfully removed (empty on dry-run).
        failed: Ids that were selected but not removed.
        skipped_in_progress: In-progress ids that were kept.
        dry_run: Whether deletes were skipped.
    """

    live_id: str
    rollback_id: str | None
    kept: tuple[str, ...]
    deleted: tuple[str, ...]
    failed: tuple[str, ...]
    skipped_in_progress: tuple[str, ...]
    dry_run: bool


class DeploymentClient(Protocol):
    """Vercel access needed by the prune policy."""

    def fetch_project(self) -> Mapping[str, object]:
        """Return the project payload that includes ``targets.production``."""

    def fetch_deployments(self) -> list[Deployment]:
        """Return every deployment for the project."""

    def delete_deployment(self, uid: str) -> DeleteOutcome:
        """Delete one deployment by id."""


def as_int(value: object) -> int | None:
    """Coerce a JSON timestamp or count to ``int``.

    Args:
        value: JSON number or digit string.

    Returns:
        The integer, or ``None`` when the value is not a safe number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def as_optional_str(value: object) -> str | None:
    """Return a stripped string, or ``None`` when missing/empty.

    Args:
        value: JSON field.

    Returns:
        A non-empty stripped string, or ``None``.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def is_deployment_id(value: str) -> bool:
    """Return whether ``value`` is a Vercel deployment id.

    Args:
        value: Candidate id.

    Returns:
        ``True`` only for ``dpl_`` ids.
    """
    return bool(DEPLOYMENT_ID_RE.fullmatch(value))


def require_deployment_id(uid: str) -> str:
    """Reject any delete target that is not a deployment id.

    Args:
        uid: Candidate delete target.

    Returns:
        The same id when it is a ``dpl_`` deployment.

    Raises:
        PruneError: If the value could identify a project or other resource.
    """
    if not is_deployment_id(uid):
        raise PruneError(f"refusing to delete non-deployment id {uid!r}")
    return uid


def deployment_delete_url(uid: str, team_id: str) -> str:
    """Build the REST URL that deletes one deployment.

    Args:
        uid: Deployment id.
        team_id: Vercel team id.

    Returns:
        Absolute ``DELETE /v13/deployments/{id}`` URL.

    Raises:
        PruneError: If the id is unsafe or the path would touch a project.
    """
    safe_uid = require_deployment_id(uid)
    path = f"/v13/deployments/{urllib.parse.quote(safe_uid, safe='')}"
    if "/projects/" in path or safe_uid.startswith("prj_"):
        raise PruneError("refusing a project-scoped delete URL")
    query = urllib.parse.urlencode({"teamId": team_id})
    return f"{API_BASE}{path}?{query}"


def parse_deployment(raw: Mapping[str, object]) -> Deployment | None:
    """Parse one Vercel list-deployments row.

    Args:
        raw: One object from the ``deployments`` array.

    Returns:
        A :class:`Deployment`, or ``None`` when required fields are missing.
    """
    uid = as_optional_str(raw.get("uid")) or as_optional_str(raw.get("id"))
    if uid is None or not is_deployment_id(uid):
        return None
    created = as_int(raw.get("created"))
    if created is None:
        created = as_int(raw.get("createdAt"))
    if created is None:
        return None
    state = as_optional_str(raw.get("readyState")) or as_optional_str(raw.get("state"))
    if state is None:
        return None
    target = as_optional_str(raw.get("target"))
    url = as_optional_str(raw.get("url"))
    return Deployment(uid=uid, url=url, created=created, state=state, target=target)


def production_alias_id(project: Mapping[str, object]) -> str:
    """Return the live production alias target from a project payload.

    Args:
        project: ``GET /v9/projects/{id}`` body.

    Returns:
        The current production deployment id.

    Raises:
        PruneError: If the alias target cannot be resolved safely.
    """
    targets = project.get("targets")
    if not isinstance(targets, dict):
        raise PruneError("project payload missing targets.production")
    production = targets.get("production")
    if isinstance(production, str) and is_deployment_id(production):
        return production
    if isinstance(production, dict):
        uid = as_optional_str(production.get("id")) or as_optional_str(production.get("uid"))
        if uid is not None and is_deployment_id(uid):
            return uid
    raise PruneError("could not resolve the live production alias target")


def verify_project(
    project: Mapping[str, object],
    *,
    project_id: str,
    project_name: str,
) -> None:
    """Refuse to prune if the resolved project is not the expected one.

    Args:
        project: Project payload.
        project_id: Expected ``prj_...`` id.
        project_name: Expected project name.

    Raises:
        PruneError: If name or id do not match.
    """
    resolved_id = as_optional_str(project.get("id"))
    resolved_name = as_optional_str(project.get("name"))
    if resolved_id != project_id:
        raise PruneError(
            f"resolved project id {resolved_id!r} does not match {project_id!r}"
        )
    if resolved_name != project_name:
        raise PruneError(
            f"resolved project name {resolved_name!r} does not match {project_name!r}"
        )


def select_rollback_id(live_id: str, deployments: Sequence[Deployment]) -> str | None:
    """Return the previous READY production deployment, if one exists.

    Args:
        live_id: Current production alias target.
        deployments: All known deployments.

    Returns:
        The newest READY production id that is not ``live_id``, or ``None``.
    """
    ready_production = [
        item
        for item in deployments
        if item.is_production and item.is_ready and item.uid != live_id
    ]
    if not ready_production:
        return None
    newest = max(ready_production, key=lambda item: item.created)
    return newest.uid


def select_keepers(live_id: str, deployments: Sequence[Deployment]) -> set[str]:
    """Return ids that must not be deleted.

    Args:
        live_id: Current production alias target.
        deployments: All known deployments.

    Returns:
        Live production, the previous READY production, and in-progress ids.
    """
    keepers = {live_id}
    rollback_id = select_rollback_id(live_id, deployments)
    if rollback_id is not None:
        keepers.add(rollback_id)
    for item in deployments:
        if item.is_in_progress:
            keepers.add(item.uid)
    return keepers


def select_prune_candidates(
    deployments: Sequence[Deployment],
    keepers: set[str],
) -> list[Deployment]:
    """Return oldest-first terminal deployments that are safe to delete.

    Args:
        deployments: All known deployments.
        keepers: Ids protected by the keep policy.

    Returns:
        Deletable deployments ordered from oldest to newest.
    """
    candidates = [
        item
        for item in deployments
        if item.uid not in keepers
        and item.state in DELETABLE_STATES
        and is_deployment_id(item.uid)
    ]
    candidates.sort(key=lambda item: item.created)
    return candidates


def iter_batches[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    """Split ``items`` into batches of at most ``size``.

    Args:
        items: Sequence to split.
        size: Maximum batch length. Must be between 1 and 200 inclusive.

    Returns:
        Contiguous slices covering ``items``.

    Raises:
        PruneError: If ``size`` exceeds the CLI delete limit or is below 1.
    """
    if size < 1:
        raise PruneError("batch size must be >= 1")
    if size > DELETE_BATCH_SIZE:
        raise PruneError(f"batch size {size} exceeds CLI limit {DELETE_BATCH_SIZE}")
    return [items[index : index + size] for index in range(0, len(items), size)]


def backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """Return the next sleep duration for a retryable Vercel error.

    Args:
        attempt: 1-based attempt number that just failed.
        retry_after: Parsed ``Retry-After`` seconds, when present.

    Returns:
        Seconds to wait before the next attempt, capped at 32s unless
        ``Retry-After`` is larger (then capped at 60s).
    """
    if retry_after is not None and retry_after > 0:
        return min(retry_after, 60.0)
    return float(min(2**attempt, 32))


def is_protected_delete_error(status: int, body: str) -> bool:
    """Return whether Vercel refused a delete because the row is live/aliased.

    Args:
        status: HTTP status.
        body: Response body text.

    Returns:
        ``True`` when the deployment must be treated as a keeper.
    """
    if status not in PROTECTED_DELETE_STATUSES:
        return False
    lowered = body.lower()
    return any(marker in lowered for marker in PROTECTED_DELETE_MARKERS)


def prune_exit_code(*, fail_soft: bool, failed: bool) -> int:
    """Map prune success/failure onto a process exit code.

    Args:
        fail_soft: When ``True``, errors log but still return 0.
        failed: Whether listing or any selected delete failed.

    Returns:
        ``0`` on success or fail-soft; ``1`` on a hard failure.
    """
    if not failed:
        return 0
    return 0 if fail_soft else 1


def _parse_retry_after(header: str | None) -> float | None:
    """Parse a ``Retry-After`` header into seconds.

    Args:
        header: Raw header value.

    Returns:
        Delay in seconds, or ``None`` when absent or unparsable.
    """
    if header is None:
        return None
    stripped = header.strip()
    if stripped.isdigit():
        return float(stripped)
    return None


class VercelRestClient:
    """Stdlib Vercel REST client used by production prune runs."""

    def __init__(
        self,
        token: str,
        project_id: str,
        team_id: str,
        *,
        sleeper: Callable[[float], None] | None = None,
        max_attempts: int = 6,
    ) -> None:
        """Create a client for one project/team pair.

        Args:
            token: ``VERCEL_TOKEN`` bearer token. Never logged.
            project_id: Expected project id.
            team_id: Team id for query parameters.
            sleeper: Injectable sleep (tests pass a no-op).
            max_attempts: Retry budget for ``429`` / ``5xx``.
        """
        self._token = token
        self._project_id = project_id
        self._team_id = team_id
        self._sleeper = sleeper or time.sleep
        self._max_attempts = max_attempts

    def fetch_project(self) -> Mapping[str, object]:
        """Return the project payload that includes ``targets.production``.

        Returns:
            Parsed JSON object.

        Raises:
            PruneError: If the API fails or the body is not an object.
        """
        query = urllib.parse.urlencode({"teamId": self._team_id})
        payload = self._request("GET", f"{API_BASE}/v9/projects/{self._project_id}?{query}")
        if not isinstance(payload, dict):
            raise PruneError("Vercel project payload was not an object")
        return payload

    def fetch_deployments(self) -> list[Deployment]:
        """Return every deployment for the project, following pagination.

        Returns:
            Parsed deployments in API order.

        Raises:
            PruneError: If a page cannot be fetched or parsed.
        """
        collected: list[Deployment] = []
        seen: set[str] = set()
        until: int | None = None
        while True:
            params: dict[str, str] = {
                "projectId": self._project_id,
                "teamId": self._team_id,
                "limit": str(LIST_PAGE_SIZE),
            }
            if until is not None:
                params["until"] = str(until)
            query = urllib.parse.urlencode(params)
            payload = self._request("GET", f"{API_BASE}/v6/deployments?{query}")
            if not isinstance(payload, dict):
                raise PruneError("Vercel deployments payload was not an object")
            rows = payload.get("deployments")
            if not isinstance(rows, list):
                raise PruneError("Vercel deployments payload missing deployments array")
            page_uids: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                parsed = parse_deployment(row)
                if parsed is None or parsed.uid in seen:
                    continue
                seen.add(parsed.uid)
                collected.append(parsed)
                page_uids.append(parsed.uid)
            pagination = payload.get("pagination")
            next_cursor = None
            if isinstance(pagination, dict):
                next_cursor = as_int(pagination.get("next"))
            if next_cursor is None or not page_uids:
                break
            if until is not None and next_cursor >= until:
                break
            until = next_cursor
        return collected

    def delete_deployment(self, uid: str) -> DeleteOutcome:
        """Delete one deployment by id.

        Args:
            uid: Deployment id.

        Returns:
            Outcome including protected-alias refusals.

        Raises:
            PruneError: If the id is not a deployment id.
        """
        url = deployment_delete_url(uid, self._team_id)
        try:
            payload = self._request("DELETE", url)
        except PruneError as exc:
            message = str(exc)
            status = 0
            if message.startswith("Vercel API HTTP "):
                status_token = message.split()[3]
                status = int(status_token) if status_token.isdigit() else 0
            if status == 404:
                return DeleteOutcome(uid, True, 404, False, "already absent")
            if is_protected_delete_error(status, message):
                return DeleteOutcome(uid, False, status, True, message)
            return DeleteOutcome(uid, False, status, False, message)
        state = ""
        if isinstance(payload, dict):
            state = as_optional_str(payload.get("state")) or ""
        ok = state == "DELETED" or payload is not None
        return DeleteOutcome(uid, ok, 200, False, state or "deleted")

    def _request(self, method: str, url: str) -> object:
        """Perform one HTTP request with retry on rate limits.

        Args:
            method: ``GET`` or ``DELETE``.
            url: Absolute Vercel API URL.

        Returns:
            Parsed JSON body, or an empty object for an empty body.

        Raises:
            PruneError: After retries are exhausted or on a hard error.
        """
        last_error: PruneError | None = None
        for attempt in range(1, self._max_attempts + 1):
            request = urllib.request.Request(url, method=method)
            request.add_header("Authorization", f"Bearer {self._token}")
            request.add_header("Accept", "application/json")
            request.add_header("User-Agent", USER_AGENT)
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
                last_error = PruneError(
                    f"Vercel API HTTP {exc.code} {urllib.parse.urlparse(url).path}: {body}"
                )
                if exc.code == 429 or exc.code >= 500:
                    if attempt < self._max_attempts:
                        self._sleeper(backoff_seconds(attempt, retry_after))
                        continue
                raise last_error from exc
            except urllib.error.URLError as exc:
                last_error = PruneError(f"Vercel API request failed: {exc.reason}")
                if attempt < self._max_attempts:
                    self._sleeper(backoff_seconds(attempt))
                    continue
                raise last_error from exc
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise PruneError("Vercel API returned non-JSON") from exc
        if last_error is not None:
            raise last_error
        raise PruneError("Vercel API request failed")


def run_prune(
    client: DeploymentClient,
    *,
    project_id: str,
    project_name: str,
    dry_run: bool,
    batch_size: int = DELETE_BATCH_SIZE,
    sleeper: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> PruneResult:
    """Resolve keepers and delete every other terminal deployment.

    Args:
        client: Vercel project/deployment client.
        project_id: Expected project id.
        project_name: Expected project name.
        dry_run: When ``True``, log candidates and delete nothing.
        batch_size: Delete batch size (max 200).
        sleeper: Pause between successful batches.
        log: Logger; defaults to ``print``.

    Returns:
        A :class:`PruneResult` summarizing keepers and deletes.

    Raises:
        PruneError: If the live alias cannot be resolved or the project
            does not match the expected ComicPile production project.
    """
    emit = log or print
    sleep = sleeper or time.sleep
    project = client.fetch_project()
    verify_project(project, project_id=project_id, project_name=project_name)
    live_id = production_alias_id(project)
    deployments = client.fetch_deployments()
    rollback_id = select_rollback_id(live_id, deployments)
    keepers = select_keepers(live_id, deployments)
    in_progress = tuple(item.uid for item in deployments if item.is_in_progress)
    candidates = select_prune_candidates(deployments, keepers)
    emit(
        "Keep policy: live production alias + previous READY production "
        f"(keep-N=2). live={live_id} rollback={rollback_id or 'none'}"
    )
    emit(f"Listed {len(deployments)} deployment(s); keeping {len(keepers)}.")
    if in_progress:
        emit(f"Leaving {len(in_progress)} in-progress deployment(s) untouched.")
    if not candidates:
        emit("Nothing to prune.")
        return PruneResult(
            live_id=live_id,
            rollback_id=rollback_id,
            kept=tuple(sorted(keepers)),
            deleted=(),
            failed=(),
            skipped_in_progress=in_progress,
            dry_run=dry_run,
        )
    emit(f"Selected {len(candidates)} terminal deployment(s) for deletion.")
    deleted: list[str] = []
    failed: list[str] = []
    if dry_run:
        for item in candidates:
            emit(f"DRY-RUN would delete {item.uid} state={item.state} target={item.target}")
        return PruneResult(
            live_id=live_id,
            rollback_id=rollback_id,
            kept=tuple(sorted(keepers)),
            deleted=(),
            failed=(),
            skipped_in_progress=in_progress,
            dry_run=True,
        )
    batches = iter_batches(candidates, batch_size)
    for batch_index, batch in enumerate(batches, start=1):
        emit(f"Deleting batch {batch_index}/{len(batches)} ({len(batch)} deployment(s)).")
        for item in batch:
            if item.uid in keepers or item.uid == live_id:
                emit(f"Refusing to delete keeper {item.uid}")
                continue
            outcome = client.delete_deployment(item.uid)
            if outcome.ok:
                deleted.append(item.uid)
                emit(f"Deleted {item.uid}")
                continue
            if outcome.protected:
                keepers.add(item.uid)
                emit(f"Vercel protected {item.uid}; treating as keeper ({outcome.message})")
                continue
            failed.append(item.uid)
            emit(f"PRUNE DELETE FAILED {item.uid}: {outcome.message}")
        if batch_index < len(batches):
            sleep(1.0)
    emit(
        f"Prune finished: deleted={len(deleted)} failed={len(failed)} "
        f"kept={len(keepers)} dry_run={dry_run}"
    )
    return PruneResult(
        live_id=live_id,
        rollback_id=rollback_id,
        kept=tuple(sorted(keepers)),
        deleted=tuple(deleted),
        failed=tuple(failed),
        skipped_in_progress=in_progress,
        dry_run=False,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id",
        default=os.environ.get("VERCEL_PROJECT_ID"),
        help="Vercel project id (default: VERCEL_PROJECT_ID).",
    )
    parser.add_argument(
        "--project-name",
        default=os.environ.get("VERCEL_PROJECT_NAME", DEFAULT_PROJECT_NAME),
        help="Expected project name (default: comic-pile).",
    )
    parser.add_argument(
        "--team-id",
        default=os.environ.get("VERCEL_ORG_ID"),
        help="Vercel team id (default: VERCEL_ORG_ID).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("VERCEL_TOKEN"),
        help="Vercel bearer token (default: VERCEL_TOKEN). Never printed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List keepers and candidates without deleting.",
    )
    parser.add_argument(
        "--fail-soft",
        action="store_true",
        help="Log prune errors and exit 0 so a finished deploy stays green.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DELETE_BATCH_SIZE,
        help=f"Delete batch size (default {DELETE_BATCH_SIZE}, maximum {DELETE_BATCH_SIZE}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the prune CLI.

    Args:
        argv: Optional argument vector for tests.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    if not args.token or not args.project_id or not args.team_id:
        message = "VERCEL_TOKEN, VERCEL_PROJECT_ID, and VERCEL_ORG_ID are required."
        print(message, file=sys.stderr)
        return prune_exit_code(fail_soft=args.fail_soft, failed=True)
    client = VercelRestClient(args.token, args.project_id, args.team_id)
    try:
        result = run_prune(
            client,
            project_id=args.project_id,
            project_name=args.project_name,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        print(f"PRUNE FAILED: {exc}", file=sys.stderr)
        if args.fail_soft:
            print(
                "PRUNE FAILED (soft): production deploy/smoke already succeeded; "
                "not failing the workflow solely because prune hit an error.",
                file=sys.stderr,
            )
        return prune_exit_code(fail_soft=args.fail_soft, failed=True)
    failed = bool(result.failed)
    if failed:
        print(
            f"PRUNE DELETE FAILED for {len(result.failed)} deployment(s): "
            + ", ".join(result.failed),
            file=sys.stderr,
        )
        if args.fail_soft:
            print(
                "PRUNE FAILED (soft): remaining rows can be retried on the next "
                "deploy or skipped-SHA prune pass.",
                file=sys.stderr,
            )
    return prune_exit_code(fail_soft=args.fail_soft, failed=failed)


if __name__ == "__main__":
    raise SystemExit(main())
