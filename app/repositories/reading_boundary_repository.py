"""Owner-scoped lookups that enrich the canonical Reading Boundary projection.

The evaluator already decides eligibility. This repository only resolves the
scalar reader-facing labels (list name, volume title, prerequisite origin) so
the service can describe live blockers and historical associations without
re-querying the evaluator or exposing storage identifiers.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.dependency import Dependency
from app.models.external_identity import (
    ExternalIdentity,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread


@dataclass(frozen=True, slots=True)
class BoundaryIssueLabels:
    """Reader-facing labels for one Issue, detached from ORM models."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    volume_label: str | None = None


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
    origin: str
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryShadowLabels:
    """Every label the boundary service needs in one immutable payload."""

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


async def load_boundary_labels(
    db: AsyncSession, user_id: int
) -> BoundaryShadowLabels:
    """Resolve reader-facing labels for every owned Issue, list and prerequisite.

    Args:
        db: Current read transaction.
        user_id: Owner whose labels are resolved.

    Returns:
        Immutable labels keyed by Issue, list and prerequisite identifiers.
    """
    issue_rows = list(
        (
            await db.scalars(
                select(Issue)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Thread.user_id == user_id)
            )
        ).all()
    )
    thread_ids = {row.thread_id for row in issue_rows}

    volume_rows = await db.execute(
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
    volume_by_thread: dict[int, ExternalIdentity] = dict(volume_rows.all())

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
    ) if issue_rows else []

    thread_map = {
        row.id: row
        for row in (
            await db.scalars(select(Thread).where(Thread.id.in_(thread_ids)))
        ).all()
    }

    issues: dict[int, BoundaryIssueLabels] = {}
    for row in issue_rows:
        thread = thread_map.get(row.thread_id)
        issues[row.id] = BoundaryIssueLabels(
            issue_id=row.id,
            thread_id=row.thread_id,
            thread_title=thread.title if thread else "",
            issue_number=row.issue_number,
            volume_label=_volume_label(volume_by_thread.get(row.thread_id)),
        )

    lists: dict[int, BoundaryListLabels] = {
        row.id: BoundaryListLabels(list_id=row.id, name=row.name, mode=row.mode)
        for row in list_rows
        if row.id in active_list_ids
    }

    prerequisites: dict[int, BoundaryPrerequisiteLabels] = {}
    for row in prerequisite_rows:
        prerequisites[row.id] = BoundaryPrerequisiteLabels(
            prerequisite_id=row.id,
            source_issue_id=row.source_issue_id,
            target_issue_id=row.target_issue_id,
            origin=row.origin or "converted",
            provenance=(
                (f"classification:{row.classification}", row.provenance or "")
                if row.origin is not None
                else ("historical classification unknown",)
            ),
        )

    return BoundaryShadowLabels(
        issues=issues,
        lists=lists,
        prerequisites=prerequisites,
    )