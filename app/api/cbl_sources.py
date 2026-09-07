"""Read-only discovery of persisted CBL source lists for Reading Plans."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.repositories.cbl_source_repository import discover_cbl_source_lists as discover_source_rows

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
            source_repository=repository,
            declared_issue_count=source_list.declared_issue_count,
            content_hash=source_list.content_hash,
            revision_sha=source_list.revision_sha,
        )
        for source_list, repository in rows
    ]
