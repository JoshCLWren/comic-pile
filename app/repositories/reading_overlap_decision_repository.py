"""Owner-scoped persistence for reader-approved Reading List overlap decisions.

Every stored decision belongs to exactly one reader and exactly one of that
reader's Reading Lists, and names two exact Comic Vine volume identities by
reference to the provider's confirmed series identities. No copy of the global
CBL library is stored here: only the reader's own choices and the provider
identities they point at.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.catalog import CatalogSeries
from app.models.custom_cbl import CustomCBLList, CustomCBLOverlapDecision
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.thread import Thread
from app.services.reading_list_evaluator import SeriesOverlapDecision
from app.services.reading_overlap_identity import (
    COMICVINE_PROVIDER,
    VOLUME_ENTITY_TYPE,
    canonical_volume_key,
    normalized_volume_key,
    parse_volume_identity_key,
)


@dataclass(frozen=True, slots=True)
class OverlapDecisionRecord:
    """One stored overlap choice with its canonical volume keys.

    The canonical keys are the exact Comic Vine volumes the reader paired. A
    decision whose referenced identities are not Comic Vine volumes is never
    returned: an unusable identity keeps full strict order.
    """

    id: int
    list_id: int
    continuing_volume_id: str
    waiting_volume_id: str
    created_at: datetime
    updated_at: datetime


async def load_owned_list(
    db: AsyncSession, user_id: int, list_id: int, *, for_update: bool = False
) -> CustomCBLList | None:
    """Load one owned Reading List row, or None when it is missing or foreign.

    Args:
        db: Current transaction.
        user_id: Reader whose ownership is checked.
        list_id: Reading List identifier.
        for_update: When true, acquire a shared lock (SELECT FOR SHARE) to
            prevent concurrent writes while reading the token and decisions.

    Returns:
        The owned list row, or None when the reader does not own it.
    """
    stmt = select(CustomCBLList).where(
        CustomCBLList.id == list_id,
        CustomCBLList.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update(read=True)
    return (await db.execute(stmt)).scalar_one_or_none()


def _to_record(
    decision_id: int,
    list_id: int,
    created_at: datetime,
    updated_at: datetime,
    continuing_provider: str,
    continuing_external_id: str,
    waiting_provider: str,
    waiting_external_id: str,
) -> OverlapDecisionRecord | None:
    """Map one joined decision row to a record, or None when it is unusable.

    Args:
        decision_id: Stored decision identifier.
        list_id: Reading List the decision belongs to.
        created_at: Creation instant of the stored decision.
        updated_at: Last change instant of the stored decision.
        continuing_provider: Provider of the continuing volume identity.
        continuing_external_id: External identifier of the continuing volume.
        waiting_provider: Provider of the waiting volume identity.
        waiting_external_id: External identifier of the waiting volume.

    Returns:
        The mapped record, or None when an identity is not a Comic Vine volume.
    """
    continuing = canonical_volume_key(continuing_provider, continuing_external_id)
    waiting = canonical_volume_key(waiting_provider, waiting_external_id)
    if continuing is None or waiting is None:
        return None
    return OverlapDecisionRecord(
        id=decision_id,
        list_id=list_id,
        continuing_volume_id=continuing,
        waiting_volume_id=waiting,
        created_at=created_at,
        updated_at=updated_at,
    )


async def load_overlap_decisions(
    db: AsyncSession, user_id: int
) -> list[OverlapDecisionRecord]:
    """Load every overlap decision owned by one reader.

    Args:
        db: Current transaction.
        user_id: Reader whose decisions are loaded.

    Returns:
        Decisions ordered by their stable identifier.
    """
    continuing = aliased(ExternalIdentity)
    waiting = aliased(ExternalIdentity)
    rows = await db.execute(
        select(
            CustomCBLOverlapDecision.id,
            CustomCBLOverlapDecision.list_id,
            CustomCBLOverlapDecision.created_at,
            CustomCBLOverlapDecision.updated_at,
            continuing.provider,
            continuing.external_id,
            waiting.provider,
            waiting.external_id,
        )
        .join(
            continuing,
            continuing.id == CustomCBLOverlapDecision.continuing_external_identity_id,
        )
        .join(waiting, waiting.id == CustomCBLOverlapDecision.waiting_external_identity_id)
        .where(CustomCBLOverlapDecision.user_id == user_id)
        .order_by(CustomCBLOverlapDecision.id)
    )
    records: list[OverlapDecisionRecord] = []
    for (
        decision_id,
        list_id,
        created_at,
        updated_at,
        continuing_provider,
        continuing_external_id,
        waiting_provider,
        waiting_external_id,
    ) in rows.all():
        record = _to_record(
            decision_id,
            list_id,
            created_at,
            updated_at,
            continuing_provider,
            continuing_external_id,
            waiting_provider,
            waiting_external_id,
        )
        if record is not None:
            records.append(record)
    return records


async def load_overlap_decision(
    db: AsyncSession, user_id: int, list_id: int, decision_id: int
) -> OverlapDecisionRecord | None:
    """Load one owned overlap decision of one owned list.

    Args:
        db: Current transaction.
        user_id: Reader whose decision is loaded.
        list_id: Reading List that must own the decision.
        decision_id: Decision identifier.

    Returns:
        The owned decision, or None when it is missing or foreign.
    """
    continuing = aliased(ExternalIdentity)
    waiting = aliased(ExternalIdentity)
    row = (
        await db.execute(
            select(
                CustomCBLOverlapDecision.id,
                CustomCBLOverlapDecision.list_id,
                CustomCBLOverlapDecision.created_at,
                CustomCBLOverlapDecision.updated_at,
                continuing.provider,
                continuing.external_id,
                waiting.provider,
                waiting.external_id,
            )
            .join(
                continuing,
                continuing.id == CustomCBLOverlapDecision.continuing_external_identity_id,
            )
            .join(waiting, waiting.id == CustomCBLOverlapDecision.waiting_external_identity_id)
            .where(
                CustomCBLOverlapDecision.id == decision_id,
                CustomCBLOverlapDecision.list_id == list_id,
                CustomCBLOverlapDecision.user_id == user_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    (
        decision_id,
        list_id,
        created_at,
        updated_at,
        continuing_provider,
        continuing_external_id,
        waiting_provider,
        waiting_external_id,
    ) = row
    return _to_record(
        decision_id,
        list_id,
        created_at,
        updated_at,
        continuing_provider,
        continuing_external_id,
        waiting_provider,
        waiting_external_id,
    )


async def load_list_overlap_decisions(
    db: AsyncSession, user_id: int, list_id: int
) -> list[OverlapDecisionRecord]:
    """Load the overlap decisions of one owned Reading List.

    Args:
        db: Current transaction.
        user_id: Reader whose decisions are loaded.
        list_id: Reading List that must own the decisions.

    Returns:
        The list's decisions ordered by their stable identifier.
    """
    continuing = aliased(ExternalIdentity)
    waiting = aliased(ExternalIdentity)
    rows = await db.execute(
        select(
            CustomCBLOverlapDecision.id,
            CustomCBLOverlapDecision.list_id,
            CustomCBLOverlapDecision.created_at,
            CustomCBLOverlapDecision.updated_at,
            continuing.provider,
            continuing.external_id,
            waiting.provider,
            waiting.external_id,
        )
        .join(
            continuing,
            continuing.id == CustomCBLOverlapDecision.continuing_external_identity_id,
        )
        .join(waiting, waiting.id == CustomCBLOverlapDecision.waiting_external_identity_id)
        .where(
            CustomCBLOverlapDecision.list_id == list_id,
            CustomCBLOverlapDecision.user_id == user_id,
        )
        .order_by(CustomCBLOverlapDecision.id)
    )
    records: list[OverlapDecisionRecord] = []
    for (
        decision_id,
        list_id,
        created_at,
        updated_at,
        continuing_provider,
        continuing_external_id,
        waiting_provider,
        waiting_external_id,
    ) in rows.all():
        record = _to_record(
            decision_id,
            list_id,
            created_at,
            updated_at,
            continuing_provider,
            continuing_external_id,
            waiting_provider,
            waiting_external_id,
        )
        if record is not None:
            records.append(record)
    return records


def group_decisions_by_list(
    records: Iterable[OverlapDecisionRecord],
) -> dict[int, tuple[SeriesOverlapDecision, ...]]:
    """Group stored decisions into the per-list evaluator decisions.

    Args:
        records: Stored decisions of one reader.

    Returns:
        Mapping of Reading List ID to its reader-approved overlap decisions.
    """
    grouped: dict[int, list[SeriesOverlapDecision]] = {}
    for record in records:
        grouped.setdefault(record.list_id, []).append(
            SeriesOverlapDecision(record.continuing_volume_id, record.waiting_volume_id)
        )
    return {list_id: tuple(values) for list_id, values in grouped.items()}


async def resolve_volume_identity_ids(
    db: AsyncSession, keys: Iterable[str]
) -> dict[str, int]:
    """Resolve canonical volume keys to their stored provider identity IDs.

    Args:
        db: Current transaction.
        keys: Canonical ``comicvine:<external id>`` keys named by the reader.

    Returns:
        Mapping of normalized canonical key to external identity ID. Keys that
        name no exact Comic Vine series identity are absent.
    """
    candidates: set[str] = set()
    wanted: set[str] = set()
    for key in keys:
        external_id = parse_volume_identity_key(key)
        if external_id is None:
            continue
        normalized = normalized_volume_key(key)
        if normalized is None:
            continue
        wanted.add(normalized)
        candidates.add(external_id)
        candidates.add(normalized)
    if not candidates:
        return {}
    rows = await db.execute(
        select(ExternalIdentity.id, ExternalIdentity.external_id).where(
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == VOLUME_ENTITY_TYPE,
            ExternalIdentity.external_id.in_(candidates),
        )
    )
    resolved: dict[str, int] = {}
    for identity_id, external_id in rows.all():
        canonical = canonical_volume_key(COMICVINE_PROVIDER, external_id)
        if canonical is None:
            continue
        resolved[canonical] = identity_id
    return {key: resolved[key] for key in wanted if key in resolved}


async def _volume_candidates(
    db: AsyncSession, user_id: int, thread_ids: Collection[int]
) -> dict[int, set[str]]:
    """Collect every exact Comic Vine volume claimed by each owned Thread.

    Confirmed series evidence and the canonical catalog series are read in one
    statement so the loader keeps a constant query count instead of one query
    per evidence source.
    """
    if not thread_ids:
        return {}
    confirmed = (
        select(Thread.id, ExternalIdentity.provider, ExternalIdentity.external_id)
        .join(ThreadExternalSeriesMapping, ThreadExternalSeriesMapping.thread_id == Thread.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.entity_type == VOLUME_ENTITY_TYPE,
        )
    )
    catalog = (
        select(Thread.id, ExternalIdentity.provider, ExternalIdentity.external_id)
        .join(CatalogSeries, CatalogSeries.id == Thread.catalog_series_id)
        .join(ExternalIdentity, ExternalIdentity.id == CatalogSeries.canonical_external_identity_id)
        .where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
            ExternalIdentity.entity_type == VOLUME_ENTITY_TYPE,
        )
    )
    rows = await db.execute(union_all(confirmed, catalog))
    candidates: dict[int, set[str]] = {}
    for thread_id, provider, external_id in rows.all():
        key = canonical_volume_key(provider, external_id)
        if key is None:
            continue
        candidates.setdefault(thread_id, set()).add(key)
    return candidates


async def resolve_thread_volume_keys(
    db: AsyncSession, user_id: int, thread_ids: Collection[int]
) -> dict[int, str]:
    """Resolve owned Threads to their exact Comic Vine volume key.

    A Thread resolves only when its confirmed series evidence and its catalog
    series agree on exactly one Comic Vine volume. Missing or ambiguous
    evidence resolves to nothing, so no overlap decision can be applied to the
    wrong run.

    Args:
        db: Current transaction.
        user_id: Reader whose Threads are resolved.
        thread_ids: Owned Thread identifiers.

    Returns:
        Mapping of Thread ID to canonical volume key for unambiguous Threads.
    """
    candidates = await _volume_candidates(db, user_id, thread_ids)
    return {
        thread_id: next(iter(keys))
        for thread_id, keys in candidates.items()
        if len(keys) == 1
    }


async def load_thread_volume_candidates(
    db: AsyncSession, user_id: int
) -> list[tuple[int, str, str]]:
    """List owned Threads with the exact Comic Vine volume they resolve to.

    Args:
        db: Current transaction.
        user_id: Reader whose Threads are listed.

    Returns:
        Thread ID, Thread title and canonical volume key for every owned
        Thread with one unambiguous Comic Vine volume.
    """
    threads = list(
        (
            await db.execute(
                select(Thread.id, Thread.title).where(Thread.user_id == user_id)
            )
        ).all()
    )
    candidates = await _volume_candidates(db, user_id, {thread_id for thread_id, _ in threads})
    rows: list[tuple[int, str, str]] = []
    for thread_id, title in threads:
        keys = candidates.get(thread_id, set())
        if len(keys) != 1:
            continue
        rows.append((thread_id, title, next(iter(keys))))
    return sorted(rows)


async def upsert_overlap_decision(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    continuing_identity_id: int,
    waiting_identity_id: int,
    continuing_volume_id: str,
    waiting_volume_id: str,
) -> OverlapDecisionRecord:
    """Store one reader-approved overlap choice for one owned list.

    Args:
        db: Current transaction.
        user_id: Reader who owns the list and the choice.
        list_id: Reading List the choice belongs to.
        continuing_identity_id: Exact Comic Vine volume allowed to continue.
        waiting_identity_id: Exact Comic Vine volume allowed to wait.
        continuing_volume_id: Canonical key of the continuing volume.
        waiting_volume_id: Canonical key of the waiting volume.

    Returns:
        The stored decision.
    """
    row = (
        await db.execute(
            select(CustomCBLOverlapDecision).where(
                CustomCBLOverlapDecision.list_id == list_id,
                CustomCBLOverlapDecision.user_id == user_id,
                CustomCBLOverlapDecision.continuing_external_identity_id
                == continuing_identity_id,
                CustomCBLOverlapDecision.waiting_external_identity_id == waiting_identity_id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = CustomCBLOverlapDecision(
            user_id=user_id,
            list_id=list_id,
            continuing_external_identity_id=continuing_identity_id,
            waiting_external_identity_id=waiting_identity_id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.updated_at = now
    await db.flush()
    return OverlapDecisionRecord(
        id=row.id,
        list_id=list_id,
        continuing_volume_id=continuing_volume_id,
        waiting_volume_id=waiting_volume_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def delete_overlap_decision(
    db: AsyncSession, *, user_id: int, list_id: int, decision_id: int
) -> bool:
    """Remove one reader-approved overlap choice from one owned list.

    Args:
        db: Current transaction.
        user_id: Reader who owns the list and the choice.
        list_id: Reading List the choice belongs to.
        decision_id: Decision identifier.

    Returns:
        True when a decision was removed, False when it was missing or foreign.
    """
    row = (
        await db.execute(
            select(CustomCBLOverlapDecision).where(
                CustomCBLOverlapDecision.id == decision_id,
                CustomCBLOverlapDecision.list_id == list_id,
                CustomCBLOverlapDecision.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True
