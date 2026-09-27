"""Catalog service layer for shared comic series and issue identities."""

import asyncio
import hashlib
import hmac
import json
import logging
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
from app.services.errors import ConflictError, InvalidRequestError


logger = logging.getLogger(__name__)

MAPPING_STATUSES = frozenset({"unresolved", "candidate", "confirmed", "rejected"})

#: Provider whose confirmed issue identities this module hydrates after commit.
COMMIT_PROVIDER = "comicvine"

#: In-process dedup registry for post-commit metadata hydration tasks.
_PENDING_HYDRATIONS: dict[int, asyncio.Task[None]] = {}


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


SERIES_MAPPING_CLASSIFICATIONS = (
    "already_confirmed",
    "safe_exact_match",
    "needs_review_ambiguous",
    "needs_review_conflict",
    "unresolved",
    "excluded_special",
)

NEEDS_REVIEW_CLASSIFICATIONS = frozenset(
    {"needs_review_ambiguous", "needs_review_conflict", "unresolved"}
)

USER_SERIES_CONFIRMATION_EVIDENCE = "user_series_confirmation"

APPROVED_ROW_PREFIX = "issue:"

COMMIT_DETAIL_PREVIEW_STALE = "preview_stale"
COMMIT_DETAIL_PREVIEW_EXPIRED = "preview_expired"
COMMIT_DETAIL_CONFIRMED_MAPPING_CONFLICT = "confirmed_mapping_conflict"
COMMIT_DETAIL_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
COMMIT_DETAIL_INVALID_APPROVED_ROW = "invalid_approved_row"


def _zero_series_mapping_counts() -> dict[str, int]:
    """Return a zeroed classification count map for series mapping scope."""
    return dict.fromkeys(SERIES_MAPPING_CLASSIFICATIONS, 0)


def _series_mapping_digest(counts: dict[str, int]) -> str:
    """Build the stable classification digest bound into a preview token.

    Args:
        counts: Classification counts for the scoped rows.

    Returns:
        Deterministic digest string over the ordered classification counts.
    """
    return "|".join(f"{name}:{counts[name]}" for name in SERIES_MAPPING_CLASSIFICATIONS)


def _unavailable_series_mapping_scope(
    origin_issue_id: int,
    basis: str,
) -> dict[str, object]:
    """Build the read-only scope payload for an unavailable preview.

    Args:
        origin_issue_id: The anchor issue ID for the mapping preview.
        basis: Reason the scope could not be established.

    Returns:
        Scope payload with zeroed counts, no rows, and no token material.
    """
    return {
        "scope": {
            "status": "unavailable",
            "scope_key": None,
            "origin_issue_id": origin_issue_id,
            "series_label": None,
            "basis": basis,
        },
        "provider_series": None,
        "counts": _zero_series_mapping_counts(),
        "rows": [],
        "issued_at": time.time(),
        "expires_at": None,
        "issue_numbers": [],
        "classification_digest": _series_mapping_digest(_zero_series_mapping_counts()),
    }


async def resolve_series_mapping_scope(
    db: AsyncSession,
    *,
    user_id: int,
    origin_issue_id: int,
    provider: str,
    provider_series_external_id: str,
) -> dict[str, object]:
    """Re-derive the current series mapping scope and classification for a preview.

    This is the single source of truth for both the read-only preview and the
    commit-time revalidation of a referenced preview. Commit recomputes this scope
    against current issue numbers, scope evidence, mapping state, and selected
    provider identities, then compares the result with the facts bound into the
    signed preview token.

    Args:
        db: Database session.
        user_id: User ID for authorization.
        origin_issue_id: The anchor issue ID for the mapping preview.
        provider: External provider name (e.g., "comicvine").
        provider_series_external_id: Provider-specific series identifier.

    Returns:
        Scope payload with the scope status, provider series, counts, classified
        rows, and the ``issue_numbers`` / ``classification_digest`` material a
        commit must revalidate.

    Raises:
        HTTPException: If the provider cannot be reached for a series that is
            absent from the local catalog.
    """
    from app.repositories.catalog_repository import get_series_with_issues, get_issue_by_id

    # Get the origin issue to establish context
    origin_issue = await get_issue_by_id(db, origin_issue_id, user_id)
    if origin_issue is None:
        return _unavailable_series_mapping_scope(origin_issue_id, "origin_issue_not_found")

    # Try local catalog first
    series_info, issues_with_mappings = await get_series_with_issues(
        db, provider=provider, series_external_id=provider_series_external_id, user_id=user_id
    )

    # If not found locally, try ComicVine API (local-first)
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
                            "comicpile_issue_id": None,
                            "issue_number": str(issue_number),
                            "title": row.get("name"),
                            "thread_id": None,
                            "thread_title": None,
                            "provider": provider,
                            "external_id": str(provider_issue_id) if provider_issue_id is not None else None,
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
                "comicpile_issue_id": origin_issue.get("issue_id"),
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
        return _unavailable_series_mapping_scope(origin_issue_id, "series_not_found")

    # Classify issues and determine safe scope
    counts = _zero_series_mapping_counts()

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
        elif _is_conflicting_mapping(issue_info, provider):
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
        counts = _zero_series_mapping_counts()
        classified_rows = []

    issued_at = time.time()
    issue_numbers = [str(row.get("issue_number", "")) for row in classified_rows if row.get("issue_number")]

    return {
        "scope": {
            "status": scope_status,
            "scope_key": scope_key,
            "origin_issue_id": origin_issue_id,
            "series_label": series_info.get("name") if isinstance(series_info.get("name"), str) else None,
            "basis": scope_basis,
        },
        "provider_series": series_info,
        "counts": counts,
        "rows": classified_rows,
        "issued_at": issued_at,
        "expires_at": issued_at + 600 if scope_status == "available" else None,
        "issue_numbers": issue_numbers,
        "classification_digest": _series_mapping_digest(counts),
    }


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
    resolved = await resolve_series_mapping_scope(
        db,
        user_id=user_id,
        origin_issue_id=origin_issue_id,
        provider=provider,
        provider_series_external_id=provider_series_external_id,
    )

    scope = resolved["scope"]
    if not isinstance(scope, dict):
        raise RuntimeError("series mapping scope payload is malformed")

    preview_token = None
    if scope["status"] == "available":
        preview_token = _generate_preview_token(
            user_id=user_id,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
            origin_issue_id=origin_issue_id,
            scope_key=str(scope["scope_key"] or ""),
            issued_at=float(resolved["issued_at"]),
            expires_at=float(resolved["expires_at"] or resolved["issued_at"]),
            issue_numbers=list(resolved["issue_numbers"]),
            classification_digest=str(resolved["classification_digest"]),
        )

    return {
        "preview_token": preview_token,
        "scope": scope,
        "provider_series": resolved["provider_series"],
        "counts": resolved["counts"],
        "rows": resolved["rows"],
        "issued_at": resolved["issued_at"],
        "expires_at": resolved["expires_at"],
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


def _is_conflicting_mapping(issue_info: dict, provider: str) -> bool:
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


def verify_preview_token(token: str, expected_user_id: int) -> dict[str, object]:
    """Verify an HMAC-signed preview token and check expiry and ownership.

    Args:
        token: JSON token string produced by ``_generate_preview_token``.
        expected_user_id: User id that must match the token payload.

    Returns:
        The verified payload dict.

    Raises:
        HTTPException: If the token is malformed, tampered, expired, or not
            bound to the expected user.
    """
    secret_key = os.environ.get("PREVIEW_TOKEN_SECRET_KEY", "").strip()
    if not secret_key:
        from app.config import get_auth_settings

        secret_key = get_auth_settings().secret_key
    if not secret_key:
        raise ValueError("Preview token secret is not configured")

    try:
        token_data = json.loads(token)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_preview_token",
        ) from exc

    payload = token_data.get("payload") if isinstance(token_data, dict) else None
    signature = token_data.get("signature") if isinstance(token_data, dict) else None
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_preview_token",
        )

    payload_json = json.dumps(payload, sort_keys=True)
    expected_sig = hmac.new(
        secret_key.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_preview_token",
        )

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)) or float(expires_at) <= time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="preview_token_expired",
        )

    payload_user = payload.get("user_id")
    if payload_user != expected_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_preview_token",
        )

    return payload

def _commit_conflict(detail: str) -> ConflictError:
    """Build a 409-mapped domain error for a series mapping commit.

    Args:
        detail: Client-safe contract detail string.

    Returns:
        ConflictError carrying the contract detail.
    """
    return ConflictError(detail)


def _verify_commit_preview_token(preview_token: str, user_id: int) -> dict[str, object]:
    """Validate the signed preview token referenced by a commit request.

    Args:
        preview_token: JSON token string produced by the preview endpoint.
        user_id: User id that must match the token payload.

    Returns:
        The verified token payload with every material field type-checked.

    Raises:
        ConflictError: If the token is expired, tampered, or missing bound facts.
    """
    try:
        payload = verify_preview_token(preview_token, user_id)
    except HTTPException as exc:
        if exc.detail == "preview_token_expired":
            raise _commit_conflict(COMMIT_DETAIL_PREVIEW_EXPIRED) from exc
        raise _commit_conflict(COMMIT_DETAIL_PREVIEW_STALE) from exc

    required: dict[str, type] = {
        "provider": str,
        "provider_series_external_id": str,
        "origin_issue_id": int,
        "scope_key": str,
        "classification_digest": str,
    }
    for field, expected_type in required.items():
        value = payload.get(field)
        if not isinstance(value, expected_type) or value == "":
            raise _commit_conflict(COMMIT_DETAIL_PREVIEW_STALE)
    return payload


def _parse_approved_row_ids(approved_row_ids: list[str]) -> list[int]:
    """Parse approved ``issue:<id>`` row identifiers into ComicPile issue IDs.

    Args:
        approved_row_ids: Raw row identifiers supplied by the caller.

    Returns:
        Ordered, de-duplicated ComicPile issue IDs.

    Raises:
        InvalidRequestError: If any row identifier is malformed.
    """
    parsed: list[int] = []
    for row_id in approved_row_ids:
        if not row_id.startswith(APPROVED_ROW_PREFIX):
            raise InvalidRequestError(COMMIT_DETAIL_INVALID_APPROVED_ROW)
        suffix = row_id[len(APPROVED_ROW_PREFIX):]
        if not suffix.isdigit():
            raise InvalidRequestError(COMMIT_DETAIL_INVALID_APPROVED_ROW)
        issue_id = int(suffix)
        if issue_id <= 0:
            raise InvalidRequestError(COMMIT_DETAIL_INVALID_APPROVED_ROW)
        if issue_id not in parsed:
            parsed.append(issue_id)
    return parsed


def _material_request_digest(
    payload: dict[str, object],
    approved_issue_ids: list[int],
) -> str:
    """Digest the complete material commit request bound to an idempotency key.

    The digest covers the referenced token's material facts and the approved rows,
    so reusing one key with a different token or a different approved set is
    detectable as a conflict rather than silently replayed.

    Args:
        payload: Verified preview token payload.
        approved_issue_ids: Parsed approved ComicPile issue IDs.

    Returns:
        Hex SHA-256 digest of the canonical material request.
    """
    token_issue_numbers = payload.get("issue_numbers")
    material = {
        "provider": payload.get("provider"),
        "provider_series_external_id": payload.get("provider_series_external_id"),
        "origin_issue_id": payload.get("origin_issue_id"),
        "scope_key": payload.get("scope_key"),
        "classification_digest": payload.get("classification_digest"),
        "issue_numbers": sorted(str(value) for value in token_issue_numbers)
        if isinstance(token_issue_numbers, list)
        else [],
        "approved_issue_ids": sorted(approved_issue_ids),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scope_matches_token(scope: dict[str, object], payload: dict[str, object]) -> bool:
    """Check whether the recomputed scope still matches the referenced preview.

    Args:
        scope: Recomputed series mapping scope payload.
        payload: Verified preview token payload.

    Returns:
        True when every bound material fact is unchanged.
    """
    if scope.get("status") != "available":
        return False
    if scope.get("scope_key") != payload.get("scope_key"):
        return False
    if scope.get("classification_digest") != payload.get("classification_digest"):
        return False
    token_issue_numbers = payload.get("issue_numbers")
    if not isinstance(token_issue_numbers, list):
        return False
    current_issue_numbers = scope.get("issue_numbers")
    if not isinstance(current_issue_numbers, list):
        return False
    return sorted(str(value) for value in current_issue_numbers) == sorted(
        str(value) for value in token_issue_numbers
    )


def _comicpile_rows_by_id(scope: dict[str, object]) -> dict[int, dict[str, object]]:
    """Index the current scope rows that resolve to a ComicPile issue.

    Args:
        scope: Recomputed series mapping scope payload.

    Returns:
        Mapping of ComicPile issue ID to its current scope row.
    """
    rows = scope.get("rows")
    if not isinstance(rows, list):
        return {}
    indexed: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        issue_id = row.get("comicpile_issue_id")
        if isinstance(issue_id, int) and issue_id > 0:
            indexed[issue_id] = row
    return indexed


def _row_provider_external_id(row: dict[str, object]) -> str | None:
    """Return the provider issue identity a scope row is bound to.

    Args:
        row: Current scope row.

    Returns:
        The provider issue external ID, or ``None`` when the row has none.
    """
    external_id = row.get("external_id")
    if isinstance(external_id, str) and external_id.strip():
        return external_id
    return None


def _response_from_receipt_payload(response_json: object) -> dict[str, object] | None:
    """Rebuild a logical commit response from a stored receipt.

    Args:
        response_json: Stored ``response_json`` value from a commit receipt.

    Returns:
        The stored logical response, or ``None`` when the receipt holds no result.
    """
    if not isinstance(response_json, dict):
        return None
    required = (
        "confirmed_issue_ids",
        "already_confirmed_issue_ids",
        "needs_review_issue_ids",
        "hydration_queued_issue_ids",
        "series_mapping",
    )
    if any(key not in response_json for key in required):
        return None
    return response_json


def _queued_hydration_issue_ids(response: dict[str, object]) -> list[int]:
    """Extract the hydration-queued issue IDs from a logical commit response.

    Args:
        response: Logical commit response payload.

    Returns:
        Ordered, de-duplicated ComicPile issue IDs queued for hydration.
    """
    queued = response.get("hydration_queued_issue_ids")
    if not isinstance(queued, list):
        return []
    ids: list[int] = []
    for value in queued:
        if isinstance(value, int) and value > 0 and value not in ids:
            ids.append(value)
    return ids


async def _run_series_mapping_hydration(issue_id: int) -> None:
    """Deep-hydrate one committed issue's confirmed provider identity.

    Hydration runs strictly after the identity transaction has committed and owns
    its own session, so a provider failure can never roll back a confirmed mapping.

    Args:
        issue_id: ComicPile issue ID whose confirmed identity should be hydrated.
    """
    from app.database import AsyncSessionLocal
    from app.comicvine_hydration import hydrate_issue
    from app.repositories.catalog_repository import get_confirmed_issue_external_id

    try:
        client = _get_comicvine_client()
        if client is None:
            return
        async with AsyncSessionLocal() as session:
            external_id = await get_confirmed_issue_external_id(
                session,
                issue_id=issue_id,
                provider=COMMIT_PROVIDER,
            )
            if external_id is None:
                return
            await hydrate_issue(session, client, int(external_id), refresh=True)
            await session.commit()
    except Exception:
        logger.warning(
            "series_mapping_hydration_failed issue_id=%s",
            issue_id,
            exc_info=True,
        )


def schedule_series_mapping_hydration(*, issue_ids: list[int]) -> list[int]:
    """Queue post-commit metadata hydration for newly confirmed issues.

    Hydration is a background handoff that only runs after the identity
    transaction has committed. In-process deduplication prevents fan-out for the
    same issue; the hydrator is idempotent, so a replayed commit can safely
    re-dispatch.

    Args:
        issue_ids: ComicPile issue IDs whose provider identity needs hydration.

    Returns:
        The issue IDs this call actually queued.
    """
    unique_ids = list(dict.fromkeys(issue_id for issue_id in issue_ids if issue_id > 0))
    if not unique_ids:
        return []
    if _get_comicvine_client() is None:
        logger.info(
            "series_mapping_hydration_skipped issue_count=%s reason=missing_api_key",
            len(unique_ids),
        )
        return []

    queued: list[int] = []
    for issue_id in unique_ids:
        pending = _PENDING_HYDRATIONS.get(issue_id)
        if pending is not None and not pending.done():
            continue
        task = asyncio.create_task(
            _run_series_mapping_hydration(issue_id),
            name=f"series-mapping-hydration-{issue_id}",
        )
        _PENDING_HYDRATIONS[issue_id] = task
        task.add_done_callback(
            lambda finished, queued_id=issue_id: _PENDING_HYDRATIONS.pop(queued_id, None)
        )
        queued.append(issue_id)
    return queued


async def commit_series_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    preview_token: str,
    idempotency_key: str,
    approved_row_ids: list[str],
) -> dict[str, object]:
    """Commit user-approved safe series mappings from a referenced preview.

    The commit revalidates the signed preview token, re-derives the current
    preview scope from the database and provider, and rejects the request when any
    bound material fact changed. All identity writes plus the durable idempotency
    receipt share one transaction; metadata hydration is dispatched only after that
    transaction commits.

    Args:
        db: Database session. The service owns the transaction boundary.
        user_id: User ID for authorization.
        preview_token: Signed preview token from the preview endpoint.
        idempotency_key: Client-supplied idempotency key for the material request.
        approved_row_ids: Approved row identifiers, all ``issue:<comicpile_issue_id>``.

    Returns:
        Commit response with confirmed, already-confirmed, needs-review, and
        hydration-queued issue IDs plus the confirmed series mapping summary.

    Raises:
        ConflictError: For ``preview_expired``, ``preview_stale``,
            ``confirmed_mapping_conflict``, or ``idempotency_conflict``.
        InvalidRequestError: For ``invalid_approved_row``.
    """
    from app.repositories.catalog_repository import (
        confirm_issue_mapping,
        filter_owned_issue_ids,
        find_confirmed_identity_conflict,
        get_commit_receipt,
        record_commit_receipt_response,
        reserve_commit_receipt,
    )

    payload = _verify_commit_preview_token(preview_token, user_id)
    approved_issue_ids = _parse_approved_row_ids(approved_row_ids)
    request_digest = _material_request_digest(payload, approved_issue_ids)

    provider = str(payload["provider"])
    provider_series_external_id = str(payload["provider_series_external_id"])
    origin_issue_id = int(payload["origin_issue_id"])

    # A completed commit for this key is replayed before any state revalidation:
    # a successful commit legitimately changes the facts the preview bound, so
    # revalidating first would reject a correct retry.
    existing_receipt = await get_commit_receipt(
        db, user_id=user_id, idempotency_key=idempotency_key
    )
    if existing_receipt is not None:
        return _replay_receipt(existing_receipt, request_digest)

    try:
        reserved = await reserve_commit_receipt(
            db,
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
            origin_issue_id=origin_issue_id,
        )
        if not reserved:
            # A concurrent identical attempt owns this key. Its transaction has
            # already committed, so its stored result is readable here.
            receipt = await get_commit_receipt(
                db, user_id=user_id, idempotency_key=idempotency_key
            )
            if receipt is None:
                raise _commit_conflict(COMMIT_DETAIL_IDEMPOTENCY_CONFLICT)
            return _replay_receipt(receipt, request_digest)

        scope = await resolve_series_mapping_scope(
            db,
            user_id=user_id,
            origin_issue_id=origin_issue_id,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
        )
        if not isinstance(scope.get("scope"), dict) or not _scope_matches_token(
            scope["scope"], payload
        ):
            raise _commit_conflict(COMMIT_DETAIL_PREVIEW_STALE)

        rows_by_id = _comicpile_rows_by_id(scope)
        target_rows: list[dict[str, object]] = []
        for issue_id in approved_issue_ids:
            row = rows_by_id.get(issue_id)
            if row is None or row.get("classification") != "safe_exact_match":
                raise InvalidRequestError(COMMIT_DETAIL_INVALID_APPROVED_ROW)
            if _row_provider_external_id(row) is None:
                raise InvalidRequestError(COMMIT_DETAIL_INVALID_APPROVED_ROW)
            target_rows.append(row)

        if target_rows:
            owned_issue_ids = await filter_owned_issue_ids(
                db,
                user_id=user_id,
                issue_ids=[int(row["comicpile_issue_id"]) for row in target_rows],
            )
            if len(owned_issue_ids) != len(target_rows):
                raise InvalidRequestError(COMMIT_DETAIL_INVALID_APPROVED_ROW)

        confirmed_issue_ids: list[int] = []
        already_confirmed_issue_ids: list[int] = []
        needs_review_issue_ids: list[int] = []
        hydration_queued_issue_ids: list[int] = []

        for issue_id in approved_issue_ids:
            row = rows_by_id[issue_id]
            comicpile_issue_id = int(row["comicpile_issue_id"])
            provider_issue_external_id = str(_row_provider_external_id(row))
            identity = await upsert_external_identity(
                db,
                provider=provider,
                entity_type="issue",
                external_id=provider_issue_external_id,
            )
            identity_id = identity.id
            conflict_id = await find_confirmed_identity_conflict(
                db,
                issue_id=comicpile_issue_id,
                provider=provider,
                external_identity_id=identity_id,
            )
            if conflict_id is not None:
                raise _commit_conflict(COMMIT_DETAIL_CONFIRMED_MAPPING_CONFLICT)
            transitioned = await confirm_issue_mapping(
                db,
                issue_id=comicpile_issue_id,
                external_identity_id=identity_id,
                evidence_source=USER_SERIES_CONFIRMATION_EVIDENCE,
                confidence=1.0,
            )
            if transitioned:
                confirmed_issue_ids.append(comicpile_issue_id)
                hydration_queued_issue_ids.append(comicpile_issue_id)

        approved_set = set(approved_issue_ids)
        for issue_id, row in rows_by_id.items():
            classification = row.get("classification")
            if issue_id in approved_set:
                continue
            if classification == "already_confirmed":
                already_confirmed_issue_ids.append(issue_id)
            elif classification in NEEDS_REVIEW_CLASSIFICATIONS:
                needs_review_issue_ids.append(issue_id)

        response = {
            "idempotency_key": idempotency_key,
            "confirmed_issue_ids": confirmed_issue_ids,
            "already_confirmed_issue_ids": already_confirmed_issue_ids,
            "needs_review_issue_ids": needs_review_issue_ids,
            "hydration_queued_issue_ids": hydration_queued_issue_ids,
            "series_mapping": {
                "provider": provider,
                "external_id": provider_series_external_id,
                "status": "confirmed",
                "evidence_source": USER_SERIES_CONFIRMATION_EVIDENCE,
            },
        }

        await record_commit_receipt_response(
            db,
            user_id=user_id,
            idempotency_key=idempotency_key,
            response_json=response,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    schedule_series_mapping_hydration(issue_ids=hydration_queued_issue_ids)
    return response


def _replay_receipt(receipt: object, request_digest: str) -> dict[str, object]:
    """Replay a stored commit result or reject a materially different reuse.

    Args:
        receipt: Stored ``SeriesMappingCommitReceipt`` for this idempotency key.
        request_digest: Digest of the current material commit request.

    Returns:
        The stored logical commit response.

    Raises:
        ConflictError: If the key was reused with materially different input or
            the stored receipt carries no completed result.
    """
    stored_digest = getattr(receipt, "request_digest", None)
    if stored_digest != request_digest:
        raise _commit_conflict(COMMIT_DETAIL_IDEMPOTENCY_CONFLICT)
    stored = _response_from_receipt_payload(getattr(receipt, "response_json", None))
    if stored is None:
        raise _commit_conflict(COMMIT_DETAIL_IDEMPOTENCY_CONFLICT)
    schedule_series_mapping_hydration(issue_ids=_queued_hydration_issue_ids(stored))
    return stored
