"""Read-only discovery of persisted CBL source lists for Reading Plans."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.cbl_reference import CBLSource, CBLSourceList
from app.models.user import User

router = APIRouter(prefix="/api/v1/issue-identity", tags=["issue-identity"])


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
    """Return bounded active CBL lists for the Reading Plan Add-material flow.

    Discovery is intentionally read-only. A returned list ID may be passed to
    the existing reconciliation/adoption-preview endpoints, but discovery never
    adopts material or mutates reader/source state.
    """
    del current_user  # Authentication is the only user-specific requirement here.

    query = (
        select(CBLSourceList, CBLSource.repository)
        .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
        .where(CBLSourceList.active.is_(True))
    )

    term = q.strip() if q else ""
    if term:
        pattern = f"%{term}%"
        query = query.where(
            or_(
                CBLSourceList.name.ilike(pattern),
                CBLSourceList.source_path.ilike(pattern),
            )
        )

    query = query.order_by(
        CBLSourceList.name.asc(),
        CBLSourceList.source_path.asc(),
        CBLSourceList.id.asc(),
    ).limit(limit)

    rows = (await db.execute(query)).all()
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
