"""Safely materialize explicitly approved missing CBL comics as canonical issues."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import cast

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import link_thread_external_series, upsert_external_identity
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.comicvine_resolution import confirm_comicvine_identity
from app.services.issue_identity_reconciliation import resolve_canonical_issue
from app.services.issue_tracking import apply_thread_issue_tracking_state
from comic_pile.queue import _acquire_queue_lock, move_to_front


class CBLMaterializationError(Exception):
    """An approved CBL entry cannot be represented safely without guessing."""


@dataclass(frozen=True, slots=True)
class CBLMaterializationResult:
    """Canonical issue identities produced or reused by one materialization pass."""

    issue_ids_by_source_position: dict[int, int]
    reused_issue_ids: tuple[int, ...]
    created_issue_ids: tuple[int, ...]
    created_thread_ids: tuple[int, ...]


def _stable_series_key(entry: Mapping[str, object]) -> tuple[str, str] | None:
    """Return normalized provider series identity, never a title-derived group."""
    provider = str(entry.get("series_provider") or "").strip().casefold()
    external_id = str(entry.get("series_external_id") or "").strip()
    if not provider or not external_id:
        return None
    return provider, external_id


def _issue_number_key(issue_number: str) -> tuple[int, int, str] | None:
    """Normalize simple provider issue numbers into deterministic run order."""
    match = re.fullmatch(r"\s*(\d+)(?:\.(\d+))?([A-Za-z]*)\s*", issue_number)
    if match is None:
        return None
    fraction = int((match.group(2) or "0").ljust(12, "0")[:12])
    return int(match.group(1)), fraction, match.group(3).casefold()


def _comicvine_numeric_id(value: object) -> int | None:
    """Return the numeric ComicVine issue ID from canonical stored forms."""
    normalized = str(value or "").strip()
    return int(normalized) if normalized.isdigit() else None


async def _confirmed_series_threads(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    external_id: str,
) -> tuple[ExternalIdentity, list[Thread]]:
    """Resolve all owned threads confirmed for one stable external series."""
    identity = await upsert_external_identity(
        db,
        provider=provider,
        entity_type="series",
        external_id=external_id,
    )
    threads = list(
        (
            await db.scalars(
                select(Thread)
                .join(
                    ThreadExternalSeriesMapping,
                    ThreadExternalSeriesMapping.thread_id == Thread.id,
                )
                .where(
                    Thread.user_id == user_id,
                    ThreadExternalSeriesMapping.external_identity_id == identity.id,
                    ThreadExternalSeriesMapping.status == "confirmed",
                )
                .order_by(Thread.id)
                .with_for_update(of=Thread)
            )
        ).all()
    )
    return identity, threads


def _target_from_series_evidence(
    *,
    provider: str,
    external_id: str,
    mapped_threads: Sequence[Thread],
    canonical_thread_ids: set[int],
) -> Thread | None:
    """Return the uniquely proven target, failing on contradictory evidence."""
    mapped_by_id = {thread.id: thread for thread in mapped_threads}
    if not mapped_threads:
        if len(canonical_thread_ids) > 1:
            raise CBLMaterializationError(
                f"Canonical issues for {provider}:{external_id} span multiple threads"
            )
        return None
    if len(mapped_threads) == 1:
        mapped = mapped_threads[0]
        if canonical_thread_ids and canonical_thread_ids != {mapped.id}:
            raise CBLMaterializationError(
                f"Canonical issue evidence contradicts the confirmed mapping for {provider}:{external_id}"
            )
        return mapped
    if len(canonical_thread_ids) != 1:
        raise CBLMaterializationError(
            f"External series {provider}:{external_id} maps to multiple owned threads"
        )
    target_id = next(iter(canonical_thread_ids))
    if target_id not in mapped_by_id:
        raise CBLMaterializationError(
            f"Canonical issue evidence contradicts confirmed mappings for {provider}:{external_id}"
        )
    return mapped_by_id[target_id]


async def _create_series_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    series_identity: ExternalIdentity,
) -> Thread:
    """Create one empty series thread after the caller has acquired the queue lock."""
    max_position = await db.scalar(
        select(func.max(Thread.queue_position)).where(Thread.user_id == user_id)
    )
    thread = Thread(
        title=title.strip(),
        format="comic",
        issues_remaining=0,
        total_issues=0,
        next_unread_issue_id=None,
        reading_progress="not_started",
        queue_position=(max_position or 0) + 1,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()
    await link_thread_external_series(
        db,
        user_id=user_id,
        thread_id=thread.id,
        external_identity_id=series_identity.id,
        status="confirmed",
        evidence_source="cbl_reading_plan_adoption",
        confidence=1.0,
    )
    return thread


async def _insert_missing_issues(
    db: AsyncSession,
    *,
    user_id: int,
    thread: Thread,
    entries: Sequence[Mapping[str, object]],
) -> list[Issue]:
    """Merge safely ordered missing issues while preserving existing issue facts."""
    was_completed = thread.status == "completed"
    existing = list(
        (
            await db.scalars(
                select(Issue)
                .where(Issue.thread_id == thread.id)
                .order_by(Issue.position, Issue.id)
                .with_for_update()
            )
        ).all()
    )
    keyed_new: list[tuple[tuple[int, int, str], Mapping[str, object]]] = []
    for entry in entries:
        key = _issue_number_key(str(entry.get("issue_number") or ""))
        if key is None:
            raise CBLMaterializationError(
                f"Source position {entry.get('cbl_position')} has no safely ordered issue number"
            )
        keyed_new.append((key, entry))
    keyed_new.sort(key=lambda item: item[0])

    keyed_existing = [(_issue_number_key(issue.issue_number), issue) for issue in existing]
    if any(key is None for key, _issue in keyed_existing):
        raise CBLMaterializationError(
            f"Existing issues in thread {thread.id} are not safely orderable"
        )
    existing_order = [cast(tuple[int, int, str], key) for key, _issue in keyed_existing]
    if any(left >= right for left, right in zip(existing_order, existing_order[1:], strict=False)):
        raise CBLMaterializationError(
            f"Existing issues in thread {thread.id} are not in strict normalized order"
        )
    all_keys = [*existing_order, *(key for key, _entry in keyed_new)]
    if len(set(all_keys)) != len(all_keys):
        raise CBLMaterializationError("Series contains duplicate normalized issue numbers")

    await db.execute(text("SET CONSTRAINTS uq_issue_thread_position DEFERRED"))
    temporary_position = max((issue.position for issue in existing), default=0)
    created: list[Issue] = []
    for _key, entry in keyed_new:
        comicvine_issue_id = _comicvine_numeric_id(entry.get("comicvine_issue_id"))
        if comicvine_issue_id is None:
            raise CBLMaterializationError(
                f"Source position {entry.get('cbl_position')} lacks a usable ComicVine issue ID"
            )
        temporary_position += 1
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(entry["issue_number"]),
            position=temporary_position,
            status="unread",
        )
        db.add(issue)
        await db.flush()
        await confirm_comicvine_identity(
            db,
            user_id=user_id,
            issue_id=issue.id,
            comicvine_issue_id=comicvine_issue_id,
        )
        created.append(issue)

    merged = sorted(
        [
            *((cast(tuple[int, int, str], key), issue) for key, issue in keyed_existing),
            *((key, issue) for (key, _entry), issue in zip(keyed_new, created, strict=True)),
        ],
        key=lambda item: item[0],
    )
    for position, (_key, issue) in enumerate(merged, start=1):
        issue.position = position
    await db.flush()
    apply_thread_issue_tracking_state(thread, [issue for _key, issue in merged])
    if created:
        thread.status = "active"
    if was_completed and created:
        await move_to_front(thread.id, user_id, db, commit=False)
    return created


async def materialize_cbl_entries(
    db: AsyncSession,
    *,
    user_id: int,
    entries: Sequence[Mapping[str, object]],
) -> CBLMaterializationResult:
    """Materialize approved missing entries using stable identity evidence only."""
    if not entries:
        return CBLMaterializationResult({}, (), (), ())

    missing_by_series: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for entry in entries:
        if entry.get("adoption_class") != "missing_importable" or entry.get("adopted") is not True:
            raise CBLMaterializationError("Materializer received an entry that was not approved missing material")
        if _comicvine_numeric_id(entry.get("comicvine_issue_id")) is None:
            raise CBLMaterializationError(
                f"Source position {entry.get('cbl_position')} lacks a usable ComicVine issue ID"
            )
        series_key = _stable_series_key(entry)
        if series_key is None:
            raise CBLMaterializationError(
                f"Source position {entry.get('cbl_position')} lacks stable external series identity"
            )
        missing_by_series.setdefault(series_key, []).append(entry)

    await _acquire_queue_lock(user_id, db)
    issue_ids_by_position: dict[int, int] = {}
    reused_issue_ids: list[int] = []
    created_issue_ids: list[int] = []
    created_thread_ids: list[int] = []

    for (provider, external_id), series_entries in missing_by_series.items():
        canonical_thread_ids: set[int] = set()
        still_missing: list[Mapping[str, object]] = []
        for entry in series_entries:
            canonical = await resolve_canonical_issue(
                db,
                user_id=user_id,
                comicvine_issue_id=str(entry["comicvine_issue_id"]),
            )
            if canonical.canonical_issue_id is None:
                still_missing.append(entry)
                continue
            canonical_issue = await db.get(Issue, canonical.canonical_issue_id)
            if canonical_issue is None:
                raise CBLMaterializationError("Canonical issue disappeared during adoption")
            position = int(entry["cbl_position"])
            issue_ids_by_position[position] = canonical_issue.id
            reused_issue_ids.append(canonical_issue.id)
            canonical_thread_ids.add(canonical_issue.thread_id)

        series_identity, mapped_threads = await _confirmed_series_threads(
            db,
            user_id=user_id,
            provider=provider,
            external_id=external_id,
        )
        target = _target_from_series_evidence(
            provider=provider,
            external_id=external_id,
            mapped_threads=mapped_threads,
            canonical_thread_ids=canonical_thread_ids,
        )
        if not mapped_threads and len(canonical_thread_ids) == 1:
            target_id = next(iter(canonical_thread_ids))
            target = await db.scalar(
                select(Thread)
                .where(Thread.id == target_id, Thread.user_id == user_id)
                .with_for_update()
            )
            if target is None:
                raise CBLMaterializationError(
                    f"Canonical target for {provider}:{external_id} is unavailable"
                )
            await link_thread_external_series(
                db,
                user_id=user_id,
                thread_id=target.id,
                external_identity_id=series_identity.id,
                status="confirmed",
                evidence_source="cbl_reading_plan_adoption_existing_issue",
                confidence=1.0,
            )

        if not still_missing:
            continue
        if target is None:
            target = await _create_series_thread(
                db,
                user_id=user_id,
                title=str(series_entries[0].get("series_name") or "Imported series"),
                series_identity=series_identity,
            )
            created_thread_ids.append(target.id)
        created = await _insert_missing_issues(
            db,
            user_id=user_id,
            thread=target,
            entries=still_missing,
        )
        sorted_missing = sorted(
            still_missing,
            key=lambda entry: cast(
                tuple[int, int, str], _issue_number_key(str(entry.get("issue_number") or ""))
            ),
        )
        for entry, issue in zip(sorted_missing, created, strict=True):
            issue_ids_by_position[int(entry["cbl_position"])] = issue.id
            created_issue_ids.append(issue.id)

    return CBLMaterializationResult(
        issue_ids_by_source_position=issue_ids_by_position,
        reused_issue_ids=tuple(reused_issue_ids),
        created_issue_ids=tuple(created_issue_ids),
        created_thread_ids=tuple(created_thread_ids),
    )
