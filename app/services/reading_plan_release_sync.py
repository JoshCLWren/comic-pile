"""Deterministic sync service for Reading Plan release sources (#3117).

For each enabled release source, fetches the authoritative ComicVine volume
roster, discovers provider issues not yet canonically adopted, and adopts
only issues that have actually reached release (store_date <= as_of).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from comic_pile.comicvine_provider import ComicVineClient


@dataclass
class SyncSourceResult:
    """Per-source outcome of one sync run."""

    source_id: int
    plan_id: int
    thread_id: int
    volume_id: str
    fetched: int = 0
    adopted: int = 0
    skipped_future: int = 0
    skipped_unknown_date: int = 0
    skipped_already_adopted: int = 0
    failures: list[str] = field(default_factory=list)


@dataclass
class SyncRunResult:
    """Structured result of one sync run across all sources."""

    as_of: datetime
    sources: list[SyncSourceResult] = field(default_factory=list)
    volume_fetch_failures: list[str] = field(default_factory=list)

    @property
    def total_adopted(self) -> int:
        """Total issues adopted across all sources."""
        return sum(s.adopted for s in self.sources)

    @property
    def total_failures(self) -> int:
        """Total per-source failures plus volume fetch failures."""
        return sum(len(s.failures) for s in self.sources) + len(
            self.volume_fetch_failures
        )


def _parse_store_date(value: object) -> datetime | None:
    """Parse a ComicVine store_date to UTC datetime, or None if unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # ComicVine dates are typically "2024-01-15" or "2024-01-15 00:00:00".
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


async def _get_adopted_issue_ids(
    db: AsyncSession, *, user_id: int, provider_issue_ids: set[str]
) -> set[str]:
    """Return the subset of provider issue IDs already canonically adopted."""
    if not provider_issue_ids:
        return set()
    stmt = (
        select(ExternalIdentity.external_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id.in_(provider_issue_ids),
            IssueExternalIdentityMapping.status == "confirmed",
            Thread.user_id == user_id,
        )
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def sync_release_sources(
    db: AsyncSession,
    *,
    user_id: int,
    as_of: datetime,
    provider: ComicVineClient,
) -> SyncRunResult:
    """Sync all enabled release sources for one user.

    Args:
        db: Database session.
        user_id: Owner user ID.
        as_of: UTC boundary; only issues with store_date <= as_of are adopted.
        provider: ComicVine client (injected for testability).

    Returns:
        Structured run result with per-source counts and failures.
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    result = SyncRunResult(as_of=as_of)
    client = provider

    # Load enabled sources with their plan/thread/volume.
    stmt = (
        select(ReadingPlanReleaseSource, ExternalIdentity)
        .join(
            ExternalIdentity,
            ReadingPlanReleaseSource.external_identity_id == ExternalIdentity.id,
        )
        .join(Thread, ReadingPlanReleaseSource.thread_id == Thread.id)
        .where(
            ReadingPlanReleaseSource.enabled.is_(True),
            Thread.user_id == user_id,
        )
        .order_by(ReadingPlanReleaseSource.id)
    )
    rows = (await db.execute(stmt)).all()

    # Group by volume to avoid refetching the same volume for multiple plans.
    by_volume: dict[str, list[tuple[ReadingPlanReleaseSource, ExternalIdentity]]] = {}
    for source, identity in rows:
        by_volume.setdefault(identity.external_id, []).append((source, identity))

    # Fetch each volume once.
    volume_rosters: dict[str, list[dict[str, object]]] = {}
    for volume_id in by_volume:
        try:
            roster = await client.fetch_volume_issues(int(volume_id), refresh=True)
            volume_rosters[volume_id] = roster
        except Exception as exc:
            result.volume_fetch_failures.append(f"volume {volume_id}: {exc}")

    # Process each source.
    for volume_id, source_pairs in by_volume.items():
        roster = volume_rosters.get(volume_id)
        if roster is None:
            continue  # Fetch failed; already recorded.
        # Build provider-issue-id -> row map.
        by_issue_id: dict[str, dict[str, object]] = {}
        for row in roster:
            pid = row.get("id")
            if pid is not None:
                by_issue_id[str(pid)] = row

        adopted_ids = await _get_adopted_issue_ids(
            db, user_id=user_id, provider_issue_ids=set(by_issue_id.keys())
        )

        for source, _identity in source_pairs:
            src_result = SyncSourceResult(
                source_id=source.id,
                plan_id=source.plan_id,
                thread_id=source.thread_id,
                volume_id=volume_id,
            )
            src_result.fetched = len(by_issue_id)
            try:
                for pid, row in by_issue_id.items():
                    if pid in adopted_ids:
                        src_result.skipped_already_adopted += 1
                        continue
                    store_date = _parse_store_date(row.get("store_date"))
                    if store_date is None:
                        src_result.skipped_unknown_date += 1
                        continue
                    if store_date > as_of:
                        src_result.skipped_future += 1
                        continue
                    # Adopt the issue.
                    try:
                        await _adopt_issue(
                            db,
                            user_id=user_id,
                            thread_id=source.thread_id,
                            provider_issue_id=pid,
                            row=row,
                        )
                        src_result.adopted += 1
                        adopted_ids.add(pid)
                    except Exception as exc:
                        src_result.failures.append(f"issue {pid}: {exc}")
                # Update last_synced_at.
                source.last_synced_at = as_of
                await db.commit()
            except Exception as exc:
                await db.rollback()
                src_result.failures.append(f"source error: {exc}")
            result.sources.append(src_result)

    return result


async def _adopt_issue(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    provider_issue_id: str,
    row: dict[str, object],
) -> Issue:
    """Idempotently create a canonical Issue from a provider row.

    Reuses the existing Issue when the ComicVine issue identity already maps
    to one; otherwise creates it using natural-order positioning.
    """
    # Check for existing canonical issue.
    stmt = (
        select(Issue)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id
            == IssueExternalIdentityMapping.external_identity_id,
        )
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == provider_issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            Thread.user_id == user_id,
        )
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    # Load thread for ownership check and positioning.
    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if thread is None or thread.user_id != user_id:
        raise ValueError(f"Thread {thread_id} not found or not owned")

    # Create the issue with natural-order positioning (append at end).
    max_pos = (
        await db.execute(
            select(Issue.position).where(Issue.thread_id == thread_id).order_by(Issue.position.desc()).limit(1)
        )
    ).scalar_one_or_none()
    next_position = (max_pos or 0) + 1

    issue_number = row.get("issue_number")
    issue = Issue(
        thread_id=thread_id,
        issue_number=str(issue_number) if issue_number is not None else provider_issue_id,
        position=next_position,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    # Create or reuse the ExternalIdentity.
    identity_stmt = select(ExternalIdentity).where(
        ExternalIdentity.provider == "comicvine",
        ExternalIdentity.entity_type == "issue",
        ExternalIdentity.external_id == provider_issue_id,
    )
    identity = (await db.execute(identity_stmt)).scalar_one_or_none()
    if identity is None:
        metadata: dict[str, object] = {}
        for key in ("name", "title", "cover_date", "store_date", "site_detail_url"):
            if row.get(key) is not None:
                metadata[key] = row[key]  # type: ignore[literal-required]
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=provider_issue_id,
            metadata_json=metadata,
        )
        db.add(identity)
        await db.flush()

    mapping = IssueExternalIdentityMapping(
        issue_id=issue.id,
        external_identity_id=identity.id,
        status="confirmed",
        evidence_source="release-sync",
    )
    db.add(mapping)
    await db.flush()

    # Update thread counts.
    thread.total_issues = (thread.total_issues or 0) + 1
    thread.issues_remaining = (thread.issues_remaining or 0) + 1
    if thread.status == "completed":
        thread.status = "active"
    await db.flush()

    return issue
