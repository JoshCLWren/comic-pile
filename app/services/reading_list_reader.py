"""Project current list membership through the guarded execution authority."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.reading_list_reader import ReadingListReaderEntry, ReadingListReaderResponse
from app.services.custom_cbl import get_custom_cbl_response
from app.services.reading_eligibility_service import (
    get_execution_eligibility,
    project_blocking_explanation,
)


async def get_reading_list_reader(
    db: AsyncSession, *, user_id: int, list_id: int,
) -> ReadingListReaderResponse:
    """Return every current member with Roll's decision and provenance.

    Args:
        db: Request transaction.
        user_id: Authenticated owner; ownership is checked before graph loading.
        list_id: Current reader-owned list, never a plan copy.

    Returns:
        Ordered current entries, with explicit inactive/legacy/excluded states.
    """
    reading_list = await get_custom_cbl_response(db, user_id=user_id, list_id=list_id)
    snapshot = await get_execution_eligibility(db, user_id)
    entries: list[ReadingListReaderEntry] = []
    for entry in reading_list.entries:
        projected = ReadingListReaderEntry(**entry.model_dump(), availability="legacy")
        if entry.status == "read":
            projected.availability = "read"
        elif snapshot is not None:
            state = snapshot.threads.get(entry.thread_id)
            if entry.issue_id in snapshot.excluded_issue_ids:
                projected.availability = "excluded"
            elif state is None:
                projected.availability = "inactive"
            elif entry.issue_id != state.next_issue_id:
                projected.availability = "later"
            else:
                projected.availability = "available" if state.eligible else "blocked"
                projected.explanation = project_blocking_explanation(snapshot, entry.thread_id)
        entries.append(projected)
    return ReadingListReaderResponse(
        list_id=reading_list.id, name=reading_list.name, mode=reading_list.mode,
        execution_mode="option_e" if snapshot is not None else "legacy", entries=entries,
    )
