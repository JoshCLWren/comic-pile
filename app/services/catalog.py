"""Catalog service layer for shared comic series and issue identities."""

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from comic_pile.comicvine_provider import ComicVineClient, ComicVineError

from app.external_identities import (
    link_issue_external_identity,
    link_thread_external_series,
    upsert_external_identity,
)
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping


MAPPING_STATUSES = frozenset({"unresolved", "candidate", "confirmed", "rejected"})


async def upsert_catalog_series(
    db: AsyncSession,
    *,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
) -> ExternalIdentity:
    """Upsert a canonical series into the shared catalog (idempotent).

    If a canonical existing series can be identified, it is returned rather than
    silently duplicating a run.

    Args:
        db: Async database session.
        provider: External provider name (normalized to lowercase).
        entity_type: Entity type, either "issue" or "series" (normalized to lowercase).
        external_id: Provider-specific identifier (whitespace trimmed).
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.

    Returns:
        The created or existing external identity.
    """
    return await upsert_external_identity(
        db,
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        external_url=external_url,
        metadata_json=metadata_json,
    )


async def upsert_catalog_issue(
    db: AsyncSession,
    *,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
) -> ExternalIdentity:
    """Upsert a canonical issue into the shared catalog (idempotent).

    If a canonical existing issue can be identified, it is returned rather than
    silently duplicating a run.

    Args:
        db: Async database session.
        provider: External provider name (normalized to lowercase).
        entity_type: Entity type, either "issue" or "series" (normalized to lowercase).
        external_id: Provider-specific identifier (whitespace trimmed).
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.

    Returns:
        The created or existing external identity.
    """
    return await upsert_external_identity(
        db,
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        external_url=external_url,
        metadata_json=metadata_json,
    )


async def attach_series_to_thread(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    series_external_id: str,
    status: str,
    evidence_source: str | None = None,
    confidence: float | None = None,
) -> ThreadExternalSeriesMapping:
    """Attach a series identity to a user's reading thread.

    Args:
        db: Async database session.
        user_id: Owner user ID for authorization.
        thread_id: Thread to associate with the series.
        series_external_id: The external series identity external_id (e.g., ComicVine volume ID).
        status: Mapping status (unresolved, candidate, confirmed, rejected).
        evidence_source: Optional source of the evidence.
        confidence: Optional confidence score (0-1).

    Returns:
        The created or updated thread-series mapping.
    """
    _validate_mapping_status(status)

    # First, upsert the series identity if not already present
    identity = await upsert_catalog_series(
        db,
        provider="comicvine",
        entity_type="series",
        external_id=series_external_id,
    )

    mapping = await link_thread_external_series(
        db,
        user_id=user_id,
        thread_id=thread_id,
        external_identity_id=identity.id,
        status=status,
        evidence_source=evidence_source,
        confidence=confidence,
    )
    return mapping


async def attach_issue_to_thread(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    issue_id: int,
    provider: str,
    entity_type: str,
    external_id: str,
    external_url: str | None = None,
    metadata_json: dict[str, object] | None = None,
    status: str,
    evidence_source: str | None = None,
    confidence: float | None = None,
) -> IssueExternalIdentityMapping:
    """Attach an issue identity to a user's reading thread.

    Args:
        db: Async database session.
        user_id: Owner user ID for authorization.
        thread_id: Thread to associate with the issue.
        issue_id: Internal ComicPile issue ID to attach the external identity to.
        provider: External provider name.
        entity_type: Entity type ("issue" or "series").
        external_id: Provider-specific identifier.
        external_url: Optional URL to the external resource.
        metadata_json: Optional arbitrary metadata from the provider.
        status: Mapping status (unresolved, candidate, confirmed, rejected).
        evidence_source: Optional source of the evidence.
        confidence: Optional confidence score (0-1).

    Returns:
        The created or updated issue-external identity mapping.
    """
    _validate_mapping_status(status)

    # First, upsert the issue identity if not already present
    identity = await upsert_external_identity(
        db,
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        external_url=external_url,
        metadata_json=metadata_json,
    )

    mapping = await link_issue_external_identity(
        db,
        user_id=user_id,
        issue_id=issue_id,
        external_identity_id=identity.id,
        status=status,
        evidence_source=evidence_source,
        confidence=confidence,
    )
    return mapping


def _validate_mapping_status(status: str) -> None:
    """Validate mapping status before persistence."""
    if status not in MAPPING_STATUSES:
        raise ValueError(f"unsupported mapping status: {status}")


async def reconcile_unmapped_issues(
    db: AsyncSession,
    *,
    provider: str = "comicvine",
    limit: int | None = None,
) -> dict[str, int]:
    """Bounded backfill reconciliation for unmapped issues.

    Prioritizes: active `next_unread_issue_id` threads → other unread
    in threads with confirmed series → threads needing series resolution.
    Reports confirmed / candidate / unresolved / skipped counts.

    Issues in threads with a confirmed series are resolved through the
    deterministic series resolver, which only confirms an exactly-one provider
    match and never fabricates pseudo-identities. Issues without a confirmed
    series are reported unresolved and left untouched.

    Idempotent on rerun: already-confirmed issues are skipped or excluded by
    selection, and no duplicate mappings are created.

    Args:
        db: Async database session.
        provider: External provider name.
        limit: Maximum number of issues to process.

    Returns:
        Dict with counts: confirmed, candidate, unresolved, skipped.
    """
    from app.models.issue import Issue
    from app.models.thread import Thread
    from app.services.comicvine_series_resolution import _run_series_resolution

    counts = {"confirmed": 0, "candidate": 0, "unresolved": 0, "skipped": 0}

    has_confirmed_series = (
        select(ThreadExternalSeriesMapping.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            ThreadExternalSeriesMapping.thread_id == Thread.id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.provider == provider,
            ExternalIdentity.entity_type == "series",
        )
        .exists()
    )

    query = (
        select(Issue)
        .options(selectinload(Issue.thread))
        .join(Thread, Issue.thread_id == Thread.id)
        .outerjoin(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .where(
            Issue.status.in_(("unread", "reading")),
            IssueExternalIdentityMapping.external_identity_id.is_(None)
            | ~IssueExternalIdentityMapping.status.in_(("confirmed",)),
        )
        .order_by(
            func.coalesce(Thread.next_unread_issue_id == Issue.id, False).desc(),
            has_confirmed_series.desc(),
            Issue.position,
        )
    )

    issues_result = await db.execute(query)
    issues = issues_result.scalars().unique().all()

    processed = 0
    for issue in issues:
        if limit is not None and processed >= limit:
            break

        existing_confirmed = await db.execute(
            select(IssueExternalIdentityMapping.id).where(
                IssueExternalIdentityMapping.issue_id == issue.id,
                IssueExternalIdentityMapping.status == "confirmed",
            )
        )
        if existing_confirmed.first() is not None:
            counts["skipped"] += 1
            processed += 1
            continue

        series_confirmed = await db.execute(
            select(ThreadExternalSeriesMapping)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
            )
            .where(
                ThreadExternalSeriesMapping.thread_id == issue.thread_id,
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.provider == provider,
                ExternalIdentity.entity_type == "series",
            )
            .limit(1)
        )
        series_mapping = series_confirmed.scalars().first()

        if series_mapping is None or issue.thread is None:
            counts["unresolved"] += 1
            processed += 1
            continue

        user_id = issue.thread.user_id
        await _run_series_resolution(issue.id, user_id)

        outcome = await db.execute(
            select(IssueExternalIdentityMapping.status)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id == issue.id,
                ExternalIdentity.provider == provider,
            )
            .order_by(IssueExternalIdentityMapping.id)
            .limit(1)
        )
        outcome_status = outcome.scalar_one_or_none()

        if outcome_status is None:
            counts["unresolved"] += 1
        elif outcome_status == "confirmed":
            counts["confirmed"] += 1
        else:
            counts["candidate"] += 1

        processed += 1

    return counts


async def search_catalog_series(
    db: AsyncSession,
    *,
    search: str | None = None,
    provider: str = "comicvine",
    limit: int = 50,
) -> list[ExternalIdentity]:
    """Search for canonical series in the shared catalog.

    Args:
        db: Database session.
        search: Optional search term to match against series external_id.
        provider: Filter by provider name (default: comicvine).
        limit: Maximum number of results to return (hard capped at 50).

    Returns:
        List of matching external identities for series.
    """
    from app.repositories.catalog_repository import search_catalog_series as repo_search
    
    return await repo_search(db, search=search, provider=provider, limit=limit)


async def search_catalog_issues(
    db: AsyncSession,
    *,
    search: str | None = None,
    provider: str = "comicvine",
    series_external_id: str | None = None,
    limit: int = 50,
) -> list[ExternalIdentity]:
    """Search for canonical issues in the shared catalog.

    Args:
        db: Database session.
        search: Optional search term to match against issue external_id.
        provider: Filter by provider name (default: comicvine).
        series_external_id: Filter by series external_id to scope the search.
        limit: Maximum number of results to return (hard capped at 50).

    Returns:
        List of matching external identities for issues.
    """
    from app.repositories.catalog_repository import search_catalog_issues as repo_search
    
    return await repo_search(db, search=search, provider=provider, series_external_id=series_external_id, limit=limit)


async def list_series_mappings(
    db: AsyncSession,
    *,
    thread_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[ThreadExternalSeriesMapping]:
    """List thread-series mappings.

    Args:
        db: Database session.
        thread_id: Optional filter by thread ID.
        status: Optional filter by mapping status.
        limit: Maximum number of results to return.

    Returns:
        List of thread-series mappings.
    """
    from app.repositories.catalog_repository import list_series_mappings as repo_list
    
    return await repo_list(db, thread_id=thread_id, status=status, limit=limit)


async def list_issue_mappings(
    db: AsyncSession,
    *,
    issue_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[IssueExternalIdentityMapping]:
    """List issue-external identity mappings.

    Args:
        db: Database session.
        issue_id: Optional filter by issue ID.
        status: Optional filter by mapping status.
        limit: Maximum number of results to return.

    Returns:
        List of issue-external identity mappings.
    """
    from app.repositories.catalog_repository import list_issue_mappings as repo_list
    
    return await repo_list(db, issue_id=issue_id, status=status, limit=limit)


async def preview_series_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    origin_issue_id: int,
    provider: str,
    provider_series_external_id: str,
) -> dict[str, object]:
    """Preview a series mapping with safe scoping and classification.
    
    Args:
        db: Database session.
        user_id: User ID for authorization.
        origin_issue_id: The anchor issue ID for the mapping preview.
        provider: External provider name (e.g., "comicvine").
        provider_series_external_id: Provider-specific series identifier.
        
    Returns:
        Preview response with scope information, counts, and classified rows.
    """
    from app.repositories.catalog_repository import get_series_with_issues, get_issue_by_id

    # Get the origin issue to establish context
    origin_issue = await get_issue_by_id(db, origin_issue_id, user_id)
    if origin_issue is None:
        return {
            "preview_token": None,
            "scope": {
                "status": "unavailable",
                "scope_key": None,
                "origin_issue_id": origin_issue_id,
                "series_label": None,
                "basis": "origin_issue_not_found",
            },
            "provider_series": None,
            "counts": {
                "already_confirmed": 0,
                "safe_exact_match": 0,
                "needs_review_ambiguous": 0,
                "needs_review_conflict": 0,
                "unresolved": 0,
                "excluded_special": 0,
            },
            "rows": [],
            "issued_at": time.time(),
            "expires_at": None,
        }
    
    # Try local catalog first
    series_info, issues_with_mappings = await get_series_with_issues(
        db, provider=provider, series_external_id=provider_series_external_id, user_id=user_id
    )
    
    # If not found locally, try ComicVine API (local-first)
    client = None
    if series_info is None:
        client = _get_comicvine_client()
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="provider_unavailable",
            )
        try:
            volume_response = await client.fetch_volume(int(provider_series_external_id))
            volume_data = volume_response.payload.get("results")
            if isinstance(volume_data, dict):
                series_info = {
                    "id": str(volume_data.get("id")),
                    "name": volume_data.get("name"),
                    "publisher": volume_data.get("publisher", {}).get("name") if volume_data.get("publisher") else None,
                    "start_year": volume_data.get("start_year"),
                    "count_of_issues": volume_data.get("count_of_issues"),
                    "site_detail_url": volume_data.get("site_detail_url"),
                    "image": volume_data.get("image"),
                }

                # Fetch issues from ComicVine
                issues_rows = await client.fetch_volume_issues(int(provider_series_external_id))
                issues_with_mappings = []

                for row in issues_rows:
                    if isinstance(row, dict):
                        issue_number = row.get("issue_number")
                        if issue_number is None:
                            continue

                        provider_issue_id = row.get("id")
                        try:
                            pid = int(provider_issue_id) if provider_issue_id is not None else 0
                        except (TypeError, ValueError):
                            pid = 0
                        issue_info = {
                            "issue_id": pid if pid != 0 else 0,
                            "issue_number": str(issue_number),
                            "title": row.get("name"),
                            "thread_id": None,
                            "thread_title": None,
                            "current_mapping_status": "unresolved",
                            "classification": "unresolved",
                        }
                        issues_with_mappings.append(issue_info)

        except HTTPException:
            raise
        except (ComicVineError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="provider_unavailable",
            ) from exc
        except Exception as exc:  # pragma: no cover - safety net
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="provider_unavailable",
            ) from exc
    
    # Ensure origin issue is included in the mapping check for conflict detection
    # even if it's mapped to a different series
    origin_mapping_provider = origin_issue.get("provider")
    origin_mapping_external_id = origin_issue.get("external_id")
    origin_mapping_status = origin_issue.get("current_mapping_status")
    if (origin_mapping_provider and origin_mapping_external_id and origin_mapping_status == "confirmed"):
        # Check if origin issue is already in the list (by issue_id)
        origin_in_list = any(
            info.get("issue_id") == origin_issue.get("issue_id")
            for info in issues_with_mappings
        )
        if not origin_in_list:
            issues_with_mappings.append({
                "issue_id": origin_issue.get("issue_id"),
                "issue_number": origin_issue.get("issue_number"),
                "title": origin_issue.get("title"),
                "thread_id": origin_issue.get("thread_id"),
                "thread_title": origin_issue.get("thread_title"),
                "current_mapping_status": origin_mapping_status,
                "provider": origin_mapping_provider,
                "external_id": origin_mapping_external_id,
                "confidence": origin_issue.get("confidence"),
                "classification": "unresolved",
                "_is_origin": True,
            })
    
    # If we still don't have series info, return unavailable scope
    if series_info is None:
        return {
            "preview_token": None,
            "scope": {
                "status": "unavailable",
                "scope_key": None,
                "origin_issue_id": origin_issue_id,
                "series_label": None,
                "basis": "series_not_found",
            },
            "provider_series": None,
            "counts": {
                "already_confirmed": 0,
                "safe_exact_match": 0,
                "needs_review_ambiguous": 0,
                "needs_review_conflict": 0,
                "unresolved": 0,
                "excluded_special": 0,
            },
            "rows": [],
            "issued_at": time.time(),
            "expires_at": None,
        }
    
    # Classify issues and determine safe scope
    counts = {
        "already_confirmed": 0,
        "safe_exact_match": 0,
        "needs_review_ambiguous": 0,
        "needs_review_conflict": 0,
        "unresolved": 0,
        "excluded_special": 0,
    }
    
    classified_rows = []
    scope_key = None

    origin_number_raw = origin_issue.get("issue_number")
    origin_number = str(origin_number_raw) if isinstance(origin_number_raw, str) else ""

    # Pre-compute normalized counts for duplicate detection (unique exact requirement)
    # Exclude the origin issue (_is_origin flag) since it's the anchor, not part of the series issues
    normalized_counts: dict[str, int] = {}
    for info in issues_with_mappings:
        if info.get("_is_origin"):
            continue
        num = info.get("issue_number", "")
        if isinstance(num, str) and not _is_special_issue(num) and not _is_ambiguous(num):
            norm = _normalize_issue_number(num)
            if norm:
                normalized_counts[norm] = normalized_counts.get(norm, 0) + 1

    for issue_info in issues_with_mappings:
        raw_number = issue_info.get("issue_number", "")
        issue_number = str(raw_number) if isinstance(raw_number, str) else ""

        # Check if it's a special issue (annual, special, etc.)
        if _is_special_issue(issue_number):
            classification = "excluded_special"
            counts["excluded_special"] += 1
        elif _is_conflicting_mapping(issue_info, provider, provider_series_external_id):
            classification = "needs_review_conflict"
            counts["needs_review_conflict"] += 1
        elif _is_ambiguous(issue_number):
            classification = "needs_review_ambiguous"
            counts["needs_review_ambiguous"] += 1
        elif issue_info.get("current_mapping_status") == "confirmed":
            classification = "already_confirmed"
            counts["already_confirmed"] += 1
        elif _is_exact_match(issue_number, origin_number):
            norm = _normalize_issue_number(issue_number)
            if norm and normalized_counts.get(norm, 0) == 1:
                classification = "safe_exact_match"
                counts["safe_exact_match"] += 1
                if scope_key is None:
                    scope_key = f"exact:{origin_issue_id}:{issue_number}"
            else:
                classification = "needs_review_ambiguous"
                counts["needs_review_ambiguous"] += 1
        else:
            classification = "unresolved"
            counts["unresolved"] += 1

        issue_info["classification"] = classification
        issue_info["proposed_mapping"] = classification in ["safe_exact_match", "already_confirmed"]
        issue_info["default_selected"] = classification == "safe_exact_match"

        classified_rows.append(issue_info)
    
    # Determine if scope is available
    scope_status = "available" if scope_key is not None else "unavailable"
    scope_basis = "insufficient_non_thread_evidence" if scope_key is None else "exact_match_found"

    # Spec: unavailable scope due to insufficient evidence returns zero counts and empty rows
    if scope_status == "unavailable":
        counts = {
            "already_confirmed": 0,
            "safe_exact_match": 0,
            "needs_review_ambiguous": 0,
            "needs_review_conflict": 0,
            "unresolved": 0,
            "excluded_special": 0,
        }
        classified_rows = []

    # Generate preview token if scope is available
    preview_token = None
    issued_at = time.time()
    expires_at = issued_at + 600 if scope_status == "available" else None
    if scope_status == "available":
        issue_numbers = [str(row.get("issue_number", "")) for row in classified_rows if row.get("issue_number")]
        classification_digest = "|".join(
            f"{cls}:{counts[cls]}"
            for cls in [
                "already_confirmed",
                "safe_exact_match",
                "needs_review_ambiguous",
                "needs_review_conflict",
                "unresolved",
                "excluded_special",
            ]
        )
        preview_token = _generate_preview_token(
            user_id=user_id,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
            origin_issue_id=origin_issue_id,
            scope_key=scope_key or "",
            issued_at=issued_at,
            expires_at=expires_at or issued_at,
            issue_numbers=issue_numbers,
            classification_digest=classification_digest,
        )

    return {
        "preview_token": preview_token,
        "scope": {
            "status": scope_status,
            "scope_key": scope_key,
            "origin_issue_id": origin_issue_id,
            "series_label": series_info.get("name") if isinstance(series_info.get("name"), str) else None,  # type: ignore[union-attr]
            "basis": scope_basis,
        },
        "provider_series": series_info,
        "counts": counts,
        "rows": classified_rows,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def _get_comicvine_client():
    """Build a ComicVine client from environment settings."""
    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        return None

    cache_dir = Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicvine-cache"))
    return ComicVineClient(api_key=api_key, cache_dir=cache_dir)


def _normalize_issue_number(value: str) -> str:
    """Normalize an issue number for exact comparison."""
    normalized = re.sub(r"[^0-9.]", "", value.lower().strip())
    normalized = normalized.strip(".")
    return normalized


def _is_special_issue(issue_number: str) -> bool:
    """Check if issue number indicates a special/annual issue."""
    stripped = issue_number.strip().lower()
    if not stripped:
        return True
    # Roman numerals are not special issues - they are ambiguous numbering
    if re.fullmatch(r"[ivx]+", stripped):
        return False
    # Purely non-numeric or annual/special keywords
    if re.search(r"\b(annual|special|hc|tpb|gn|omnibus|deluxe|absolute|hardcover|trade paperback|graphic novel)\b", stripped):
        return True
    if re.fullmatch(r"[^0-9]*", stripped):
        return True
    if re.search(r"\.[^0-9]+$", stripped):
        return True
    return False


def _is_exact_match(issue_number: str, origin_issue_number: str) -> bool:
    """Check if issue number exactly matches the origin issue number."""
    if not issue_number or not origin_issue_number:
        return False
    return _normalize_issue_number(issue_number) == _normalize_issue_number(origin_issue_number)


def _is_conflicting_mapping(issue_info: dict, provider: str, series_external_id: str) -> bool:
    """Check if issue has a confirmed mapping that conflicts with the selected series."""
    if issue_info.get("current_mapping_status") != "confirmed":
        return False
    issue_provider = issue_info.get("provider")
    # If provider differs, it's a conflict (cross-provider mapping conflict)
    if issue_provider != provider:
        return True
    # Same provider: we cannot reliably determine series-level conflict without
    # additional data (issue's volume/series not stored locally). Defer to review.
    return False


def _is_ambiguous(issue_number: str) -> bool:
    """Check if issue number is ambiguous."""
    # Fractional, roman, suffixed, or named numbering is never bulk-safe.
    ambiguous_patterns = [
        r"\d+\.\d+",  # Fractional numbers (e.g., "1.5", "0.5")
        r"^[ivx]+$",  # Roman numerals
        r"^[a-z]+$",  # Letters only
        r"\.\d+$",  # Decimal suffixes
        r"\d+[a-zA-Z]",  # Named variants like "1A", "2B"
        r"\d+\s*-\s*\d+",  # Ranges like "1-2"
        r"#",  # Hash-prefixed like "#1"
    ]

    issue_number_lower = issue_number.lower()
    for pattern in ambiguous_patterns:
        if re.search(pattern, issue_number_lower):
            return True
    return False


def _generate_preview_token(
    user_id: int,
    provider: str,
    provider_series_external_id: str,
    origin_issue_id: int,
    scope_key: str,
    issued_at: float,
    expires_at: float,
    issue_numbers: list[str] | None = None,
    classification_digest: str | None = None,
) -> str:
    """Generate an HMAC-signed preview token."""
    # Use the application secret key; fall back to env for test isolation
    secret_key = os.environ.get("PREVIEW_TOKEN_SECRET_KEY", "").strip()
    if not secret_key:
        from app.config import get_auth_settings

        secret_key = get_auth_settings().secret_key
    if not secret_key:
        raise ValueError("Preview token secret is not configured")

    # Create token payload
    payload = {
        "user_id": user_id,
        "provider": provider,
        "provider_series_external_id": provider_series_external_id,
        "origin_issue_id": origin_issue_id,
        "scope_key": scope_key,
        "issue_numbers": issue_numbers or [],
        "classification_digest": classification_digest or "",
        "issued_at": issued_at,
        "expires_at": expires_at,
    }

    # Generate signature
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Combine payload and signature
    token_data = {
        "payload": payload,
        "signature": signature,
    }

    return json.dumps(token_data)
