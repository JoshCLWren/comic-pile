"""Read-only discovery of persisted CBL source lists for Reading Plans."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.repositories.cbl_source_repository import (
    discover_cbl_source_lists as discover_source_rows,
    get_cbl_source_list_detail,
)
from app.services.cbl_source_public import (
    public_cbl_repository,
    public_cbl_source_path,
    public_cbl_source_ref,
)

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])


class CBLSourceListDiscoveryItem(BaseModel):
    """One active persisted source list that may be previewed by Add material."""

    id: int
    name: str
    source_path: str
    source_repository: str
    declared_issue_count: int | None
    content_hash: str
    revision_sha: str



class CBLSourceEntryDetail(BaseModel):
    """One ordered source occurrence in a CBL list."""

    position: int
    series_name: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_issue_id: str | None
    comicvine_volume_id: str | None


class CBLSourceListDetail(BaseModel):
    """Read-only detail for one CBL source list."""

    id: int
    name: str
    source_path: str
    source_repository: str
    source_ref: str
    declared_issue_count: int | None
    content_hash: str
    revision_sha: str
    entries: list[CBLSourceEntryDetail]

@router.get("/cbl-sources", response_model=list[CBLSourceListDiscoveryItem])
async def discover_cbl_source_lists(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[CBLSourceListDiscoveryItem]:
    """Return bounded active CBL lists for the Reading Plan Add-material flow."""
    del current_user
    rows = await discover_source_rows(db, query_text=q, limit=limit)
    return [
        CBLSourceListDiscoveryItem(
            id=source_list.id,
            name=source_list.name,
            source_path=source_list.source_path,
            source_repository=public_cbl_repository(repository),
            declared_issue_count=source_list.declared_issue_count,
            content_hash=source_list.content_hash,
            revision_sha=source_list.revision_sha,
        )
        for source_list, repository in rows
    ]


@router.get("/cbl-sources/{list_id}", response_model=CBLSourceListDetail)
async def get_cbl_source_list(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CBLSourceListDetail:
    """Return every ordered source occurrence for one CBL list (read-only)."""
    del current_user
    detail = await get_cbl_source_list_detail(db, list_id=list_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CBL source list not found")
    source_list, repository, entries = detail
    return CBLSourceListDetail(
        id=source_list.id,
        name=source_list.name,
        source_path=public_cbl_source_path(source_list.source_path),
        source_repository=public_cbl_repository(repository),
        source_ref=public_cbl_source_ref(repository, source_list.source_path),
        declared_issue_count=source_list.declared_issue_count,
        content_hash=source_list.content_hash,
        revision_sha=source_list.revision_sha,
        entries=[
            CBLSourceEntryDetail(
                position=entry.position,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                volume_year=entry.volume_year,
                publication_year=entry.publication_year,
                comicvine_issue_id=issue_id,
                comicvine_volume_id=series_id,
            )
            for entry, issue_id, series_id in entries
        ],
    )
