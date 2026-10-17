"""Persistence boundaries for Option E list authoring and validation inputs."""

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.collection_exclusion import CollectionExclusion
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.dependency import Dependency
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User

from app.services.collection_exclusion_guard import normalize_volume


async def lock_reader(db: AsyncSession, user_id: int) -> None:
    """Serialize list writes across overlapping lists for the same reader.

    Args:
        db: Transaction that holds the lock until commit or rollback.
        user_id: Reader whose list writes must serialize.

    Returns:
        None.
    """
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())


async def load_threads(db: AsyncSession, user_id: int) -> list[Thread]:
    """Load all owned Threads, including inactive ones for cycle checks.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose constraints are being validated.

    Returns:
        Owned Thread models.
    """
    return list((await db.scalars(select(Thread).where(Thread.user_id == user_id))).all())


async def load_issues(db: AsyncSession, user_id: int) -> list[Issue]:
    """Load every owned Issue, including read Issues for cycle checks.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose constraints are being validated.

    Returns:
        Owned Issue models.
    """
    return list(
        (
            await db.scalars(
                select(Issue)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Thread.user_id == user_id)
            )
        ).all()
    )


async def load_lists(db: AsyncSession, user_id: int) -> list[CustomCBLList]:
    """Load the complete owner's authored list collection.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose constraints are being validated.

    Returns:
        Owned list models.
    """
    return list(
        (await db.scalars(select(CustomCBLList).where(CustomCBLList.user_id == user_id))).all()
    )


async def load_entries(db: AsyncSession, user_id: int) -> list[CustomCBLEntry]:
    """Load all placements in stable list order.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose constraints are being validated.

    Returns:
        Owned entries ordered by list ID and position.
    """
    return list(
        (
            await db.scalars(
                select(CustomCBLEntry)
                .join(CustomCBLList)
                .where(CustomCBLList.user_id == user_id)
                .order_by(CustomCBLEntry.list_id, CustomCBLEntry.position)
            )
        ).all()
    )


async def load_requirements(db: AsyncSession, user_id: int) -> list[Dependency]:
    """Keep enforced historical requirements without classifying or rewriting them.

    Args:
        db: Current authoring transaction.
        user_id: Reader who owns both requirement endpoints.

    Returns:
        Existing enforced dependency models, excluding inert cbl-order rows.
    """
    source = aliased(Issue)
    target = aliased(Issue)
    source_thread = aliased(Thread)
    target_thread = aliased(Thread)
    return list(
        (
            await db.scalars(
                select(Dependency)
                .join(source, source.id == Dependency.source_issue_id)
                .join(source_thread, source_thread.id == source.thread_id)
                .join(target, target.id == Dependency.target_issue_id)
                .join(target_thread, target_thread.id == target.thread_id)
                .where(
                    source_thread.user_id == user_id,
                    target_thread.user_id == user_id,
                    or_(
                        Dependency.origin.is_not(None),
                        Dependency.note.is_(None),
                        Dependency.note.not_like("cbl-order:%"),
                    ),
                )
            )
        ).all()
    )


async def load_excluded_issue_ids(
    db: AsyncSession, user_id: int, issues: Sequence[Issue]
) -> frozenset[int]:
    """Resolve owner exclusions by stable Issue, Thread and confirmed volume identity.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose collection exclusions are resolved.
        issues: Already-loaded owned Issue rows.

    Returns:
        Owned Issue IDs matched by durable collection exclusions.
    """
    exclusions = list(
        (
            await db.scalars(
                select(CollectionExclusion).where(CollectionExclusion.user_id == user_id)
            )
        ).all()
    )
    issue_ids = {row.issue_id for row in exclusions if row.issue_id is not None}
    thread_ids = {row.thread_id for row in exclusions if row.thread_id is not None}
    volumes = {
        normalize_volume(row.provider, row.external_volume_id)
        for row in exclusions
        if row.provider is not None and row.external_volume_id is not None
    }
    if volumes:
        identities = await db.execute(
            select(
                ThreadExternalSeriesMapping.thread_id,
                ExternalIdentity.provider,
                ExternalIdentity.external_id,
            )
            .join(
                ExternalIdentity,
                ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
            )
            .join(Thread, Thread.id == ThreadExternalSeriesMapping.thread_id)
            .where(Thread.user_id == user_id, ThreadExternalSeriesMapping.status == "confirmed")
        )
        thread_ids.update(
            tid
            for tid, provider, external_id in identities
            if normalize_volume(provider, external_id) in volumes
        )
        canonical = await db.execute(
            select(Thread.id, ExternalIdentity.provider, ExternalIdentity.external_id)
            .join(CatalogSeries, CatalogSeries.id == Thread.catalog_series_id)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == CatalogSeries.canonical_external_identity_id,
            )
            .where(Thread.user_id == user_id)
        )
        thread_ids.update(
            tid
            for tid, provider, external_id in canonical
            if normalize_volume(provider, external_id) in volumes
        )
        catalog_issues = await db.execute(
            select(Issue.id, ExternalIdentity.provider, ExternalIdentity.external_id)
            .join(Thread, Thread.id == Issue.thread_id)
            .join(CatalogIssue, CatalogIssue.id == Issue.catalog_issue_id)
            .join(CatalogSeries, CatalogSeries.id == CatalogIssue.catalog_series_id)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == CatalogSeries.canonical_external_identity_id,
            )
            .where(Thread.user_id == user_id)
        )
        issue_ids.update(
            issue_id
            for issue_id, provider, external_id in catalog_issues
            if normalize_volume(provider, external_id) in volumes
        )
    return frozenset(
        issue.id for issue in issues if issue.id in issue_ids or issue.thread_id in thread_ids
    )


async def set_entry_intents(
    db: AsyncSession,
    list_id: int,
    intents: dict[int, tuple[Literal["none", "hold", "after_previous"], bool]],
) -> None:
    """Persist validated intent without touching historical checkpoint metadata.

    Args:
        db: Current authoring transaction.
        list_id: List whose ownership has already been checked by the service.
        intents: Member Issue IDs mapped to complete gate and skip values.

    Returns:
        None.
    """
    entries = (
        await db.scalars(select(CustomCBLEntry).where(CustomCBLEntry.list_id == list_id))
    ).all()
    for entry in entries:
        if entry.issue_id in intents:
            gate, skipped = intents[entry.issue_id]
            entry.gate = gate
            entry.skipped = skipped
    await db.flush()
