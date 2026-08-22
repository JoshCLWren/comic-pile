"""API routes for browsing and uploading CBL reading lists."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, List, Set, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cbl_ingest import parse_cbl_file, CBLParseFailure, CBLBook
from app.database import get_db
from app.models.cbl_reference import CBLSource, CBLSourceList
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.schemas.cbl import (
    CBLSourceResponse,
    CBLSourceListResponse,
    CBLSourceWithListsResponse,
    CBLUploadResponse,
    CBLBookResponse,
)
from app.schemas.continuity_plan import (
    CrossoverTemplateConflictPreview,
    CrossoverTemplateIntersectionPreview,
    CrossoverTemplateItemPreview,
    CrossoverTemplateParallelCandidatePreview,
    CrossoverTemplateSerialSpinePreview,
    CrossoverTemplateUnresolvedMatchPreview,
    DerivedCrossoverTemplatePreview,
)
from app.services.crossover_templates import (
    CBLPlacement,
    TemplateEvidence,
    DerivedCrossoverTemplate,
    _unresolved_reason,
    derive_crossover_template,
    _story_arc_ids,
)

router = APIRouter(prefix="/api/v1/cbl", tags=["cbl"])


def _to_preview(template: DerivedCrossoverTemplate) -> DerivedCrossoverTemplatePreview:
    """Convert internal dataclasses into the public preview response."""
    return DerivedCrossoverTemplatePreview(
        items=[
            CrossoverTemplateItemPreview(
                issue_id=item.issue_id,
                suggested_position=item.suggested_position,
                role=item.role,
                confidence=item.confidence,
                explanation=item.explanation,
                source_paths=item.source_paths,
                target_story_arc_id=item.target_story_arc_id,
            )
            for item in template.items
        ],
        conflicts=[
            CrossoverTemplateConflictPreview(
                first_issue_id=conflict.first_issue_id,
                second_issue_id=conflict.second_issue_id,
                source_paths=conflict.source_paths,
            )
            for conflict in template.conflicts
        ],
        parallel_candidates=[
            CrossoverTemplateParallelCandidatePreview(
                first_issue_id=candidate.first_issue_id,
                second_issue_id=candidate.second_issue_id,
                source_paths=candidate.source_paths,
            )
            for candidate in template.parallel_candidates
        ],
        serial_spines=[
            CrossoverTemplateSerialSpinePreview(
                thread_id=spine.thread_id,
                issue_ids=spine.issue_ids,
                source_paths=spine.source_paths,
                explanation=spine.explanation,
            )
            for spine in template.serial_spines
        ],
        intersections=[
            CrossoverTemplateIntersectionPreview(
                first_issue_id=intersection.first_issue_id,
                second_issue_id=intersection.second_issue_id,
                source_paths=intersection.source_paths,
                explanation=intersection.explanation,
            )
            for intersection in template.intersections
        ],
        unresolved=[
            CrossoverTemplateUnresolvedMatchPreview(
                source_path=match.source_path,
                position=match.position,
                series_name=match.series_name,
                issue_number=match.issue_number,
                reason=match.reason,
            )
            for match in template.unresolved
        ],
    )


@router.get(
    "/sources",
    response_model=List[CBLSourceWithListsResponse],
    summary="List all CBL sources with their active lists",
)
async def list_cbl_sources(
    current_user: Annotated[object, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> List[CBLSourceWithListsResponse]:
    """Return all CBL sources and their active lists for browsing."""
    # We don't actually use current_user for filtering here because CBL sources are
    # considered public or shared across users. If per-source privacy is needed,
    # we can add it later.
    sources_result = await db.execute(select(CBLSource).order_by(CBLSource.repository))
    sources = sources_result.scalars().all()

    response: List[CBLSourceWithListsResponse] = []
    for source in sources:
        # Get active lists for this source
        lists_result = await db.execute(
            select(CBLSourceList)
            .where(CBLSourceList.source_id == source.id, CBLSourceList.active.is_(True))
            .order_by(CBLSourceList.source_path)
        )
        lists = lists_result.scalars().all()

        source_with_lists = CBLSourceWithListsResponse(
            id=source.id,
            repository=source.repository,
            revision_sha=source.revision_sha,
            synced_at=source.synced_at,
            created_at=source.created_at,
            updated_at=source.updated_at,
            lists=[
                CBLSourceListResponse(
                    id=cbllist.id,
                    source_id=cbllist.source_id,
                    source_path=cbllist.source_path,
                    name=cbllist.name,
                    declared_issue_count=cbllist.declared_issue_count,
                    content_hash=cbllist.content_hash,
                    revision_sha=cbllist.revision_sha,
                    active=cbllist.active,
                    created_at=cbllist.created_at,
                    updated_at=cbllist.updated_at,
                )
                for cbllist in lists
            ],
        )
        response.append(source_with_lists)

    return response


@router.get(
    "/sources/{source_id}/lists",
    response_model=List[CBLSourceListResponse],
    summary="List active CBL lists for a given source",
)
async def list_cbl_source_lists(
    source_id: int,
    current_user: Annotated[object, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> List[CBLSourceListResponse]:
    """Return all active CBL lists for a specific source."""
    # Verify the source exists
    source_result = await db.execute(
        select(CBLSource).where(CBLSource.id == source_id)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CBL source with ID {source_id} not found",
        )

    lists_result = await db.execute(
        select(CBLSourceList)
        .where(CBLSourceList.source_id == source_id, CBLSourceList.active.is_(True))
        .order_by(CBLSourceList.source_path)
    )
    lists = lists_result.scalars().all()

    return [
        CBLSourceListResponse(
            id=cbllist.id,
            source_id=cbllist.source_id,
            source_path=cbllist.source_path,
            name=cbllist.name,
            declared_issue_count=cbllist.declared_issue_count,
            content_hash=cbllist.content_hash,
            revision_sha=cbllist.revision_sha,
            active=cbllist.active,
            created_at=cbllist.created_at,
            updated_at=cbllist.updated_at,
        )
        for cbllist in lists
    ]


@router.post(
    "/upload",
    response_model=CBLUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload and parse a CBL file",
)
async def upload_cbl_file(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[object, Depends(get_current_user)],
) -> CBLUploadResponse:
    """
    Upload a CBL file, parse it, and return the parsed content for preview.

    The file is not persisted; it is only used for the current session.
    """
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".cbl"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a .cbl extension",
        )

    # Read the file content
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # Create a temporary directory and file to parse
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "uploaded.cbl"
        temp_path.write_bytes(content)

        try:
            # Parse the CBL file
            cbl_list = parse_cbl_file(temp_path, mirror_path=Path(temp_dir))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse CBL file: {exc}",
            ) from exc

    # Convert the parsed CBLList to our response format
    books: List[CBLBookResponse] = []
    for book in cbl_list.books:
        books.append(
            CBLBookResponse(
                position=book.position,
                series=book.series,
                issue_number=book.issue_number,
                volume_year=book.volume_year,
                publication_year=book.publication_year,
                comicvine_series_id=book.comicvine_series_id,
                comicvine_issue_id=book.comicvine_issue_id,
            )
        )

    return CBLUploadResponse(
        source_path=cbl_list.source_path,  # This will be "uploaded.cbl"
        name=cbl_list.name,
        declared_issue_count=cbl_list.declared_issue_count,
        content_hash=cbl_list.content_hash,
        books=books,
    )


async def _derive_crossover_template_from_uploaded_books(
    db: AsyncSession,
    books: List[CBLBook],
    target_story_arc_id: str | None = None,
) -> DerivedCrossoverTemplate:
    """Build a crossover template from uploaded CBL book entries.

    Similar to derive_crossover_template_from_lists but works with in-memory
    CBLBook objects from an uploaded file.
    """
    if not books:
        return DerivedCrossoverTemplate(items=(), conflicts=())

    # We'll need to map each book to a ComicPile issue if possible.
    # Collect all unique series IDs and issue IDs from the books that have them.
    series_ids: set[str] = set()
    issue_ids: set[str] = set()
    for book in books:
        if book.comicvine_series_id:
            series_ids.add(book.comicvine_series_id)
        if book.comicvine_issue_id:
            issue_ids.add(book.comicvine_issue_id)

    # Fetch external identities for series and issues in batches.
    # We'll do two separate queries: one for series, one for issues.
    series_identities: dict[str, ExternalIdentity] = {}
    if series_ids:
        series_result = await db.execute(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
                ExternalIdentity.external_id.in_(series_ids),
            )
        )
        for identity in series_result.scalars():
            series_identities[identity.external_id] = identity

    issue_identities: dict[str, ExternalIdentity] = {}
    if issue_ids:
        issue_result = await db.execute(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
                ExternalIdentity.external_id.in_(issue_ids),
            )
        )
        for identity in issue_result.scalars():
            issue_identities[identity.external_id] = identity

    # Now, for each book, try to find a confirmed issue mapping.
    placements_by_issue: dict[int, List[CBLPlacement]] = {}
    arcs_by_issue: dict[int, Set[str]] = {}
    issue_structure: dict[int, Tuple[int, int]] = {}  # issue_id -> (thread_id, thread_position)

    # We also need to know the source path for each book. Since all books come from the same
    # uploaded file, we can use a constant source path, e.g., "uploaded.cbl".
    source_path = "uploaded.cbl"

    for book in books:
        # Skip if we don't have a comicvine_issue_id (cannot map to an issue)
        if not book.comicvine_issue_id:
            continue

        issue_external_id = book.comicvine_issue_id
        issue_identity = issue_identities.get(issue_external_id)
        if not issue_identity:
            # No external identity for this issue ID -> unresolved
            continue

        # Check if there is a confirmed mapping from this external identity to a ComicPile issue
        mapping_result = await db.execute(
            select(IssueExternalIdentityMapping, Issue)
            .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
            .where(
                IssueExternalIdentityMapping.external_identity_id == issue_identity.id,
                IssueExternalIdentityMapping.status == "confirmed",
            )
        )
        mapping_row = mapping_result.first()
        if not mapping_row:
            # No confirmed mapping -> unresolved
            continue

        mapping, issue = mapping_row

        # Record the placement for this issue
        placement = CBLPlacement(source_path=source_path, position=book.position)
        placements_by_issue.setdefault(mapping.issue_id, []).append(placement)

        # Extract story arc IDs from the series identity if we have it
        series_id = book.comicvine_series_id
        series_identity = series_identities.get(series_id) if series_id else None
        if series_identity:
            arcs = _story_arc_ids(series_identity.metadata_json)
        else:
            arcs = set()
        if arcs:
            arcs_by_issue.setdefault(mapping.issue_id, set()).update(arcs)

        # Record the issue's thread and position for structure
        issue_structure[mapping.issue_id] = (issue.thread_id, issue.position)

    # Build TemplateEvidence for each issue that had at least one placement
    evidence: List[TemplateEvidence] = []
    for issue_id, placements in placements_by_issue.items():
        evidence.append(
            TemplateEvidence(
                issue_id=issue_id,
                cbl_placements=tuple(sorted(placements, key=lambda p: p.position)),
                story_arc_ids=tuple(sorted(arcs_by_issue.get(issue_id, set()))),
                target_story_arc_id=target_story_arc_id,
                thread_id=issue_structure[issue_id][0],
                thread_position=issue_structure[issue_id][1],
            )
        )

    # If no evidence, return empty template
    if not evidence:
        return DerivedCrossoverTemplate(items=(), conflicts=())

    # Derive the template from the evidence
    template = derive_crossover_template(tuple(evidence))

    # Now, we need to find unresolved matches: books that could not be mapped to a confirmed issue
    unresolved: List[CrossoverTemplateUnresolvedMatch] = []
    for book in books:
        # Determine if this book is unresolved:
        # - No comicvine_issue_id -> unresolved (no embedded identity)
        # - Has comicvine_issue_id but either:
        #   a) No external identity for that issue ID
        #   b) External identity exists but no confirmed mapping to an issue
        if not book.comicvine_issue_id:
            unresolved.append(
                CrossoverTemplateUnresolvedMatch(
                    source_path=source_path,
                    position=book.position,
                    series_name=book.series,
                    issue_number=book.issue_number,
                    reason="no embedded ComicVine issue identity",
                )
            )
            continue

        issue_external_id = book.comicvine_issue_id
        issue_identity = issue_identities.get(issue_external_id)
        if not issue_identity:
            unresolved.append(
                CrossoverTemplateUnresolvedMatch(
                    source_path=source_path,
                    position=book.position,
                    series_name=book.series,
                    issue_number=book.issue_number,
                    reason="no embedded ComicVine issue identity",
                )
            )
            continue

        # Check for confirmed mapping
        mapping_result = await db.execute(
            select(IssueExternalIdentityMapping)
            .where(
                IssueExternalIdentityMapping.external_identity_id == issue_identity.id,
                IssueExternalIdentityMapping.status == "confirmed",
            )
        )
        if not mapping_result.scalar_one_or_none():
            unresolved.append(
                CrossoverTemplateUnresolvedMatch(
                    source_path=source_path,
                    position=book.position,
                    series_name=book.series,
                    issue_number=book.issue_number,
                    reason="no confirmed ComicPile mapping",
                )
            )

    return DerivedCrossoverTemplate(
        items=template.items,
        conflicts=template.conflicts,
        parallel_candidates=template.parallel_candidates,
        serial_spines=template.serial_spines,
        intersections=template.intersections,
        unresolved=tuple(unresolved),
    )


@router.post(
    "/preview/uploaded",
    response_model=DerivedCrossoverTemplatePreview,
    summary="Preview a crossover template from an uploaded CBL file",
)
async def preview_uploaded_cbl_template(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[object, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    target_story_arc_id: Annotated[
        str | None, Form()
    ] = None,
) -> DerivedCrossoverTemplatePreview:
    """
    Upload a CBL file, parse it, and return a preview of the derived crossover template.
    """
    # Reuse the upload logic to parse the file
    upload_response = await upload_cbl_file(file, current_user)
    
    # Convert the CBLBookResponse objects back to CBLBook for our derivation function
    # We'll need to convert from the response format to the internal CBLBook.
    # Since CBLBookResponse is a subset of CBLBook (missing some fields that we don't need for derivation),
    # we can create CBLBook objects from the response.
    books: List[CBLBook] = []
    for book_resp in upload_response.books:
        books.append(
            CBLBook(
                position=book_resp.position,
                series=book_resp.series,
                issue_number=book_resp.issue_number,
                volume_year=book_resp.volume_year,
                publication_year=book_resp.publication_year,
                comicvine_series_id=book_resp.comicvine_series_id,
                comicvine_issue_id=book_resp.comicvine_issue_id,
            )
        )

    # Derive the template
    template = await _derive_crossover_template_from_uploaded_books(
        db, books, target_story_arc_id=target_story_arc_id
    )

    # Convert to preview response (we need to import the conversion function or reuse)
    # We can use the same _to_preview function from continuity_template.py, but we don't want to
    # import from there if it's not exposed. Let's define a similar conversion here.
    # We'll copy the _to_preview logic from continuity_template.py.
    return _to_preview(template)


@router.post(
    "/adopt/uploaded",
    status_code=status.HTTP_201_CREATED,
    summary="Adopt an uploaded CBL file as a continuity plan",
)
async def adopt_uploaded_cbl_template(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[object, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    plan_name: Annotated[str, Form()] = "Imported reading list",
    lane_id: Annotated[str, Form()] = "lane-1",
    lane_name: Annotated[str, Form()] = "Reading order",
    ordering_mode: Annotated[str, Form()] = "informational",
    target_story_arc_id: Annotated[
        str | None, Form()
    ] = None,
) -> dict:
    """
    Adopt an uploaded CBL file into an editable continuity plan.
    """
    # Parse the uploaded file
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # Create a temporary directory and file to parse
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "uploaded.cbl"
        temp_path.write_bytes(content)

        try:
            # Parse the CBL file
            cbl_list = parse_cbl_file(temp_path, mirror_path=Path(temp_dir))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse CBL file: {exc}",
            ) from exc

    # Convert the parsed CBLList to our internal CBLBook list
    books: List[CBLBook] = []
    for book in cbl_list.books:
        books.append(
            CBLBook(
                position=book.position,
                series=book.series,
                issue_number=book.issue_number,
                volume_year=book.volume_year,
                publication_year=book.publication_year,
                comicvine_series_id=book.comicvine_series_id,
                comicvine_issue_id=book.comicvine_issue_id,
            )
        )

    # Derive the template from the uploaded books
    template = await _derive_crossover_template_from_uploaded_books(
        db, books, target_story_arc_id=target_story_arc_id
    )

    if not template.items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No resolvable entries found in the uploaded CBL file",
        )

    # Validate that each item in the template corresponds to an issue owned by the current user
    # We'll extract the issue IDs from the template items
    issue_ids = [item.issue_id for item in template.items]
    # We need to check that each issue ID belongs to the current user
    # We can do this by querying the issues and checking their thread's user_id
    # But we can reuse the _validate_node_ownership function from continuity_plan API
    # by constructing the nodes in the same way as in adopt_crossover_template.
    # However, _validate_node_ownership expects a list of nodes with ref_id being the issue ID.
    # Let's build the nodes as we would for the plan.
    nodes = []
    for position, item in enumerate(template.items):
        nodes.append(
            {
                "id": f"{lane_id}-{item.issue_id}",  # We need a unique ID; we can use a prefix
                "node_type": "issue",
                "ref_id": item.issue_id,
                "lane_id": lane_id,
                "position": position,
            }
        )

    # Validate node ownership
    await _validate_node_ownership(db, user_id=current_user.id, nodes=nodes)

    # Build the lane
    lane = {"id": lane_id, "name": lane_name, "order": 0}

    # Build the payload for the continuity plan
    from app.api.continuity_plan import _replace_compiled_rules, _to_response, _refresh_blocked_state
    from app.models.continuity_plan import ContinuityPlan
    from app.schemas.continuity_plan import ContinuityPlanWrite

    payload = ContinuityPlanWrite(
        name=plan_name,
        ordering_mode=ordering_mode,
        lanes=[lane],
        nodes=nodes,
    )

    # Create the continuity plan
    plan = ContinuityPlan(
        user_id=current_user.id,
        name=payload.name,
        ordering_mode=payload.ordering_mode,
        lanes_json=[lane],
        nodes_json=nodes,
    )
    db.add(plan)
    await db.flush()
    try:
        await _replace_compiled_rules(
            db, user_id=current_user.id, plan=plan, payload=payload
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    if payload.ordering_mode == "strict_sequential":
        await _refresh_blocked_state(current_user.id, db)
    return _to_response(plan)