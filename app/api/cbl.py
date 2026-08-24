"""API routes for browsing, previewing, reconciling, and adopting CBL lists."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cbl_ingest import CBLBook, CBLParseFailure, parse_cbl_file
from app.database import get_db
from app.models.cbl_reference import CBLSource, CBLSourceList
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.user import User
from app.schemas.cbl import (
    CBLBookResponse,
    CBLSourceListResponse,
    CBLSourceWithListsResponse,
    CBLUploadResponse,
)
from app.schemas.continuity_plan import (
    ContinuityPlanResponse,
    ContinuityPlanWrite,
    CrossoverReconciliationDecision,
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
    DerivedCrossoverTemplate,
    ReconciliationDecisionInput,
    ReconciliationError,
    TemplateEvidence,
    build_adopted_plan_nodes,
    derive_crossover_template,
    resolve_adoption_order,
)

router = APIRouter(prefix="/api/v1/cbl", tags=["cbl"])

UPLOADED_SOURCE_PATH = "uploaded.cbl"

_reconciliations_adapter: TypeAdapter[tuple[CrossoverReconciliationDecision, ...]] = TypeAdapter(
    tuple[CrossoverReconciliationDecision, ...]
)


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


def _parse_reconciliations(raw: str) -> tuple[CrossoverReconciliationDecision, ...]:
    """Parse the JSON reconciliation decisions submitted with an upload."""
    if not raw.strip():
        return ()
    try:
        return _reconciliations_adapter.validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_reconciliations", "errors": exc.errors()},
        ) from exc


def _raise_reconciliation_error(exc: ReconciliationError) -> None:
    """Translate a structured reconciliation failure into an HTTP 422."""
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail)


@router.get(
    "/sources",
    response_model=List[CBLSourceWithListsResponse],
    summary="List all CBL sources with their active lists",
)
async def list_cbl_sources(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> List[CBLSourceWithListsResponse]:
    """Return all CBL sources and their active lists for browsing.

    Args:
        current_user: Authenticated user (sources are shared across readers).
        db: Async database session.

    Returns:
        Every synced CBL source with its active reading lists.
    """
    sources_result = await db.execute(select(CBLSource).order_by(CBLSource.repository))
    sources = sources_result.scalars().all()

    response: List[CBLSourceWithListsResponse] = []
    for source in sources:
        lists_result = await db.execute(
            select(CBLSourceList)
            .where(CBLSourceList.source_id == source.id, CBLSourceList.active.is_(True))
            .order_by(CBLSourceList.source_path)
        )
        lists = lists_result.scalars().all()

        response.append(
            CBLSourceWithListsResponse(
                id=source.id,
                repository=source.repository,
                revision_sha=source.revision_sha,
                synced_at=source.synced_at,
                created_at=source.created_at,
                updated_at=source.updated_at,
                lists=[
                    _to_list_response(cbllist)  # noqa: F821 - replaced below
                    for cbllist in lists
                ],
            )
        )

    return response


def _to_list_response(cbllist: CBLSourceList) -> CBLSourceListResponse:
    """Convert one persisted list into its API response."""
    return CBLSourceListResponse(
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


@router.get(
    "/sources/{source_id}/lists",
    response_model=List[CBLSourceListResponse],
    summary="List active CBL lists for a given source",
)
async def list_cbl_source_lists(
    source_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> List[CBLSourceListResponse]:
    """Return all active CBL lists for a specific source.

    Args:
        source_id: Database identifier of the CBL source.
        current_user: Authenticated user.
        db: Async database session.

    Returns:
        Active reading lists belonging to the requested source.

    Raises:
        HTTPException: 404 when the source does not exist.
    """
    source_result = await db.execute(select(CBLSource).where(CBLSource.id == source_id))
    if source_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CBL source with ID {source_id} not found",
        )

    lists_result = await db.execute(
        select(CBLSourceList)
        .where(CBLSourceList.source_id == source_id, CBLSourceList.active.is_(True))
        .order_by(CBLSourceList.source_path)
    )
    return [_to_list_response(cbllist) for cbllist in lists_result.scalars().all()]


async def _read_and_parse_upload(file: UploadFile) -> tuple[str, object]:
    """Validate and parse an uploaded CBL file without persisting it.

    Args:
        file: The uploaded multipart file part.

    Returns:
        Tuple of ``(source_path, parsed_list)`` for the uploaded content.

    Raises:
        HTTPException: 400 on a non-``.cbl`` filename, empty body, or parse error.
    """
    if not file.filename or not file.filename.lower().endswith(".cbl"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a .cbl extension",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / UPLOADED_SOURCE_PATH
        temp_path.write_bytes(content)
        try:
            parsed = parse_cbl_file(temp_path, mirror_path=Path(temp_dir))
        except CBLParseFailure as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse CBL file: {exc}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse CBL file: {exc}",
            ) from exc
    return UPLOADED_SOURCE_PATH, parsed


@router.post(
    "/upload",
    response_model=CBLUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload and parse a CBL file",
)
async def upload_cbl_file(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CBLUploadResponse:
    """Upload a CBL file, parse it, and return the parsed content for preview.

    Args:
        file: Uploaded ``.cbl`` document.
        current_user: Authenticated user.

    Returns:
        Parsed list metadata plus every ordered book entry.

    Raises:
        HTTPException: 400 when the upload cannot be parsed.
    """
    _, cbl_list = await _read_and_parse_upload(file)
    return _to_upload_response(cbl_list)


def _to_upload_response(cbl_list: object) -> CBLUploadResponse:
    """Convert a parsed CBL list into its API response."""
    books = [
        CBLBookResponse(
            position=book.position,
            series=book.series,
            issue_number=book.issue_number,
            volume_year=book.volume_year,
            publication_year=book.publication_year,
            comicvine_series_id=book.comicvine_series_id,
            comicvine_issue_id=book.comicvine_issue_id,
        )
        for book in cbl_list.books
    ]
    return CBLUploadResponse(
        source_path=cbl_list.source_path,
        name=cbl_list.name,
        declared_issue_count=cbl_list.declared_issue_count,
        content_hash=cbl_list.content_hash,
        books=books,
    )


async def derive_crossover_template_from_books(
    db: AsyncSession,
    books: Sequence[CBLBook],
    *,
    source_path: str,
    target_story_arc_id: str | None = None,
) -> DerivedCrossoverTemplate:
    """Build a crossover template from ordered CBL book entries.

    Args:
        db: Async database session.
        books: Ordered parsed book entries from one CBL source.
        source_path: Provenance path recorded for every placement.
        target_story_arc_id: Optional story arc that marks core membership.

    Returns:
        Derived template including unresolved entries for unmatched books.
    """
    if not books:
        return DerivedCrossoverTemplate(items=(), conflicts=(), unresolved=tuple())

    series_ids = {book.comicvine_series_id for book in books if book.comicvine_series_id}
    issue_ids = {book.comicvine_issue_id for book in books if book.comicvine_issue_id}

    series_identities: dict[str, ExternalIdentity] = {}
    if series_ids:
        series_result = await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
                ExternalIdentity.external_id.in_(series_ids),
            )
        )
        series_identities = {
            identity.external_id: identity for identity in series_result.scalars()
        }

    issue_identities: dict[str, ExternalIdentity] = {}
    if issue_ids:
        issue_result = await db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
                ExternalIdentity.external_id.in_(issue_ids),
            )
        )
        issue_identities = {identity.external_id: identity for identity in issue_result.scalars()}

    mapping_rows = []
    if issue_identities:
        mapping_result = await db.execute(
            select(IssueExternalIdentityMapping, Issue)
            .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
            .where(
                IssueExternalIdentityMapping.external_identity_id.in_(
                    [identity.id for identity in issue_identities.values()]
                ),
                IssueExternalIdentityMapping.status == "confirmed",
            )
        )
        mapping_rows = mapping_result.all()

    issue_by_identity_id = {mapping.external_identity_id: issue for mapping, issue in mapping_rows}
    arcs_by_issue: dict[int, set[str]] = {}

    placements_by_issue: dict[int, List[CBLPlacement]] = {}
    evidence_issues: dict[int, Issue] = {}
    unresolved: list[tuple[CBLBook, str]] = []

    for book in books:
        external_issue_id = book.comicvine_issue_id
        if not external_issue_id:
            unresolved.append((book, "no embedded ComicVine issue identity"))
            continue

        identity = issue_identities.get(external_issue_id)
        if identity is None:
            unresolved.append((book, "ComicVine issue identity not present in ComicPile"))
            continue

        issue = issue_by_identity_id.get(identity.id)
        if issue is None:
            unresolved.append((book, "no confirmed ComicPile mapping"))
            continue

        placements_by_issue.setdefault(issue.id, []).append(
            CBLPlacement(source_path=source_path, position=book.position)
        )
        evidence_issues.setdefault(issue.id, issue)

        series_identity = (
            series_identities.get(book.comicvine_series_id) if book.comicvine_series_id else None
        )
        if series_identity is not None:
            arcs_by_issue.setdefault(issue.id, set()).update(
                _story_arc_ids(series_identity.metadata_json)
            )

    evidence = tuple(
        TemplateEvidence(
            issue_id=issue.id,
            cbl_placements=tuple(sorted(placements_by_issue[issue.id], key=lambda p: p.position)),
            story_arc_ids=tuple(sorted(arcs_by_issue.get(issue.id, set()))),
            target_story_arc_id=target_story_arc_id,
            thread_id=issue.thread_id,
            thread_position=issue.position,
        )
        for issue in evidence_issues.values()
    )

    template = (
        derive_crossover_template(evidence) if evidence else DerivedCrossoverTemplate(items=())
    )
    return DerivedCrossoverTemplate(
        items=template.items,
        conflicts=template.conflicts,
        parallel_candidates=template.parallel_candidates,
        serial_spines=template.serial_spines,
        intersections=template.intersections,
        unresolved=tuple(
            CrossoverTemplateUnresolvedMatchData(
                source_path=source_path,
                position=book.position,
                series_name=book.series,
                issue_number=book.issue_number,
                reason=reason,
            ).as_match()
            for book, reason in unresolved
        ),
    )


class CrossoverTemplateUnresolvedMatchData:
    """Lightweight builder mirroring the service-layer unresolved match."""

    __slots__ = ("source_path", "position", "series_name", "issue_number", "reason")

    def __init__(
        self,
        *,
        source_path: str,
        position: int,
        series_name: str,
        issue_number: str,
        reason: str,
    ) -> None:
        """Store the unresolved-entry provenance fields."""
        self.source_path = source_path
        self.position = position
        self.series_name = series_name
        self.issue_number = issue_number
        self.reason = reason

    def as_match(self) -> object:
        """Return the service-layer dataclass instance for this entry."""
        from app.services.crossover_templates import CrossoverTemplateUnresolvedMatch

        return CrossoverTemplateUnresolvedMatch(
            source_path=self.source_path,
            position=self.position,
            series_name=self.series_name,
            issue_number=self.issue_number,
            reason=self.reason,
        )


@router.post(
    "/preview/uploaded",
    response_model=DerivedCrossoverTemplatePreview,
    summary="Preview a crossover template from an uploaded CBL file",
)
async def preview_uploaded_cbl_template(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    target_story_arc_id: Annotated[str | None, Form()] = None,
) -> DerivedCrossoverTemplatePreview:
    """Upload a CBL file and preview its derived crossover template.

    Read-only: never mutates user data or continuity rules.

    Args:
        file: Uploaded ``.cbl`` document.
        current_user: Authenticated user.
        db: Async database session.
        target_story_arc_id: Optional story arc marking core members.

    Returns:
        Non-blocking preview with items, structure, and unresolved entries.
    """
    source_path, cbl_list = await _read_and_parse_upload(file)
    template = await derive_crossover_template_from_books(
        db,
        cbl_list.books,
        source_path=source_path,
        target_story_arc_id=target_story_arc_id,
    )
    return _to_preview(template)


@router.post(
    "/adopt/uploaded",
    response_model=ContinuityPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Adopt an uploaded CBL file as an editable reading plan",
)
async def adopt_uploaded_cbl_template(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    plan_name: Annotated[str, Form()] = "Imported reading list",
    lane_id: Annotated[str, Form()] = "lane-1",
    lane_name: Annotated[str, Form()] = "Reading order",
    ordering_mode: Annotated[str, Form()] = "informational",
    target_story_arc_id: Annotated[str | None, Form()] = None,
    skipped_issue_ids: Annotated[str, Form()] = "",
    reconciliations: Annotated[str, Form()] = "",
) -> ContinuityPlanResponse:
    """Adopt an uploaded CBL file after explicit reader reconciliation.

    Every unresolved entry must be mapped or skipped before adoption so no
    source entry is silently dropped. Defaults stay informational: zero hard
    rules are compiled unless the caller selects strict semantics.

    Args:
        file: Uploaded ``.cbl`` document.
        current_user: Authenticated user.
        db: Async database session.
        plan_name: Name of the created reader-owned plan.
        lane_id: Lane identifier used inside the plan.
        lane_name: Human-readable lane label.
        ordering_mode: ``informational`` or ``strict_sequential``.
        target_story_arc_id: Optional story arc marking core members.
        skipped_issue_ids: JSON array of template issues removed by the reader.
        reconciliations: JSON array of per-entry map/skip decisions.

    Returns:
        The created continuity plan.

    Raises:
        HTTPException: 400 on parse failures, 422 on incomplete reconciliation,
            unowned references, or invalid decision payloads.
    """
    source_path, cbl_list = await _read_and_parse_upload(file)
    template = await derive_crossover_template_from_books(
        db,
        cbl_list.books,
        source_path=source_path,
        target_story_arc_id=target_story_arc_id,
    )
    return await _adopt_template_as_plan(
        db,
        current_user=current_user,
        template=template,
        plan_name=plan_name,
        lane_id=lane_id,
        lane_name=lane_name,
        ordering_mode=ordering_mode,
        decisions=_parse_reconciliations(reconciliations),
        raw_skipped_issue_ids=json.loads(skipped_issue_ids) if skipped_issue_ids.strip() else [],
    )


async def _adopt_template_as_plan(
    db: AsyncSession,
    *,
    current_user: User,
    template: DerivedCrossoverTemplate,
    plan_name: str,
    lane_id: str,
    lane_name: str,
    ordering_mode: str,
    decisions: tuple[CrossoverReconciliationDecision, ...],
    raw_skipped_issue_ids: object,
) -> ContinuityPlanResponse:
    """Resolve decisions, validate ownership, and persist one adopted plan.

    Raises:
        HTTPException: On invalid payloads or incomplete reconciliation.
    """
    try:
        skipped_issue_ids = _validated_skip_ids(raw_skipped_issue_ids)
        ordered_issue_ids = resolve_adoption_order(
            template,
            [
                ReconciliationDecisionInput(
                    source_path=decision.source_path,
                    position=decision.position,
                    action=decision.action,
                    issue_id=decision.issue_id,
                )
                for decision in decisions
            ],
            skipped_issue_ids,
        )
    except ReconciliationError as exc:
        _raise_reconciliation_error(exc)
        raise

    if not ordered_issue_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_adopted_plan"},
        )

    lane = {"id": lane_id, "name": lane_name, "order": 0}
    nodes = build_adopted_plan_nodes(
        template,
        ordered_issue_ids,
        decisions,
        lane_id=lane_id,
        node_id_prefix=f"{lane_id}-",
    )

    from app.api.continuity_plan import (
        _refresh_blocked_state,
        _replace_compiled_rules,
        _to_response,
        _validate_node_ownership,
    )
    from app.models.continuity_plan import ContinuityPlan

    payload = ContinuityPlanWrite(
        name=plan_name,
        ordering_mode=ordering_mode,  # type-checked by the schema below
        lanes=[lane],
        nodes=nodes,
    )
    await _validate_node_ownership(db, user_id=current_user.id, nodes=payload.nodes)

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
        await _replace_compiled_rules(db, user_id=current_user.id, plan=plan, payload=payload)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(plan)
    if payload.ordering_mode == "strict_sequential":
        await _refresh_blocked_state(current_user.id, db)
    return _to_response(plan)


def _validated_skip_ids(raw: object) -> list[int]:
    """Validate the JSON skip list submitted by a client."""
    if not isinstance(raw, list) or any(isinstance(item, bool) for item in raw):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_skipped_issue_ids"},
        )
    if any(not isinstance(item, int) or item <= 0 for item in raw):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_skipped_issue_ids"},
        )
    return raw
