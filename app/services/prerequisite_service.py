"""Reader prerequisite authoring with global graph validation and stable identity."""

from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import prerequisite_repository as repository
from app.repositories import reading_list_authoring_repository as authoring_repository
from app.schemas.prerequisite import PrerequisiteCreate, PrerequisiteResponse
from app.services.reading_list_authoring import load_authoring_snapshot
from app.services.reading_list_cycle_validator import validate_reading_constraints
from app.services.reading_list_evaluator import ReadingPrerequisite


class PrerequisiteNotFoundError(ValueError):
    """The requested prerequisite or endpoint is unavailable to this reader."""


class HistoricalPrerequisiteError(ValueError):
    """Historical requirements require the separate reviewed conversion workflow."""


async def list_owned(db: AsyncSession, user_id: int) -> list[PrerequisiteResponse]:
    """Read provenance without classifying or modifying historical rows."""
    return [
        PrerequisiteResponse.model_validate(row) for row in await repository.list_owned(db, user_id)
    ]


async def create(db: AsyncSession, user_id: int, data: PrerequisiteCreate) -> PrerequisiteResponse:
    """Validate the complete execution graph before creating an idempotent pair."""
    await authoring_repository.lock_reader(db, user_id)
    issues = await authoring_repository.load_issues(db, user_id)
    owned_ids = {issue.id for issue in issues}
    if {data.source_issue_id, data.target_issue_id} - owned_ids:
        raise PrerequisiteNotFoundError("Issue not found")
    for row in await repository.list_owned(db, user_id):
        if (row.source_issue_id, row.target_issue_id) == (
            data.source_issue_id,
            data.target_issue_id,
        ):
            if row.origin != "reader":
                # A new explicit authoring request can adopt a historical pair.
                # Its archived existence alone did not activate it.
                snapshot, _ = await load_authoring_snapshot(db, user_id)
                candidate = ReadingPrerequisite(-1, data.source_issue_id, data.target_issue_id)
                validate_reading_constraints(
                    replace(snapshot, prerequisites=(*snapshot.prerequisites, candidate))
                )
                await repository.promote_reader(db, row, data.note)
                response = PrerequisiteResponse.model_validate(row)
                await db.commit()
                return response
            return PrerequisiteResponse.model_validate(row)
    snapshot, _ = await load_authoring_snapshot(db, user_id)
    candidate = ReadingPrerequisite(-1, data.source_issue_id, data.target_issue_id)
    validate_reading_constraints(
        replace(snapshot, prerequisites=(*snapshot.prerequisites, candidate))
    )
    row = await repository.add_reader(db, data.source_issue_id, data.target_issue_id, data.note)
    response = PrerequisiteResponse.model_validate(row)
    await db.commit()
    return response


async def update_note(
    db: AsyncSession, user_id: int, prerequisite_id: int, note: str | None
) -> PrerequisiteResponse:
    """Update only reader-authored prose, preserving stable endpoints."""
    await authoring_repository.lock_reader(db, user_id)
    for row in await repository.list_owned(db, user_id):
        if row.id == prerequisite_id:
            if row.origin != "reader":
                raise HistoricalPrerequisiteError("Historical prerequisite requires review")
            await repository.update_note(db, row, note)
            response = PrerequisiteResponse.model_validate(row)
            await db.commit()
            return response
    raise PrerequisiteNotFoundError("Prerequisite not found")


async def delete(db: AsyncSession, user_id: int, prerequisite_id: int) -> None:
    """Delete only new reader-authored requirements; historical data stays protected."""
    await authoring_repository.lock_reader(db, user_id)
    for row in await repository.list_owned(db, user_id):
        if row.id == prerequisite_id:
            if row.origin != "reader":
                raise HistoricalPrerequisiteError("Historical prerequisite requires review")
            await repository.remove(db, row)
            await db.commit()
            return
    raise PrerequisiteNotFoundError("Prerequisite not found")
