"""Read-only ComicVine hydration planning for existing ComicPile issues."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.local_comicvine import LocalComicVineResult

HydrationStatus = Literal["matched", "local-miss", "unresolved"]


class ComicVineSnapshotReader(Protocol):
    """Read-only ComicVine snapshot contract used by the hydrator."""

    path: Path | None

    @property
    def available(self) -> bool:
        """Return whether snapshot data can be read."""
        ...

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Return one local ComicVine issue by provider ID."""
        ...

    def sync_metadata(self) -> dict[str, object]:
        """Return snapshot freshness metadata."""
        ...


@dataclass(frozen=True)
class HydrationTarget:
    """One user-owned ComicPile issue considered for ComicVine hydration."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    position: int
    comicvine_issue_id: int | None = None


@dataclass(frozen=True)
class HydrationResult:
    """Machine-readable report row for one hydration target."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    position: int
    status: HydrationStatus
    comicvine_issue_id: int | None
    provenance: str | None
    detail: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the result without leaking provider credentials.

        Returns:
            JSON-compatible report data.
        """
        return asdict(self)


async def enumerate_user_issues(
    db: AsyncSession,
    *,
    user_id: int,
    include_test_threads: bool = False,
) -> list[HydrationTarget]:
    """Enumerate user-owned issues and reuse confirmed ComicVine identities.

    This query is intentionally read-only. It does not modify reading progress,
    continuity, ratings, threads, issues, or external identity mappings.

    Args:
        db: Async database session.
        user_id: ComicPile user whose issues should be inspected.
        include_test_threads: Include threads marked as test data when true.

    Returns:
        Deterministically ordered hydration targets.
    """
    issue_query = (
        select(Issue, Thread)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position, Thread.id, Issue.position, Issue.id)
    )
    if not include_test_threads:
        issue_query = issue_query.where(Thread.is_test.is_(False))

    rows = (await db.execute(issue_query)).all()
    issue_ids = [issue.id for issue, _thread in rows]
    confirmed_by_issue: dict[int, int] = {}
    if issue_ids:
        mapping_query = (
            select(IssueExternalIdentityMapping.issue_id, ExternalIdentity.external_id)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id.in_(issue_ids),
                IssueExternalIdentityMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
            )
        )
        for issue_id, external_id in (await db.execute(mapping_query)).all():
            try:
                confirmed_by_issue[issue_id] = int(external_id)
            except (TypeError, ValueError):
                continue

    return [
        HydrationTarget(
            issue_id=issue.id,
            thread_id=thread.id,
            thread_title=thread.title,
            issue_number=issue.issue_number,
            position=issue.position,
            comicvine_issue_id=confirmed_by_issue.get(issue.id),
        )
        for issue, thread in rows
    ]


def inspect_local_snapshot(
    target: HydrationTarget,
    snapshot: ComicVineSnapshotReader,
) -> HydrationResult:
    """Resolve one target from confirmed identity plus the local snapshot only.

    A confirmed ComicVine issue ID is authoritative identity evidence. A local
    snapshot miss is reported rather than converted into a guessed mapping. Live
    provider fallback is deliberately left to the endpoint-budgeted client from
    #1019 so this foundation remains safe and restart-friendly.

    Args:
        target: ComicPile issue to inspect.
        snapshot: Read-only local ComicVine snapshot.

    Returns:
        A report row describing the local resolution state.
    """
    if target.comicvine_issue_id is None:
        return HydrationResult(
            issue_id=target.issue_id,
            thread_id=target.thread_id,
            thread_title=target.thread_title,
            issue_number=target.issue_number,
            position=target.position,
            status="unresolved",
            comicvine_issue_id=None,
            provenance=None,
            detail="No confirmed ComicVine issue identity is available yet.",
        )

    local = snapshot.get_issue(target.comicvine_issue_id)
    if local is None:
        return HydrationResult(
            issue_id=target.issue_id,
            thread_id=target.thread_id,
            thread_title=target.thread_title,
            issue_number=target.issue_number,
            position=target.position,
            status="local-miss",
            comicvine_issue_id=target.comicvine_issue_id,
            provenance="comicvine-local-sqlite",
            detail="Confirmed identity is absent from the configured local snapshot.",
        )

    provider_issue_number = str(local.data.get("issue_number", "")).strip()
    detail = "Confirmed identity resolved from the local ComicVine snapshot."
    if provider_issue_number and provider_issue_number != target.issue_number:
        detail = (
            "Confirmed identity resolved; provider issue number differs from the "
            "ComicPile label, so the mapping is preserved instead of guessed by number."
        )
    return HydrationResult(
        issue_id=target.issue_id,
        thread_id=target.thread_id,
        thread_title=target.thread_title,
        issue_number=target.issue_number,
        position=target.position,
        status="matched",
        comicvine_issue_id=target.comicvine_issue_id,
        provenance=local.provenance,
        detail=detail,
    )


def build_report(
    targets: list[HydrationTarget],
    snapshot: ComicVineSnapshotReader,
) -> dict[str, object]:
    """Build a deterministic report suitable for resumable hydrator handoff.

    Args:
        targets: Ordered ComicPile issues to inspect.
        snapshot: Read-only local ComicVine snapshot.

    Returns:
        Summary counts, snapshot metadata, and per-issue results.
    """
    results = [inspect_local_snapshot(target, snapshot) for target in targets]
    counts: dict[str, int] = {"matched": 0, "local-miss": 0, "unresolved": 0}
    for result in results:
        counts[result.status] += 1
    return {
        "summary": {"total": len(results), **counts},
        "snapshot": {
            "path": str(snapshot.path) if snapshot.path is not None else None,
            "available": snapshot.available,
            "sync_metadata": snapshot.sync_metadata(),
        },
        "issues": [result.to_dict() for result in results],
    }


def write_report(report: dict[str, object], output_path: str | Path) -> None:
    """Write a hydration report atomically enough for restart-safe CLI use.

    Args:
        report: JSON-compatible hydration report.
        output_path: Destination file path.
    """
    import json

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
