"""Service layer for ComicVine identity resolution and metadata correction."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import (
    ExternalIdentityMappingError,
    link_issue_external_identity,
    upsert_external_identity,
)
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.models.metadata_correction import IssueMetadataCorrection
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.thread import Thread
from app.schemas.comicvine_resolution import (
    CanonicalCorrection,
    ComicVineIssueCandidate,
    ComicVineResolveResponse,
    ComicVineResolvedIssue,
    ComicVineSeriesIssuesResponse,
    ComicVineSeriesSearchResponse,
    ComicVineSeriesResult,
    ImportIssueRequest,
    ImportIssueResponse,
    IssueIdentityMapping,
    IssueIdentityResponse,
    MetadataCorrectionRequest,
    MetadataCorrectionsResponse,
    MetadataRefreshResponse,
)
from app.services.comicvine_url import looks_like_url, parse_comicvine_url
from app.services.reading_order_placement import apply_insert, resolve_anchored_position
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError

logger = logging.getLogger(__name__)


def _coerce_provider_int(value: object) -> int | None:
    """Coerce a ComicVine value into an int when it is numeric.

    The provider returns fields such as ``start_year`` as strings, so both
    native ints and numeric strings must normalize to ints.

    Args:
        value: Raw provider field value.

    Returns:
        The parsed integer, or ``None`` when the value is not numeric.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


async def search_comicvine_series(
    client: ComicVineClient | None,
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
) -> ComicVineSeriesSearchResponse:
    """Search ComicVine volumes/series by title.

    Uses ComicVine ``limit``/``page`` semantics internally while maintaining
    offset-based API compatibility for callers. ComicVine ``/search`` paginates
    with a 1-based ``page`` number where each page holds ``limit`` results, so a
    0-based caller ``offset`` maps to ``page = offset // limit + 1``. The response
    exposes ``offset``, ``limit``, ``has_more``, and ``next_offset`` so the client
    can render a bounded load-more contract instead of dead-ending at page one.

    Args:
        client: Optional live ComicVine client. When ``None``, returns empty results.
        query: Search query string.
        limit: Maximum results to return (1-100).
        offset: Zero-based caller offset for the requested page.

    Returns:
        Series search results with paging metadata.
    """
    clamped_limit = max(1, min(limit, 100))
    clamped_offset = max(0, offset)
    # ComicVine /search pages with a 1-based page number (page size == limit).
    page = clamped_offset // clamped_limit + 1
    if client is None or not query.strip():
        return ComicVineSeriesSearchResponse(
            query=query,
            results=[],
            total_available=0,
            offset=clamped_offset,
            limit=clamped_limit,
            has_more=False,
            next_offset=None,
        )

    response = await client.request(
        "search",
        "search",
        {
            "query": query,
            "resources": "volume",
            "limit": clamped_limit,
            "page": page,
            "field_list": "id,name,publisher,start_year,count_of_issues,site_detail_url,image",
        },
    )
    results = response.payload.get("results")
    if not isinstance(results, list):
        return ComicVineSeriesSearchResponse(
            query=query,
            results=[],
            offset=clamped_offset,
            limit=clamped_limit,
        )

    series_results: list[ComicVineSeriesResult] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        volume_id = row.get("id")
        name = row.get("name")
        if not isinstance(volume_id, int) or not isinstance(name, str):
            continue
        publisher_raw = row.get("publisher")
        publisher = None
        if isinstance(publisher_raw, dict):
            publisher = publisher_raw.get("name")
        elif isinstance(publisher_raw, str):
            publisher = publisher_raw
        image_raw = row.get("image")
        image_url = None
        if isinstance(image_raw, dict):
            image_url = image_raw.get("medium_url") or image_raw.get("small_url")
        series_results.append(
            ComicVineSeriesResult(
                comicvine_volume_id=volume_id,
                name=name,
                publisher=publisher if isinstance(publisher, str) else None,
                start_year=_coerce_provider_int(row.get("start_year")),
                issue_count=_coerce_provider_int(row.get("count_of_issues")),
                site_detail_url=row.get("site_detail_url")
                if isinstance(row.get("site_detail_url"), str)
                else None,
                image_url=image_url,
            )
        )

    total = _coerce_provider_int(response.payload.get("number_of_total_results"))
    total_available = total if total is not None else len(series_results)
    loaded = clamped_offset + len(series_results)
    has_more = loaded < total_available if total_available is not None else False
    return ComicVineSeriesSearchResponse(
        query=query,
        results=series_results,
        total_available=total_available,
        offset=clamped_offset,
        limit=clamped_limit,
        has_more=has_more,
        next_offset=loaded if has_more else None,
    )


async def get_comicvine_series_issues(
    client: ComicVineClient | None,
    volume_id: int,
    *,
    series_name: str = "",
) -> ComicVineSeriesIssuesResponse:
    """Fetch all issues in a ComicVine volume/series.

    Args:
        client: Optional live ComicVine client. When ``None``, returns empty results.
        volume_id: ComicVine volume ID.
        series_name: Optional pre-fetched series name.

    Returns:
        Series issues response.
    """
    if client is None:
        return ComicVineSeriesIssuesResponse(
            comicvine_volume_id=volume_id,
            series_name=series_name or f"Volume {volume_id}",
            issues=[],
        )

    try:
        issues_rows = await client.fetch_volume_issues(volume_id)
    except Exception:
        logger.warning("Failed to fetch volume %d issues", volume_id, exc_info=True)
        return ComicVineSeriesIssuesResponse(
            comicvine_volume_id=volume_id,
            series_name=series_name or f"Volume {volume_id}",
            issues=[],
        )

    candidates: list[ComicVineIssueCandidate] = []
    for row in issues_rows:
        issue_id = row.get("id")
        if not isinstance(issue_id, int):
            continue
        issue_number = row.get("issue_number")
        name = row.get("name")
        cover_date = row.get("cover_date")
        store_date = row.get("store_date")
        image_raw = row.get("image")
        image_url = None
        if isinstance(image_raw, dict):
            image_url = image_raw.get("small_url") or image_raw.get("thumb_url")
        candidates.append(
            ComicVineIssueCandidate(
                comicvine_issue_id=issue_id,
                issue_number=str(issue_number) if issue_number is not None else None,
                name=str(name) if isinstance(name, str) else None,
                cover_date=str(cover_date) if isinstance(cover_date, str) else None,
                store_date=str(store_date) if isinstance(store_date, str) else None,
                image_url=image_url,
                site_detail_url=row.get("site_detail_url")
                if isinstance(row.get("site_detail_url"), str)
                else None,
            )
        )

    if not series_name:
        vol_response = await client.fetch_volume(volume_id)
        vol_obj = vol_response.payload.get("results")
        if isinstance(vol_obj, dict):
            volume_name = vol_obj.get("name")
            series_name = volume_name if isinstance(volume_name, str) else f"Volume {volume_id}"
        else:
            series_name = f"Volume {volume_id}"

    return ComicVineSeriesIssuesResponse(
        comicvine_volume_id=volume_id,
        series_name=series_name,
        issues=candidates,
    )


def _provider_image_url(image_raw: object) -> str | None:
    """Extract the best available image URL from a ComicVine image object."""
    if not isinstance(image_raw, dict):
        return None
    for key in ("medium_url", "small_url", "super_url", "thumb_url"):
        candidate = image_raw.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _provider_string(value: object) -> str | None:
    """Return a non-empty string value, else None."""
    return value if isinstance(value, str) and value else None


async def _resolve_comicvine_issue(
    client: ComicVineClient, issue_id: int
) -> ComicVineResolvedIssue:
    """Resolve one ComicVine issue from a direct issue URL."""
    response = await client.fetch_issue(issue_id)
    result = response.payload.get("results")
    if not isinstance(result, dict):
        raise ComicVineError("ComicVine issue response did not contain an object result")

    series_name: str | None = None
    volume_id: int | None = None
    volume_raw = result.get("volume")
    if isinstance(volume_raw, dict):
        raw_id = volume_raw.get("id")
        if isinstance(raw_id, int):
            volume_id = raw_id
        raw_name = volume_raw.get("name")
        if isinstance(raw_name, str):
            series_name = raw_name

    issue_number = result.get("issue_number")
    return ComicVineResolvedIssue(
        comicvine_issue_id=issue_id,
        series_name=series_name,
        volume_id=volume_id,
        issue_number=str(issue_number) if issue_number is not None else None,
        name=_provider_string(result.get("name")),
        cover_date=_provider_string(result.get("cover_date")),
        store_date=_provider_string(result.get("store_date")),
        image_url=_provider_image_url(result.get("image")),
        site_detail_url=_provider_string(result.get("site_detail_url")),
    )


async def _resolve_comicvine_volume(
    client: ComicVineClient,
    volume_id: int,
) -> tuple[ComicVineSeriesResult, list[ComicVineIssueCandidate]]:
    """Resolve one ComicVine volume and its issues from a direct volume URL."""
    response = await client.fetch_volume(volume_id)
    result = response.payload.get("results")
    if not isinstance(result, dict):
        raise ComicVineError("ComicVine volume response did not contain an object result")

    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ComicVineError("ComicVine volume response did not contain a name")

    publisher: str | None = None
    publisher_raw = result.get("publisher")
    if isinstance(publisher_raw, dict):
        publisher_name = publisher_raw.get("name")
        if isinstance(publisher_name, str):
            publisher = publisher_name
    elif isinstance(publisher_raw, str):
        publisher = publisher_raw
    volume = ComicVineSeriesResult(
        comicvine_volume_id=volume_id,
        name=name,
        publisher=publisher,
        start_year=_coerce_provider_int(result.get("start_year")),
        issue_count=_coerce_provider_int(result.get("count_of_issues")),
        site_detail_url=_provider_string(result.get("site_detail_url")),
        image_url=_provider_image_url(result.get("image")),
    )

    issues_response = await get_comicvine_series_issues(
        client, volume_id, series_name=name
    )
    return volume, issues_response.issues


async def resolve_comicvine_input(
    client: ComicVineClient | None,
    raw: str,
) -> ComicVineResolveResponse:
    """Resolve a correction input that may be a pasted ComicVine issue/volume URL.

    A recognized ComicVine issue URL resolves directly to a compact
    confirmation-card payload so the user does not need to find the volume via
    title search first. A recognized volume URL resolves to the volume plus its
    issues. Unsupported/malformed URLs and provider failures return a clear
    ``validation_error`` while leaving ordinary title search available.

    Args:
        client: Optional live ComicVine client.
        raw: The untrusted pasted input or ordinary search text.

    Returns:
        A discriminated resolve response.
    """
    trimmed = raw.strip()
    if not trimmed:
        return ComicVineResolveResponse(input=raw, kind="search")

    parsed = parse_comicvine_url(trimmed)
    if parsed is None:
        if looks_like_url(trimmed):
            return ComicVineResolveResponse(
                input=raw,
                kind="search",
                validation_error=(
                    "That doesn't look like a ComicVine issue or volume URL. Paste a "
                    "comicvine.gamespot.com link or search by title instead."
                ),
            )
        return ComicVineResolveResponse(input=raw, kind="search")

    if client is None:
        return ComicVineResolveResponse(
            input=raw,
            kind=parsed.kind,
            validation_error=(
                "ComicVine is not configured on this server, so pasted links cannot "
                "be resolved. Search by title instead."
            ),
        )

    try:
        if parsed.kind == "issue":
            issue = await _resolve_comicvine_issue(client, parsed.resource_id)
            return ComicVineResolveResponse(input=raw, kind="issue", issue=issue)
        volume, issues = await _resolve_comicvine_volume(client, parsed.resource_id)
        return ComicVineResolveResponse(
            input=raw,
            kind="volume",
            volume=volume,
            issues=issues,
        )
    except (ComicVineError, TimeoutError, ValueError):
        logger.warning(
            "comicvine_resolve_failed kind=%s id=%s",
            parsed.kind,
            parsed.resource_id,
            exc_info=True,
        )
        return ComicVineResolveResponse(
            input=raw,
            kind=parsed.kind,
            validation_error=(
                "We couldn't resolve that ComicVine link right now. Check the link "
                "or search by title instead."
            ),
        )


async def get_issue_identity_state(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
) -> IssueIdentityResponse:
    """Return the current identity mapping state for one ComicPile issue.

    Args:
        db: Async database session.
        user_id: Owner user ID for authorization.
        issue_id: ComicPile issue ID.

    Returns:
        Identity state response.
    """
    issue = await db.scalar(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    if issue is None:
        raise ExternalIdentityMappingError(f"Issue {issue_id} not found")

    thread = await db.get(Thread, issue.thread_id)

    mapping_query = (
        select(IssueExternalIdentityMapping, ExternalIdentity)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(IssueExternalIdentityMapping.issue_id == issue_id)
        .order_by(IssueExternalIdentityMapping.confidence.desc().nullslast())
    )
    mapping_result = await db.execute(mapping_query)
    mapping_rows = mapping_result.all()

    confirmed: list[IssueIdentityMapping] = []
    candidates: list[IssueIdentityMapping] = []
    has_unresolved = False

    for mapping, identity in mapping_rows:
        item = IssueIdentityMapping(
            external_identity_id=identity.id,
            provider=identity.provider,
            comicvine_id=identity.external_id,
            status=mapping.status,
            confidence=mapping.confidence,
            evidence_source=mapping.evidence_source,
            created_at=mapping.created_at,
        )
        if mapping.status == "confirmed":
            confirmed.append(item)
        elif mapping.status == "candidate":
            candidates.append(item)
        elif mapping.status == "unresolved":
            has_unresolved = True

    comicvine_issue_id: str | None = confirmed[0].comicvine_id if confirmed else None
    return IssueIdentityResponse(
        issue_id=issue_id,
        thread_id=issue.thread_id,
        thread_title=thread.title if thread else "",
        has_confirmed_identity=len(confirmed) > 0,
        comicvine_issue_id=comicvine_issue_id,
        confirmed_mappings=confirmed,
        candidate_mappings=candidates,
        has_unresolved=has_unresolved,
    )


async def confirm_comicvine_identity(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    comicvine_issue_id: int,
) -> IssueIdentityMapping:
    """Confirm a specific ComicVine identity for an issue, creating the mapping if needed.

    This uses the existing external identity service to create/confirm a mapping.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_id: ComicPile issue ID.
        comicvine_issue_id: ComicVine issue ID to confirm.

    Returns:
        The confirmed identity mapping.
    """
    identity = await upsert_external_identity(
        db,
        provider="comicvine",
        entity_type="issue",
        external_id=str(comicvine_issue_id),
        external_url=f"https://comicvine.gamespot.com/issue/4000-{comicvine_issue_id}/",
    )

    mapping = await link_issue_external_identity(
        db,
        user_id=user_id,
        issue_id=issue_id,
        external_identity_id=identity.id,
        status="confirmed",
        evidence_source="user_confirmed",
        confidence=1.0,
    )

    await db.flush()

    return IssueIdentityMapping(
        external_identity_id=identity.id,
        provider=identity.provider,
        comicvine_id=identity.external_id,
        status=mapping.status,
        confidence=mapping.confidence,
        evidence_source=mapping.evidence_source,
        created_at=mapping.created_at,
    )


async def replace_comicvine_identity(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    comicvine_issue_id: int,
    reason: str | None = None,
) -> IssueIdentityMapping:
    """Replace the current confirmed identity with a new one.

    Demotes the old confirmed mapping to 'rejected' and confirms the new one.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_id: ComicPile issue ID.
        comicvine_issue_id: New ComicVine issue ID to confirm.
        reason: Optional reason for replacement.

    Returns:
        The new confirmed identity mapping.
    """
    old_confirmed_result = await db.execute(
        select(IssueExternalIdentityMapping)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == "comicvine",
        )
    )
    old_mappings = old_confirmed_result.scalars().all()

    for old_mapping in old_mappings:
        old_mapping.status = "rejected"
        old_mapping.rejection_reason = reason or "replaced by user"

    await db.flush()

    return await confirm_comicvine_identity(
        db,
        user_id=user_id,
        issue_id=issue_id,
        comicvine_issue_id=comicvine_issue_id,
    )


async def request_provider_refresh(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
) -> MetadataRefreshResponse:
    """Request a provider metadata refresh for an issue with a confirmed identity.

    Returns a signal that the caller can use to trigger async hydration.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_id: ComicPile issue ID.

    Returns:
        Refresh response with the confirmed comicvine ID.
    """
    result = await db.execute(
        select(ExternalIdentity.external_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            Issue.id == issue_id,
            Thread.user_id == user_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == "comicvine",
        )
    )
    comicvine_id = result.scalar_one_or_none()

    return MetadataRefreshResponse(
        issue_id=issue_id,
        refreshed=comicvine_id is not None,
        comicvine_issue_id=comicvine_id,
    )


async def apply_metadata_correction(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    request: MetadataCorrectionRequest,
) -> CanonicalCorrection:
    """Apply a canonical metadata correction to an issue.

    The correction stores both the provider's raw value (if available) and
    the user's canonical value, with provenance.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_id: ComicPile issue ID.
        request: Correction request with field name and canonical value.

    Returns:
        The created correction record.
    """
    provider_value: str | None = None
    intelligence_result = await db.execute(
        select(ExternalIdentity.metadata_json)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
        )
        .limit(1)
    )
    identity_metadata = intelligence_result.scalar_one_or_none()
    if isinstance(identity_metadata, dict):
        provider_value = str(identity_metadata.get(request.field_name, "")) or None

    correction = IssueMetadataCorrection(
        issue_id=issue_id,
        field_name=request.field_name,
        provider_value=provider_value,
        canonical_value=request.canonical_value,
        provenance="user_correction",
        created_by=user_id,
    )
    db.add(correction)
    await db.flush()

    return CanonicalCorrection(
        id=correction.id,
        field_name=correction.field_name,
        provider_value=correction.provider_value,
        canonical_value=correction.canonical_value,
        provenance=correction.provenance,
        created_by=correction.created_by,
        created_at=correction.created_at,
    )


async def list_metadata_corrections(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
) -> MetadataCorrectionsResponse:
    """List all active (non-reverted) corrections for an issue.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_id: ComicPile issue ID.

    Returns:
        List of corrections.
    """
    result = await db.execute(
        select(IssueMetadataCorrection)
        .join(Issue, Issue.id == IssueMetadataCorrection.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            IssueMetadataCorrection.issue_id == issue_id,
            Thread.user_id == user_id,
            IssueMetadataCorrection.reverted_at.is_(None),
        )
        .order_by(IssueMetadataCorrection.created_at)
    )
    rows = result.scalars().all()

    corrections = [
        CanonicalCorrection(
            id=row.id,
            field_name=row.field_name,
            provider_value=row.provider_value,
            canonical_value=row.canonical_value,
            provenance=row.provenance,
            created_by=row.created_by,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return MetadataCorrectionsResponse(issue_id=issue_id, corrections=corrections)


async def revert_metadata_correction(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    correction_id: int,
) -> CanonicalCorrection:
    """Revert (soft-delete) a metadata correction.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_id: ComicPile issue ID.
        correction_id: Correction to revert.

    Returns:
        The reverted correction.
    """
    correction = await db.scalar(
        select(IssueMetadataCorrection)
        .join(Issue, Issue.id == IssueMetadataCorrection.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            IssueMetadataCorrection.id == correction_id,
            IssueMetadataCorrection.issue_id == issue_id,
            Thread.user_id == user_id,
            IssueMetadataCorrection.reverted_at.is_(None),
        )
    )
    if correction is None:
        raise ExternalIdentityMappingError(f"Correction {correction_id} not found")

    correction.reverted_at = datetime.now(UTC)
    await db.flush()

    return CanonicalCorrection(
        id=correction.id,
        field_name=correction.field_name,
        provider_value=correction.provider_value,
        canonical_value=correction.canonical_value,
        provenance=correction.provenance,
        created_by=correction.created_by,
        created_at=correction.created_at,
    )


class ImportTargetNotFoundError(Exception):
    """A referenced import target (reading order) does not exist for the user."""


class DuplicatePhysicalIssueError(Exception):
    """Import would create a second logical copy of an already-known physical issue."""

    def __init__(self, comicvine_issue_id: int, existing_issue_id: int) -> None:
        """Initialize the duplicate physical-issue error.

        Args:
            comicvine_issue_id: ComicVine issue ID that already exists.
            existing_issue_id: Existing canonical Issue ID for that physical issue.
        """
        super().__init__(
            f"ComicVine issue {comicvine_issue_id} already exists as issue {existing_issue_id}"
        )
        self.comicvine_issue_id = comicvine_issue_id
        self.existing_issue_id = existing_issue_id


async def import_comicvine_issue(
    db: AsyncSession,
    *,
    user_id: int,
    request: ImportIssueRequest,
) -> ImportIssueResponse:
    """Import a ComicVine issue as a new thread with its exact identity preserved.

    Atomically (pending the caller's commit) creates a thread, a single issue
    row, and a confirmed external-identity mapping so story-arc panels can
    match the imported thread back to its ComicVine issue. When a reading
    order is requested, the thread is inserted between the surrounding arc
    members using neighbor-anchored placement.

    Duplicate physical-issue prevention: when the requested ComicVine issue ID
    already has a confirmed mapping to a user-owned Issue, the import is
    rejected so future hydrations do not recreate a second logical copy.

    Args:
        db: Async database session; the caller owns the transaction commit.
        user_id: Owner who will receive the imported thread.
        request: Validated import payload with optional anchored placement.

    Returns:
        The created identifiers plus final reading-order placement.

    Raises:
        DuplicatePhysicalIssueError: The ComicVine issue already represents a
            known physical comic for this user.
        ImportTargetNotFoundError: ``request.reading_order_id`` does not exist
            for this user.
    """
    order: ReadingOrder | None = None
    if request.reading_order_id is not None:
        order = (
            await db.execute(
                select(ReadingOrder).where(
                    ReadingOrder.id == request.reading_order_id,
                    ReadingOrder.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if order is None:
            raise ImportTargetNotFoundError(
                f"Reading order {request.reading_order_id} not found"
            )

    from app.services.issue_identity_reconciliation import resolve_canonical_issue

    existing_canonical = await resolve_canonical_issue(
        db, user_id=user_id, comicvine_issue_id=str(request.comicvine_issue_id)
    )
    if existing_canonical.canonical_issue_id is not None:
        raise DuplicatePhysicalIssueError(request.comicvine_issue_id, existing_canonical.canonical_issue_id)

    max_position = (
        await db.execute(
            select(func.max(Thread.queue_position)).where(Thread.user_id == user_id)
        )
    ).scalar() or 0
    thread = Thread(
        title=request.title.strip(),
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=max_position + 1,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number=request.issue_number or "1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    mapping = await confirm_comicvine_identity(
        db,
        user_id=user_id,
        issue_id=issue.id,
        comicvine_issue_id=request.comicvine_issue_id,
    )

    response = ImportIssueResponse(
        thread_id=thread.id,
        issue_id=issue.id,
        external_identity_id=mapping.external_identity_id,
    )

    if order is not None:
        existing_items = (
            (
                await db.execute(
                    select(ReadingOrderItem)
                    .where(ReadingOrderItem.reading_order_id == order.id)
                    .order_by(ReadingOrderItem.position)
                )
            )
            .scalars()
            .all()
        )
        positions_by_thread = {item.thread_id: item.position for item in existing_items}
        target_pos = resolve_anchored_position(
            positions_by_thread,
            request.anchor_before_thread_id,
            request.anchor_after_thread_id,
            len(existing_items),
        )
        apply_insert(list(existing_items), thread.id, target_pos)
        db.add(
            ReadingOrderItem(
                reading_order_id=order.id,
                thread_id=thread.id,
                position=target_pos,
            )
        )
        response.reading_order_id = order.id
        response.position = target_pos
        response.total_items = len(existing_items) + 1

    return response
