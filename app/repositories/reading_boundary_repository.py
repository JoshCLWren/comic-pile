"""Owner-scoped lookups that enrich the canonical Reading Boundary projection.

The evaluator already decides eligibility. This repository only resolves the
scalar reader-facing labels (list name, volume title, prerequisite origin) so
the service can describe live blockers and historical associations without
re-querying the evaluator or exposing storage identifiers.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.dependency import Dependency
from app.models.external_identity import (
    ExternalIdentity,
    ThreadExternalSeriesMapping,
)
from app.schemas.reading_boundary import BoundaryReadingList

from app.models.issue import Issue
from app.models.thread import Thread


@dataclass(frozen=True, slots=True)
class BoundaryThreadLabels:
    """Reader-facing identity and activity for one owned Thread."""

    thread_id: int
    title: str
    status: str
    volume_label: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryIssueLabels:
    """Reader-facing labels for one Issue, detached from ORM models."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    volume_label: str | None = None
    reading_lists: list[BoundaryReadingList] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BoundaryListLabels:
    """Reader-facing labels for one owned Reading List."""

    list_id: int
    name: str
    mode: str


@dataclass(frozen=True, slots=True)
class BoundaryPrerequisiteLabels:
    """Reader-facing labels for one owned prerequisite edge."""

    prerequisite_id: int
    source_issue_id: int
    target_issue_id: int
    origin: str | None
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryShadowLabels:
    """Every label the boundary service needs in one immutable payload."""

    threads: Mapping[int, BoundaryThreadLabels]
    issues: Mapping[int, BoundaryIssueLabels]
    lists: Mapping[int, BoundaryListLabels]
    prerequisites: Mapping[int, BoundaryPrerequisiteLabels]


def _volume_label(row: ExternalIdentity | None) -> str | None:
    """Return the provider volume name when it is a confirmed Comic Vine series."""
    if row is None or row.entity_type != "series":
        return None
    name = (row.metadata_json or {}).get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


async def _volume_labels_by_thread(
    db: AsyncSession, user_id: int, thread_ids: set[int]
) -> dict[int, str]:
    """Resolve a volume name only when a Thread has exactly one confirmed series.

    A composite Thread may legitimately have several confirmed series mappings.
    Choosing one of them would apply the wrong volume to every Issue, so an
    ambiguous Thread resolves to no label instead of a partial guess.

    Args:
        db: Current read transaction.
        user_id: Owner whose Threads are read.
        thread_ids: Owned Thread identifiers.

    Returns:
        Mapping of unambiguous Thread ID to its confirmed volume name.
    """
    if not thread_ids:
        return {}
    rows = (
        await db.execute(
            select(Thread.id, ExternalIdentity)
            .join(
                ThreadExternalSeriesMapping,
                ThreadExternalSeriesMapping.thread_id == Thread.id,
            )
            .join(
                ExternalIdentity,
                ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
            )
            .where(
                Thread.id.in_(thread_ids),
                Thread.user_id == user_id,
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.entity_type == "series",
            )
        )
    ).all()
    grouped: dict[int, list[ExternalIdentity]] = {}
    for thread_id, identity in rows:
        grouped.setdefault(thread_id, []).append(identity)
    labels: dict[int, str] = {}
    for thread_id, identities in grouped.items():
        if len(identities) != 1:
            continue
        label = _volume_label(identities[0])
        if label is not None:
            labels[thread_id] = label
    return labels


async def load_boundary_labels(
    db: AsyncSession, user_id: int
) -> BoundaryShadowLabels:
    """Resolve reader-facing labels for every owned Issue, list and prerequisite.

    Args:
        db: Current read transaction.
        user_id: Owner whose labels are resolved.

    Returns:
        Immutable labels keyed by Thread, Issue, list and prerequisite identifiers.
    """
    thread_rows = (
        await db.execute(
            select(Thread.id, Thread.title, Thread.status).where(Thread.user_id == user_id)
        )
    ).all()
    thread_ids = {row.id for row in thread_rows}
    volume_by_thread = await _volume_labels_by_thread(db, user_id, thread_ids)

    thread_labels: dict[int, BoundaryThreadLabels] = {
        row.id: BoundaryThreadLabels(
            thread_id=row.id,
            title=row.title,
            status=row.status,
            volume_label=volume_by_thread.get(row.id),
        )
        for row in thread_rows
    }

    issue_rows = (
        (
            await db.execute(
                select(Issue.id, Issue.thread_id, Issue.issue_number).where(
                    Issue.thread_id.in_(thread_ids)
                )
            )
        ).all()
        if thread_ids
        else []
    )
    issue_labels: dict[int, BoundaryIssueLabels] = {}
    for row in issue_rows:
        thread = thread_labels[row.thread_id]
        issue_labels[row.id] = BoundaryIssueLabels(
            issue_id=row.id,
            thread_id=row.thread_id,
            thread_title=thread.title,
            issue_number=row.issue_number,
            volume_label=thread.volume_label,
        )

    list_rows = list(
        (await db.scalars(select(CustomCBLList).where(CustomCBLList.user_id == user_id))).all()
    )
    list_ids = [row.id for row in list_rows]
    if list_ids:
        entry_list_ids = (
            await db.scalars(
                select(CustomCBLEntry.list_id)
                .where(CustomCBLEntry.list_id.in_(list_ids))
                .distinct()
            )
        ).all()
        active_list_ids = set(entry_list_ids)
    else:
        active_list_ids = set()

    if thread_ids:
        source_thread = Thread.__table__.alias("boundary_source_thread")
        target_thread = Thread.__table__.alias("boundary_target_thread")
        source_issue = Issue.__table__.alias("boundary_source_issue")
        target_issue = Issue.__table__.alias("boundary_target_issue")
        prerequisite_rows = list(
            (
                await db.scalars(
                    select(Dependency)
                    .join(source_issue, source_issue.c.id == Dependency.source_issue_id)
                    .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
                    .join(target_issue, target_issue.c.id == Dependency.target_issue_id)
                    .join(target_thread, target_issue.c.thread_id == target_thread.c.id)
                    .where(
                        source_thread.c.user_id == user_id,
                        target_thread.c.user_id == user_id,
                    )
                    .order_by(Dependency.id)
                )
            ).all()
        )
    else:
        prerequisite_rows = []

    lists: dict[int, BoundaryListLabels] = {
        row.id: BoundaryListLabels(list_id=row.id, name=row.name, mode=row.mode)
        for row in list_rows
        if row.id in active_list_ids
    }

    # Load owned list memberships for each issue (reading_lists on BoundaryIssue).
    issue_reading_lists: dict[int, list[BoundaryReadingList]] = {
        issue_id: [] for issue_id in issue_labels
    }
    if active_list_ids:
        entry_rows = (
            await db.scalars(
                select(CustomCBLEntry).where(CustomCBLEntry.list_id.in_(list(active_list_ids)))
            )
        ).all()
        for entry in entry_rows:
            if entry.issue_id not in issue_reading_lists:
                continue
            list_row = lists.get(entry.list_id)
            if list_row is not None:
                issue_reading_lists[entry.issue_id].append(
                    BoundaryReadingList(
                        list_id=list_row.list_id,
                        name=list_row.name,
                        mode=list_row.mode,
                    )
                )
    # Attach memberships to issue labels.
    for issue_id in issue_labels:
        issue_labels[issue_id] = BoundaryIssueLabels(
            issue_id=issue_labels[issue_id].issue_id,
            thread_id=issue_labels[issue_id].thread_id,
            thread_title=issue_labels[issue_id].thread_title,
            issue_number=issue_labels[issue_id].issue_number,
            volume_label=issue_labels[issue_id].volume_label,
            reading_lists=issue_reading_lists.get(issue_id, []),
        )

    prerequisites: dict[int, BoundaryPrerequisiteLabels] = {}
    for row in prerequisite_rows:
        prerequisites[row.id] = BoundaryPrerequisiteLabels(
            prerequisite_id=row.id,
            source_issue_id=row.source_issue_id,
            target_issue_id=row.target_issue_id,
            origin=row.origin,
            provenance=(
                (f"classification:{row.classification}", row.provenance or "")
                if row.origin is not None
                else ("historical classification unknown",)
            ),
        )

    return BoundaryShadowLabels(
        threads=thread_labels,
        issues=issue_labels,
        lists=lists,
        prerequisites=prerequisites,
    )
