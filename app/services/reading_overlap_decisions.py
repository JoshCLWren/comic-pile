"""Reader-facing write path for stored Reading List overlap decisions.

A reader approves one overlap choice per Reading List and exact Comic Vine
volume pair. The choice is durable, owner-scoped, and versioned by the list's
own ``overlap_decisions_updated_at`` token so a concurrent write is rejected
instead of silently overwriting another tab's approval. Membership upserts
never touch that token, so an approved choice survives a later membership
rewrite.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.repositories import reading_list_authoring_repository as authoring_repository
from app.repositories import reading_overlap_decision_repository as overlap_repository
from app.schemas.custom_cbl import (
    OverlapDecisionItem,
    OverlapDecisionSetResponse,
    OverlapVolumeCandidate,
)
from app.services.reading_list_authoring import load_authoring_snapshot
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import SeriesOverlapDecision
from app.services.reading_overlap_identity import normalized_volume_key

#: Detail code returned when a write uses a stale decision version token.
VERSION_CONFLICT_CODE = "reading_overlap_version_conflict"


def _as_utc(value: datetime) -> datetime:
    """Return one timestamp as an aware UTC value.

    Args:
        value: Timestamp supplied by a client or loaded from the database.

    Returns:
        The same instant expressed with an aware UTC timezone.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _guard_version(
    row: CustomCBLList, expected_updated_at: datetime | None
) -> None:
    """Reject a write that was based on a stale decision version token.

    Args:
        row: Owned Reading List row holding the current token.
        expected_updated_at: Token supplied by the client, or None to skip the
            check.

    Returns:
        None.

    Raises:
        HTTPException: With status 409 when the token no longer matches.
    """
    if expected_updated_at is None:
        return
    current = _as_utc(row.overlap_decisions_updated_at)
    if current != _as_utc(expected_updated_at):
        raise HTTPException(
            status_code=409,
            detail={
                "code": VERSION_CONFLICT_CODE,
                "message": "The Reading List's overlap decisions changed since they were read",
                "updated_at": current.isoformat(),
            },
        )


async def _owned_list(
    db: AsyncSession, user_id: int, list_id: int, *, for_update: bool = False
) -> CustomCBLList:
    """Load one owned Reading List or reject a missing or foreign list.

    Args:
        db: Current transaction.
        user_id: Reader whose ownership is checked.
        list_id: Reading List identifier.
        for_update: When true, acquire a shared lock (SELECT FOR SHARE) to
            prevent concurrent writes while reading the token and decisions.

    Returns:
        The owned Reading List row.

    Raises:
        HTTPException: With status 404 when the reader does not own the list.
    """
    row = await overlap_repository.load_owned_list(db, user_id, list_id, for_update=for_update)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Reading List {list_id} not found")
    return row


async def _decision_set(
    db: AsyncSession, *, user_id: int, list_id: int, updated_at: datetime
) -> OverlapDecisionSetResponse:
    """Build the public decision set of one owned Reading List.

    Args:
        db: Current transaction.
        user_id: Reader whose decisions are published.
        list_id: Reading List whose decisions are published.
        updated_at: Current decision version token of the list.

    Returns:
        The list's decisions and the reader's selectable volume candidates.
    """
    records = await overlap_repository.load_list_overlap_decisions(db, user_id, list_id)
    candidates = await overlap_repository.load_thread_volume_candidates(db, user_id)
    return OverlapDecisionSetResponse(
        list_id=list_id,
        updated_at=updated_at,
        decisions=[
            OverlapDecisionItem(
                id=record.id,
                continuing_volume_id=record.continuing_volume_id,
                waiting_volume_id=record.waiting_volume_id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ],
        candidate_volumes=[
            OverlapVolumeCandidate(
                thread_id=thread_id,
                thread_title=title,
                volume_id=volume_id,
            )
            for thread_id, title, volume_id in candidates
        ],
    )


async def _validate_projection(
    db: AsyncSession,
    user_id: int,
    projected: Mapping[int, tuple[SeriesOverlapDecision, ...]],
) -> None:
    """Prove that one projected decision set keeps the reader's graph acyclic.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose complete constraint graph is validated.
        projected: Complete replacement decision set keyed by Reading List ID.

    Returns:
        None.

    Raises:
        HTTPException: With status 422 when the projected graph contains a
            cycle.
    """
    snapshot, _names = await load_authoring_snapshot(
        db, user_id, overlap_decisions=projected
    )
    try:
        validate_reading_constraints(snapshot)
    except ReadingCycleError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "reading_list_cycle", "message": str(exc)},
        ) from exc


def _projected_decisions(
    grouped: Mapping[int, tuple[SeriesOverlapDecision, ...]],
    list_id: int,
    replaced: tuple[str, str],
    replacement: SeriesOverlapDecision,
) -> dict[int, tuple[SeriesOverlapDecision, ...]]:
    """Return the reader's complete decision set with one pair replaced.

    An approved direction supersedes the opposite direction for the same two
    volumes. Otherwise a reader who changes their answer would leave both
    contradictory choices stored, and the evaluator would waive both strict
    edges instead of honoring the reader's latest decision.

    Args:
        grouped: Durable decisions of every list keyed by Reading List ID.
        list_id: Reading List whose pair is replaced.
        replaced: Canonical continuing/waiting volume pair being replaced.
        replacement: Decision that replaces the pair.

    Returns:
        The complete replacement decision set keyed by Reading List ID.
    """
    # The ``superseded`` set covers both (continuing, waiting) and (waiting,
# continuing) volume-direction pairs, so that replacing a pair removes any
# existing choice in either direction for the same two volumes. This handles
# the invariant that ``replaced`` is always canonical (continuing, waiting)
# while stored decisions may exist in either direction.
    projected = {key: values for key, values in grouped.items() if key != list_id}
    superseded = {replaced, (replaced[1], replaced[0])}
    kept = tuple(
        decision
        for decision in grouped.get(list_id, ())
        if (decision.continuing_volume_id, decision.waiting_volume_id) not in superseded
    )
    projected[list_id] = (*kept, replacement)
    return projected


async def get_overlap_decision_set(
    db: AsyncSession, *, user_id: int, list_id: int
) -> OverlapDecisionSetResponse:
    """Return one owned Reading List's overlap decisions and version token.

    Args:
        db: Current transaction.
        user_id: Reader whose decisions are read.
        list_id: Reading List whose decisions are read.

    Returns:
        The list's decisions and the reader's selectable volume candidates.

    Raises:
        HTTPException: With status 404 when the reader does not own the list.
    """
    row = await _owned_list(db, user_id, list_id, for_update=True)
    return await _decision_set(
        db,
        user_id=user_id,
        list_id=list_id,
        updated_at=_as_utc(row.overlap_decisions_updated_at),
    )


async def save_overlap_decision(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    continuing_volume_id: str,
    waiting_volume_id: str,
    expected_updated_at: datetime | None = None,
) -> OverlapDecisionSetResponse:
    """Store one reader-approved overlap choice inside one owned Reading List.

    Args:
        db: Current transaction.
        user_id: Reader who owns the list and the choice.
        list_id: Reading List the choice belongs to.
        continuing_volume_id: Canonical key of the volume allowed to continue.
        waiting_volume_id: Canonical key of the volume allowed to keep waiting.
        expected_updated_at: Decision version token the client last read. None
            skips the concurrency check.

    Returns:
        The list's updated decision set and version token.

    Raises:
        HTTPException: With status 404 for a foreign list, 409 for a stale
            version token, and 422 for an unusable or cyclic choice.
    """
    await authoring_repository.lock_reader(db, user_id)
    row = await _owned_list(db, user_id, list_id, for_update=True)
    _guard_version(row, expected_updated_at)
    continuing_key = normalized_volume_key(continuing_volume_id)
    waiting_key = normalized_volume_key(waiting_volume_id)
    if continuing_key is None or waiting_key is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reading_overlap_invalid_volume",
                "message": "An overlap decision must name two exact Comic Vine volumes",
            },
        )
    if continuing_key == waiting_key:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reading_overlap_same_volume",
                "message": "An overlap decision must name two distinct volumes",
            },
        )
    resolved = await overlap_repository.resolve_volume_identity_ids(
        db, [continuing_key, waiting_key]
    )
    continuing_identity_id = resolved.get(continuing_key)
    waiting_identity_id = resolved.get(waiting_key)
    if continuing_identity_id is None or waiting_identity_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reading_overlap_unknown_volume",
                "message": "An overlap decision must name two known Comic Vine volumes",
            },
        )
    records = await overlap_repository.load_overlap_decisions(db, user_id)
    grouped = overlap_repository.group_decisions_by_list(records)
    projected = _projected_decisions(
        grouped,
        list_id,
        (continuing_key, waiting_key),
        SeriesOverlapDecision(continuing_key, waiting_key),
    )
    await _validate_projection(db, user_id, projected)
    await overlap_repository.upsert_overlap_decision(
        db,
        user_id=user_id,
        list_id=list_id,
        continuing_identity_id=continuing_identity_id,
        waiting_identity_id=waiting_identity_id,
        continuing_volume_id=continuing_key,
        waiting_volume_id=waiting_key,
    )
    updated_at = datetime.now(UTC)
    # The repository owns the token write. It preserves the list's own
    # updated_at so a decision change never rewrites the list revision.
    advanced = await overlap_repository.advance_overlap_decisions_token(
        db, user_id=user_id, list_id=list_id, updated_at=updated_at
    )
    if advanced is None:
        raise HTTPException(status_code=404, detail=f"Reading List {list_id} not found")
    await db.flush()
    # Build the response while still holding the lock, before committing.
    # The response is fully materialized here; no ORM model attributes are accessed
    # after this point or after `await db.commit()` below, so MissingGreenlet is avoided.
    response = await _decision_set(
        db,
        user_id=user_id,
        list_id=list_id,
        updated_at=_as_utc(advanced.overlap_decisions_updated_at),
    )
    await db.commit()
    return response


async def remove_overlap_decision(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    decision_id: int,
    expected_updated_at: datetime | None = None,
) -> OverlapDecisionSetResponse:
    """Remove one reader-approved overlap choice from one owned Reading List.

    Args:
        db: Current transaction.
        user_id: Reader who owns the list and the choice.
        list_id: Reading List the choice belongs to.
        decision_id: Decision identifier.
        expected_updated_at: Decision version token the client last read. None
            skips the concurrency check.

    Returns:
        The list's updated decision set and version token.

    Raises:
        HTTPException: With status 404 for a foreign list or unknown decision,
            409 for a stale version token, and 422 when removing the choice
            would make the reader's constraint graph cyclic.
    """
    await authoring_repository.lock_reader(db, user_id)
    row = await _owned_list(db, user_id, list_id, for_update=True)
    _guard_version(row, expected_updated_at)
    if (
        await overlap_repository.load_overlap_decision(db, user_id, list_id, decision_id)
        is None
    ):
        raise HTTPException(
            status_code=404, detail=f"Overlap decision {decision_id} not found"
        )
    # Validate the graph the removal would create before deleting anything, so
    # a rejected write leaves the stored choice and its version token untouched.
    records = await overlap_repository.load_overlap_decisions(db, user_id)
    projected = overlap_repository.group_decisions_by_list(
        record for record in records if record.id != decision_id
    )
    await _validate_projection(db, user_id, projected)
    removed = await overlap_repository.delete_overlap_decision(
        db, user_id=user_id, list_id=list_id, decision_id=decision_id
    )
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"Overlap decision {decision_id} not found"
        )
    updated_at = datetime.now(UTC)
    # The repository owns the token write. It preserves the list's own
    # updated_at so a decision change never rewrites the list revision.
    advanced = await overlap_repository.advance_overlap_decisions_token(
        db, user_id=user_id, list_id=list_id, updated_at=updated_at
    )
    if advanced is None:
        raise HTTPException(status_code=404, detail=f"Reading List {list_id} not found")
    await db.flush()
    # Build the response while still holding the lock, before committing
    response = await _decision_set(
        db,
        user_id=user_id,
        list_id=list_id,
        updated_at=_as_utc(advanced.overlap_decisions_updated_at),
    )
    await db.commit()
    return response
