"""Reader-owned selection choices for one CBL source list.

The CBL browser is a review surface: a reader checks every source series and
issue on a first add, then narrows the selection. Those choices belong to the
reader, not to the shared source catalog, so they are stored per reader and per
source list. Reopening an already adopted source restores the saved choices
instead of resetting them to the all-checked first-add default.

This module owns that read/write contract; query construction lives in
:mod:`app.repositories.cbl_source_selection_repository`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import cbl_source_selection_repository
from app.schemas.shared_types import SourceBackedDecision

#: Reader decisions persisted for one source position.
SELECTION_INCLUDE = "include"
SELECTION_EXCLUDE = "exclude"


def _normalize_saved_decisions(raw: object) -> dict[int, bool]:
    """Return saved position decisions as a position-keyed include/exclude map.

    Args:
        raw: Stored ``entry_decisions`` JSON value.

    Returns:
        A mapping of CBL source position to the reader's include decision.
        Unusable values are ignored instead of failing the whole preview.
    """
    if not isinstance(raw, dict):
        return {}
    decisions: dict[int, bool] = {}
    for key, value in raw.items():
        try:
            position = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, bool):
            decisions[position] = value
    return decisions


async def load_saved_entry_decisions(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
) -> dict[int, bool]:
    """Return the reader's saved include/exclude choices for one source list.

    Args:
        db: Async database session.
        user_id: Reader whose saved choices are requested.
        cbl_source_list_id: CBL source list ID.

    Returns:
        Saved decisions keyed by CBL source position. Empty when the reader
        never saved a selection for this source.
    """
    selection = await cbl_source_selection_repository.find_source_selection(
        db,
        user_id=user_id,
        cbl_source_list_id=cbl_source_list_id,
    )
    if selection is None:
        return {}
    return _normalize_saved_decisions(selection.entry_decisions)


async def merge_saved_entry_decisions(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
    explicit_decisions: dict[int, SourceBackedDecision],
) -> dict[int, SourceBackedDecision]:
    """Return effective per-position decisions with saved choices as baseline.

    The reader's saved choices are the baseline for a re-opened source; a
    decision made in the current review always wins over the saved one.

    Args:
        db: Async database session.
        user_id: Reader whose saved choices provide the baseline.
        cbl_source_list_id: CBL source list ID.
        explicit_decisions: Decisions made in the current review, keyed by
            CBL source position.

    Returns:
        The effective per-position decisions.
    """
    saved = await load_saved_entry_decisions(
        db,
        user_id=user_id,
        cbl_source_list_id=cbl_source_list_id,
    )
    merged: dict[int, SourceBackedDecision] = {
        position: (
            SourceBackedDecision.INCLUDE if include else SourceBackedDecision.EXCLUDE
        )
        for position, include in saved.items()
    }
    merged.update(explicit_decisions)
    return merged


async def record_source_selection(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
    decisions: dict[int, str],
    content_hash: str,
    revision_sha: str,
) -> None:
    """Persist the reader's effective choices for one source list.

    Only decided positions are stored. A position the reader never decided
    stays absent, so a later review asks again instead of silently inheriting
    an old choice.

    Args:
        db: Async database session inside the caller's transaction.
        user_id: Reader whose choices are saved.
        cbl_source_list_id: CBL source list ID.
        decisions: Effective decisions keyed by CBL source position.
        content_hash: Source content hash observed at save time.
        revision_sha: Source revision observed at save time.
    """
    entry_decisions = {
        str(position): decision == SELECTION_INCLUDE
        for position, decision in decisions.items()
        if decision in {SELECTION_INCLUDE, SELECTION_EXCLUDE}
    }
    await cbl_source_selection_repository.upsert_source_selection(
        db,
        user_id=user_id,
        cbl_source_list_id=cbl_source_list_id,
        entry_decisions=entry_decisions,
        content_hash=content_hash,
        revision_sha=revision_sha,
    )
