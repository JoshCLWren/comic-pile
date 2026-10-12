"""Reattach a split continuation Thread onto its canonical series Thread.

Used for the Fantastic Four (1961)/(1970) split: both Threads hold issues from
one original publishing series. Issue rows are reassigned, never deleted or
recreated, so ids, read status, ``read_at``, ratings, events, and incoming
Dependencies stay put.

Genuine annuals, specials, and Giant-Size titles are different publications
and must not be passed to this helper.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.issue_tracking import apply_thread_issue_tracking_state


class SeriesThreadReattachError(ValueError):
    """Raised when a split continuation cannot be reattached safely."""


async def reattach_split_series_thread(
    db: AsyncSession,
    *,
    canonical_thread_id: int,
    split_thread_id: int,
    expected_canonical_title: str,
    expected_split_title: str,
) -> dict[str, int]:
    """Move every Issue from ``split_thread_id`` onto ``canonical_thread_id``.

    Positions on the split Thread are shifted by the canonical Thread's current
    maximum position so ``(thread_id, position)`` stays unique. Overlapping
    ``issue_number`` values abort. Duplicate series identity mappings on the
    split Thread are dropped when the canonical Thread already holds the same
    ``external_identity_id``.

    Args:
        db: Async database session. Caller commits.
        canonical_thread_id: Surviving series Thread.
        split_thread_id: Continuation Thread that will be deleted after it
            owns zero issues.
        expected_canonical_title: Exact title guard for the surviving Thread.
        expected_split_title: Exact title guard for the continuation Thread.

    Returns:
        Counts of moved issues, dropped series mappings, and the new total.

    Raises:
        SeriesThreadReattachError: When titles differ, numbers overlap, or a
            Thread is missing.
    """
    if canonical_thread_id == split_thread_id:
        raise SeriesThreadReattachError("canonical and split Thread ids must differ")
    canonical = await db.get(Thread, canonical_thread_id)
    split = await db.get(Thread, split_thread_id)
    if canonical is None or split is None:
        raise SeriesThreadReattachError("canonical or split Thread is missing")
    if canonical.title != expected_canonical_title:
        raise SeriesThreadReattachError(
            f"canonical title {canonical.title!r} != {expected_canonical_title!r}"
        )
    if split.title != expected_split_title:
        raise SeriesThreadReattachError(
            f"split title {split.title!r} != {expected_split_title!r}"
        )
    if canonical.user_id != split.user_id:
        raise SeriesThreadReattachError("canonical and split Threads have different owners")

    canonical_issues = list(
        (
            await db.execute(
                select(Issue).where(Issue.thread_id == canonical_thread_id).order_by(Issue.position)
            )
        ).scalars().all()
    )
    split_issues = list(
        (
            await db.execute(
                select(Issue).where(Issue.thread_id == split_thread_id).order_by(Issue.position)
            )
        ).scalars().all()
    )
    if not split_issues:
        raise SeriesThreadReattachError("split Thread has no issues to reattach")
    overlap = {issue.issue_number for issue in canonical_issues} & {
        issue.issue_number for issue in split_issues
    }
    if overlap:
        raise SeriesThreadReattachError(
            f"issue_number overlap {sorted(overlap)[:8]} would violate uniqueness"
        )

    position_shift = max((issue.position for issue in canonical_issues), default=0)
    split.next_unread_issue_id = None
    await db.flush()
    for issue in split_issues:
        issue.thread_id = canonical_thread_id
        issue.position = issue.position + position_shift
    await db.flush()

    dropped_mappings = 0
    canonical_identities = set(
        (
            await db.execute(
                select(ThreadExternalSeriesMapping.external_identity_id).where(
                    ThreadExternalSeriesMapping.thread_id == canonical_thread_id
                )
            )
        ).scalars().all()
    )
    split_mappings = list(
        (
            await db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == split_thread_id
                )
            )
        ).scalars().all()
    )
    for mapping in split_mappings:
        if mapping.external_identity_id in canonical_identities:
            await db.delete(mapping)
            dropped_mappings += 1
        else:
            mapping.thread_id = canonical_thread_id
    await db.flush()

    moved_issues = list(
        (
            await db.execute(
                select(Issue).where(Issue.thread_id == canonical_thread_id).order_by(Issue.position)
            )
        ).scalars().all()
    )
    apply_thread_issue_tracking_state(canonical, moved_issues)
    await db.execute(delete(Thread).where(Thread.id == split_thread_id))
    await db.flush()
    return {
        "moved_issues": len(split_issues),
        "dropped_duplicate_series_mappings": dropped_mappings,
        "canonical_total_issues": len(moved_issues),
        "canonical_issues_remaining": int(canonical.issues_remaining),
    }
