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

PREVIEW_TOKEN_TTL_SECONDS = 600
"""Lifetime of a signed series-mapping preview token (10 minutes)."""

PREVIEW_ROW_ID_PREFIX = "issue:"
"""Prefix for stable preview row identifiers such as ``issue:789``."""

PREVIEW_CLASSIFICATIONS = (
    "already_confirmed",
    "safe_exact_match",
    "needs_review_ambiguous",
    "needs_review_conflict",
    "unresolved",
    "excluded_special",
)
"""The closed preview classification contract."""

MAPPING_STATUS_PRECEDENCE = {
    "confirmed": 0,
    "candidate": 1,
    "unresolved": 2,
    "rejected": 3,
}
"""Deterministic tie-break order used when one issue yields several candidate rows."""


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


async def build_series_mapping_plan(
    db: AsyncSession,
    *,
    user_id: int,
    origin_issue_id: int,
    provider: str,
    provider_series_external_id: str,
) -> dict[str, object]:
    """Build the read-only series-mapping plan that a preview token binds.

    This performs no writes and mints no token. Commit reuses it to re-derive the current
    material facts, so the returned ``state_digest`` must stay deterministic for an unchanged
    database: rows are de-duplicated per issue and ordered before the digest is computed.

    Args:
        db: Database session.
        user_id: User ID for authorization.
        origin_issue_id: The anchor issue ID for the mapping preview.
        provider: External provider name (e.g., "comicvine").
        provider_series_external_id: Provider-specific series identifier.

    Returns:
        Plan dict with ``scope``, ``provider_series``, ``counts``, ``rows``, ``scope_key``,
        ``issue_numbers``, and ``state_digest``.
    """
    from app.repositories.catalog_repository import get_series_with_issues, get_issue_by_id

    # Get the origin issue to establish context
    origin_issue = await get_issue_by_id(db, origin_issue_id, user_id)
    if origin_issue is None:
        return _unavailable_series_mapping_plan(origin_issue_id, basis="origin_issue_not_found")

    # Try local catalog first
    series_info, issues_with_mappings = await get_series_with_issues(
        db, provider=provider, series_external_id=provider_series_external_id, user_id=user_id
    )

    # If not found locally, try ComicVine API (local-first)
    if series_info is None:
        series_info, issues_with_mappings = await _load_provider_volume_roster(
            provider_series_external_id,
            issues_with_mappings,
        )

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
        return _unavailable_series_mapping_plan(origin_issue_id, basis="series_not_found")

    assert series_info is not None

    # Classify issues and determine safe scope
    counts = _empty_preview_counts()

    classified_rows = _classify_series_mapping_rows(
        issues_with_mappings,
        provider=provider,
        origin_issue_number=_issue_number_text(origin_issue.get("issue_number")),
        counts=counts,
    )
    scope_key = _derive_scope_key(classified_rows, origin_issue_id)

    # Determine if scope is available
    scope_status = "available" if scope_key is not None else "unavailable"
    scope_basis = "insufficient_non_thread_evidence" if scope_key is None else "exact_match_found"

    # Spec: unavailable scope due to insufficient evidence returns zero counts and empty rows
    if scope_status == "unavailable":
        counts = _empty_preview_counts()
        classified_rows = []

    issue_numbers = [str(row.get("issue_number", "")) for row in classified_rows if row.get("issue_number")]
    state_digest = _plan_state_digest(
        provider=provider,
        provider_series_external_id=provider_series_external_id,
        origin_issue_id=origin_issue_id,
        scope_key=scope_key,
        scope_basis=scope_basis,
        rows=classified_rows,
    )

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
        "scope_key": scope_key,
        "issue_numbers": issue_numbers,
        "state_digest": state_digest,
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
        Preview response with scope information, counts, classified rows, and a
        user-bound signed token when the scope is available.
    """
    plan = await build_series_mapping_plan(
        db,
        user_id=user_id,
        origin_issue_id=origin_issue_id,
        provider=provider,
        provider_series_external_id=provider_series_external_id,
    )

    scope = plan["scope"] if isinstance(plan.get("scope"), dict) else plan.get("scope")
    issued_at = time.time()
    scope_available = isinstance(scope, dict) and scope.get("status") == "available"
    expires_at = issued_at + PREVIEW_TOKEN_TTL_SECONDS if scope_available else None

    preview_token = None
    if scope_available:
        preview_token = _generate_preview_token(
            user_id=user_id,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
            origin_issue_id=origin_issue_id,
            scope_key=_plan_scope_key(plan),
            issued_at=issued_at,
            expires_at=expires_at or issued_at,
            issue_numbers=_plan_issue_numbers(plan),
            classification_digest=_plan_state_digest_text(plan),
        )

    return {
        "preview_token": preview_token,
        "scope": scope,
        "provider_series": plan["provider_series"],
        "counts": plan["counts"],
        "rows": plan["rows"],
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


async def _load_provider_volume_roster(
    provider_series_external_id: str,
    issues_with_mappings: list[dict[str, object]],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Fetch a provider volume roster when the local catalog has no stored roster.

    Args:
        provider_series_external_id: Provider-specific series identifier.
        issues_with_mappings: Rows already resolved locally (normally empty at this point).

    Returns:
        Tuple of (series_info, roster rows). ``series_info`` is ``None`` when the provider is
        unavailable, which the caller reports as an unavailable scope.

    Raises:
        HTTPException: 503 ``provider_unavailable`` when live provider data is required but
            cannot be retrieved. No mutation is attempted in that case.
    """
    client = _get_comicvine_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="provider_unavailable",
        )
    try:
        volume_response = await client.fetch_volume(int(provider_series_external_id))
        volume_data = volume_response.payload.get("results")
        if not isinstance(volume_data, dict):
            return None, list(issues_with_mappings)
        series_info: dict[str, object] = {
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
        roster: list[dict[str, object]] = []

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
                # Roster rows carry no ComicPile thread. ``thread_id`` stays ``None`` so commit
                # refuses to bulk-confirm a provider roster id as if it were a local issue.
                roster.append({
                    "issue_id": pid if pid != 0 else 0,
                    "issue_number": str(issue_number),
                    "title": row.get("name"),
                    "thread_id": None,
                    "thread_title": None,
                    "current_mapping_status": "unresolved",
                    "provider": "comicvine",
                    "external_id": str(provider_issue_id),
                    "classification": "unresolved",
                })
        return series_info, roster
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


def _empty_preview_counts() -> dict[str, int]:
    """Return a zeroed classification counter for every preview classification."""
    return dict.fromkeys(PREVIEW_CLASSIFICATIONS, 0)


def _issue_number_text(raw_value: object) -> str:
    """Coerce a stored issue number into comparable text."""
    if raw_value is None:
        return ""
    return str(raw_value)


def _classify_series_mapping_rows(
    issues_with_mappings: list[dict[str, object]],
    *,
    provider: str,
    origin_issue_number: str,
    counts: dict[str, int],
) -> list[dict[str, object]]:
    """Classify one row per issue and count each classification.

    Args:
        issues_with_mappings: Raw candidate rows from the local catalog or provider roster.
        provider: Selected provider name.
        origin_issue_number: Normalized-text issue number of the anchor issue.
        counts: Counter updated in place for every classification.

    Returns:
        Deterministically ordered rows with ``row_id``, ``classification``,
        ``proposed_mapping``, and ``default_selected`` populated.
    """
    candidates = _dedupe_rows_by_issue(issues_with_mappings)

    # Pre-compute normalized counts for duplicate detection (unique exact requirement)
    # Exclude the origin issue (_is_origin flag) since it's the anchor, not part of the series issues
    normalized_counts: dict[str, int] = {}
    for info in candidates:
        if info.get("_is_origin"):
            continue
        num = _issue_number_text(info.get("issue_number"))
        if not _is_special_issue(num) and not _is_ambiguous(num):
            norm = _normalize_issue_number(num)
            if norm:
                normalized_counts[norm] = normalized_counts.get(norm, 0) + 1

    classified_rows: list[dict[str, object]] = []
    for issue_info in candidates:
        issue_number = _issue_number_text(issue_info.get("issue_number"))

        # Check if it's a special issue (annual, special, etc.)
        if _is_special_issue(issue_number):
            classification = "excluded_special"
        elif _is_conflicting_mapping(issue_info, provider):
            classification = "needs_review_conflict"
        elif _is_ambiguous(issue_number):
            classification = "needs_review_ambiguous"
        elif issue_info.get("current_mapping_status") == "confirmed":
            classification = "already_confirmed"
        elif _is_exact_match(issue_number, origin_issue_number):
            norm = _normalize_issue_number(issue_number)
            if norm and normalized_counts.get(norm, 0) == 1:
                classification = "safe_exact_match"
            else:
                classification = "needs_review_ambiguous"
        else:
            classification = "unresolved"

        counts[classification] += 1
        issue_info["row_id"] = _preview_row_id(issue_info.get("issue_id"))
        issue_info["classification"] = classification
        issue_info["proposed_mapping"] = classification in ("safe_exact_match", "already_confirmed")
        issue_info["default_selected"] = classification == "safe_exact_match"

        classified_rows.append(issue_info)

    return classified_rows


def _dedupe_rows_by_issue(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Collapse candidate rows to one deterministic row per issue.

    A single issue can appear more than once when several provider identities are mapped to it,
    or when the anchor issue is also joined from the local catalog. Collapsing here keeps
    counts honest and keeps the plan digest stable across identical queries.

    Args:
        rows: Raw candidate rows.

    Returns:
        One row per issue ID, ordered by issue ID.
    """
    best: dict[int, dict[str, object]] = {}
    passthrough: list[dict[str, object]] = []
    for row in rows:
        issue_id = row.get("issue_id")
        if not isinstance(issue_id, int):
            passthrough.append(row)
            continue
        current = best.get(issue_id)
        if current is None or _row_precedence_key(row) < _row_precedence_key(current):
            best[issue_id] = row

    ordered = [best[issue_id] for issue_id in sorted(best)]
    ordered.extend(sorted(passthrough, key=_row_precedence_key))
    return ordered


def _row_precedence_key(row: dict[str, object]) -> tuple[int, int, str, str]:
    """Return the deterministic tie-break key used when collapsing rows for one issue."""
    return (
        0 if row.get("thread_id") is not None else 1,
        MAPPING_STATUS_PRECEDENCE.get(_issue_number_text(row.get("current_mapping_status")), 4),
        str(row.get("external_id") or ""),
        str(row.get("issue_number") or ""),
    )


def _derive_scope_key(classified_rows: list[dict[str, object]], origin_issue_id: int) -> str | None:
    """Return the opaque scope key for an available scope, otherwise ``None``."""
    for row in classified_rows:
        if row.get("classification") == "safe_exact_match":
            return f"exact:{origin_issue_id}:{row.get('issue_number')}"
    return None


def _preview_row_id(issue_id: object) -> str:
    """Return the stable preview row identifier for one issue."""
    return f"{PREVIEW_ROW_ID_PREFIX}{issue_id}"


def _plan_scope_key(plan: dict[str, object]) -> str:
    """Return the plan's scope key, or an empty string when the scope is unavailable."""
    scope_key = plan.get("scope_key")
    return scope_key if isinstance(scope_key, str) else ""


def _plan_issue_numbers(plan: dict[str, object]) -> list[str]:
    """Return the plan's bound issue numbers."""
    issue_numbers = plan.get("issue_numbers")
    if not isinstance(issue_numbers, list):
        return []
    return [str(value) for value in issue_numbers]


def _plan_state_digest_text(plan: dict[str, object]) -> str:
    """Return the plan's state digest, which the preview token binds."""
    state_digest = plan.get("state_digest")
    return state_digest if isinstance(state_digest, str) else ""


def _unavailable_series_mapping_plan(origin_issue_id: int, *, basis: str) -> dict[str, object]:
    """Return a normal, non-error unavailable-scope plan."""
    return {
        "scope": {
            "status": "unavailable",
            "scope_key": None,
            "origin_issue_id": origin_issue_id,
            "series_label": None,
            "basis": basis,
        },
        "provider_series": None,
        "counts": _empty_preview_counts(),
        "rows": [],
        "scope_key": None,
        "issue_numbers": [],
        "state_digest": _plan_state_digest(
            provider="",
            provider_series_external_id="",
            origin_issue_id=origin_issue_id,
            scope_key=None,
            scope_basis=basis,
            rows=[],
        ),
    }


def _plan_state_digest(
    *,
    provider: str,
    provider_series_external_id: str,
    origin_issue_id: int,
    scope_key: str | None,
    scope_basis: str,
    rows: list[dict[str, object]],
) -> str:
    """Digest every material fact a preview token binds.

    Commit recomputes this digest and refuses to write when it changes, so any change to the
    selected provider series, scope evidence, issue numbers, mapping state, or selected
    provider identities invalidates the preview.

    Args:
        provider: Selected provider name.
        provider_series_external_id: Selected provider series identifier.
        origin_issue_id: Anchor issue ID.
        scope_key: Derived scope key, or ``None`` when the scope is unavailable.
        scope_basis: Why the scope is available or unavailable.
        rows: Deterministically ordered classified rows.

    Returns:
        Hex SHA-256 digest of the bound material facts.
    """
    parts = [
        f"provider={provider}",
        f"series={provider_series_external_id}",
        f"origin={origin_issue_id}",
        f"scope={scope_key or ''}",
        f"basis={scope_basis}",
    ]
    for row in rows:
        parts.append(
            "|".join(
                (
                    _preview_row_id(row.get("issue_id")),
                    str(row.get("issue_number") or ""),
                    str(row.get("classification") or ""),
                    str(row.get("current_mapping_status") or ""),
                    str(row.get("provider") or ""),
                    str(row.get("external_id") or ""),
                    str(row.get("thread_id") or ""),
                )
            )
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


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


def verify_preview_token(
    token: str,
    expected_user_id: int,
    *,
    expiry_status_code: int = status.HTTP_401_UNAUTHORIZED,
    expiry_detail: str = "preview_token_expired",
) -> dict[str, object]:
    """Verify an HMAC-signed preview token and check expiry and ownership.

    Args:
        token: JSON token string produced by ``_generate_preview_token``.
        expected_user_id: User id that must match the token payload.
        expiry_status_code: HTTP status reported when the token is past its TTL. Commit maps
            expiry onto ``409 preview_expired`` while the preview surface keeps ``401``.
        expiry_detail: Response detail reported when the token is past its TTL.

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
            status_code=expiry_status_code,
            detail=expiry_detail,
        )

    payload_user = payload.get("user_id")
    if payload_user != expected_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_preview_token",
        )

    return payload
