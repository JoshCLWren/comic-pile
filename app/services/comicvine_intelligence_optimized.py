"""Optimized ComicVine intelligence for ComicPile's issue experience."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from html.parser import HTMLParser
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.schemas.comicvine import (
    ComicVineComicPileMatch,
    ComicVineCreator,
    ComicVineIssueIntelligence,
    ComicVineRelatedIssue,
    ComicVineStoryArc,
)
from app.services.comicvine_fallback import (
    metadata_needs_hydration,
    schedule_issue_metadata_refresh,
)
from app.services.comicvine_series_resolution import schedule_series_issue_resolution

COMICVINE_PROVIDER = "comicvine"
MAX_RELATED_ISSUES_PER_ARC = 60
MAX_ARCS_PER_INTELLIGENCE_READ = 10

logger = logging.getLogger(__name__)


class _PlainTextParser(HTMLParser):
    """Convert provider HTML fragments to readable plain text."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


# Cache for HTML parsers to avoid repeated instantiation
_HTML_PARSER_CACHE: dict[int, _PlainTextParser] = {}


def _plain_text_cached(value: object) -> str | None:
    """Optimized plain text parsing with caching."""
    if not isinstance(value, str) or not value.strip():
        return None
    
    # Fast path: simple text without HTML tags
    if '<' not in value and '>' not in value:
        return " ".join(value.split())
    
    # Use cached HTML parser for complex content
    parser_id = hash(value)  # Use hash for different content
    if parser_id not in _HTML_PARSER_CACHE:
        _HTML_PARSER_CACHE[parser_id] = _PlainTextParser()
    
    parser = _HTML_PARSER_CACHE[parser_id]
    parser.reset()  # Clear previous state
    parser.feed(value)
    normalized = " ".join(parser.parts)
    return normalized or None


def _string(value: object) -> str | None:
    return str(value) if isinstance(value, (str, int)) and str(value).strip() else None


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _reference_list(metadata: dict[str, object], *keys: str) -> list[dict[str, object]]:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            return [cast(dict[str, object], item) for item in value if isinstance(item, dict)]
    return []


def _series(metadata: dict[str, object]) -> tuple[int | None, str | None]:
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        return _integer(volume.get("id")), _string(volume.get("name"))
    return _integer(metadata.get("volume_id")), _string(metadata.get("volume_name"))


def _image(metadata: dict[str, object]) -> str | None:
    direct = _string(metadata.get("image_url")) or _string(metadata.get("primary_image"))
    if direct:
        return direct
    image = metadata.get("image")
    if isinstance(image, dict):
        for key in ("original_url", "super_url", "medium_url", "small_url"):
            candidate = _string(image.get(key))
            if candidate:
                return candidate
    return None


def _creators_optimized(metadata: dict[str, object]) -> list[ComicVineCreator]:
    """Optimized creator processing with set-based deduplication that preserves order."""
    by_id: dict[int, tuple[str, set[str], list[str]]] = {}  # Added list to preserve order
    order: list[int] = []
    no_id: list[ComicVineCreator] = []

    for credit in _reference_list(metadata, "person_credits", "creator_credits"):
        name = _string(credit.get("name"))
        if not name:
            continue
        creator_id = _integer(credit.get("id"))
        role_value = _string(credit.get("role")) or ""
        # Preserve order of roles as they appear in the input
        roles_list = [role.strip() for role in role_value.split(",") if role.strip()]
        roles_set = set(roles_list)

        if creator_id is None:
            no_id.append(ComicVineCreator(name=name, roles=roles_list))
            continue

        if creator_id not in by_id:
            by_id[creator_id] = (name, roles_set, roles_list)
            order.append(creator_id)
        else:
            _, existing_set, existing_list = by_id[creator_id]
            # Add new roles while preserving order
            for role in roles_list:
                if role not in existing_set:
                    existing_set.add(role)
                    existing_list.append(role)

    creators = [
        ComicVineCreator(
            creator_id=cid,
            name=by_id[cid][0],
            roles=by_id[cid][2],  # Use the preserved order list
        )
        for cid in order
    ]
    creators.extend(no_id)
    return creators
def _arc_references(metadata: dict[str, object]) -> list[dict[str, object]]:
    return _reference_list(metadata, "story_arc_credits", "story_arcs")


async def _confirmed_identity(db: AsyncSession, issue_id: int) -> ExternalIdentity | None:
    result = await db.execute(
        select(ExternalIdentity)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "issue",
        )
        .order_by(IssueExternalIdentityMapping.confidence.desc().nullslast(), ExternalIdentity.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _related_external_rows_optimized(
    db: AsyncSession,
    arc_ids: list[int],
    current_external_id: str,
) -> tuple[list[dict[str, object]], bool]:
    """Optimized version using JSONB array operations for better performance."""
    capped_arc_ids: list[int] = []
    for arc_id in arc_ids:
        if arc_id not in capped_arc_ids:
            capped_arc_ids.append(arc_id)
        if len(capped_arc_ids) >= MAX_ARCS_PER_INTELLIGENCE_READ:
            break
    
    if not capped_arc_ids:
        return [], False
    
    # Build JSONB arrays once instead of multiple individual containment checks
    arc_credits_json = json.dumps([{"id": arc_id} for arc_id in capped_arc_ids])
    story_arcs_json = json.dumps([{"id": arc_id} for arc_id in capped_arc_ids])
    
    result = await db.execute(
        text(
            """
            SELECT DISTINCT ON (ei.external_id)
                ei.id AS identity_id,
                ei.external_id,
                ei.external_url,
                ei.metadata_json
            FROM external_identities ei
            WHERE ei.provider = :provider
              AND ei.entity_type = 'issue'
              AND ei.external_id <> :current_external_id
              AND (
                  ei.metadata_json::jsonb -> 'story_arc_credits' @> CAST(:arc_credits_json AS jsonb)
                  OR ei.metadata_json::jsonb -> 'story_arcs' @> CAST(:story_arcs_json AS jsonb)
              )
            ORDER BY ei.external_id, ei.id
            LIMIT :related_row_limit
            """
        ),
        {
            "provider": COMICVINE_PROVIDER,
            "current_external_id": current_external_id,
            "arc_credits_json": arc_credits_json,
            "story_arcs_json": story_arcs_json,
            "related_row_limit": MAX_RELATED_ISSUES_PER_ARC * len(capped_arc_ids),
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    row_limit = MAX_RELATED_ISSUES_PER_ARC * len(capped_arc_ids)
    return rows, len(rows) >= row_limit


async def _arc_related_total(
    db: AsyncSession,
    arc_id: int,
    current_external_id: str,
) -> int:
    """Count every related member of one story arc without hydrating rows.

    The bounded rows query can no longer report how many members an arc truly
    has once its window truncates, and the UI exposes that total as the
    ``(X of Y shown)`` indicator. This scalar count uses the same containment
    predicates as the rows query so the displayed total stays exact while the
    request path still fetches at most ``MAX_RELATED_ISSUES_PER_ARC`` rows per
    arc.

    Args:
        db: Async database session.
        arc_id: ComicVine story-arc identifier.
        current_external_id: The current issue's external ID, excluded from
            the total exactly as it is from the related rows.

    Returns:
        The number of distinct related ComicVine issue identities in the arc.
    """
    result = await db.execute(
        text(
            """
            SELECT COUNT(DISTINCT ei.external_id)
            FROM external_identities ei
            WHERE ei.provider = :provider
              AND ei.entity_type = 'issue'
              AND ei.external_id <> :current_external_id
              AND (
                    ei.metadata_json->'story_arc_credits' @> CAST(:arc_credits AS jsonb)
                 OR ei.metadata_json->'story_arcs' @> CAST(:arc_normalized AS jsonb)
              )
            """
        ),
        {
            "provider": COMICVINE_PROVIDER,
            "current_external_id": current_external_id,
            "arc_credits": json.dumps({"story_arc_credits": [{"id": arc_id}]}),
            "arc_normalized": json.dumps({"story_arcs": [{"id": arc_id}]}),
        },
    )
    total = result.scalar()
    return int(total) if total is not None else 0


async def _comicpile_matches(
    db: AsyncSession,
    identity_ids: list[int],
    user_id: int,
) -> dict[int, list[ComicVineComicPileMatch]]:
    if not identity_ids:
        return {}
    result = await db.execute(
        text(
            """
            SELECT iem.external_identity_id, i.id AS issue_id, i.thread_id,
                   t.title AS thread_title, i.issue_number, i.status
            FROM issue_external_identity_mappings iem
            JOIN issues i ON i.id = iem.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE iem.external_identity_id = ANY(:identity_ids)
              AND iem.status = 'confirmed'
              AND t.user_id = :user_id
            ORDER BY iem.external_identity_id, t.title, i.position, i.id
            """
        ),
        {"identity_ids": identity_ids, "user_id": user_id},
    )
    matches: dict[int, list[ComicVineComicPileMatch]] = {}
    for row in result.mappings():
        identity_id = int(row["external_identity_id"])
        matches.setdefault(identity_id, []).append(
            ComicVineComicPileMatch(
                issue_id=int(row["issue_id"]),
                thread_id=int(row["thread_id"]),
                thread_title=str(row["thread_title"]),
                issue_number=str(row["issue_number"]),
                status=str(row["status"]),
            )
        )
    return matches


async def _build_story_arcs_optimized(
    arc_refs: list[dict[str, object]],
    related_by_arc: dict[int, list[ComicVineRelatedIssue]],
    arc_ids: list[int],
    window_saturated: bool,
    identity_external_id: str,
    db: AsyncSession,
) -> list[ComicVineStoryArc]:
    """Optimized story arc building with improved sorting performance."""
    story_arcs: list[ComicVineStoryArc] = []
    
    # Pre-compute arc information to avoid repeated lookups
    arc_info = []
    for arc in arc_refs:
        arc_id = _integer(arc.get("id"))
        name = _string(arc.get("name"))
        if arc_id is not None and name is not None:
            arc_info.append((arc_id, name, arc))
    
    for arc_id, name, arc in arc_info:
        all_related = related_by_arc.get(arc_id, [])
        
        if all_related:
            # Optimized sorting: separate dated and undated items
            dated_items = []
            undated_items = []
            
            for item in all_related:
                if item.cover_date:
                    dated_items.append(item)
                else:
                    undated_items.append(item)
            
            # Sort dated items by date, series, issue number
            dated_items.sort(key=lambda x: (
                x.cover_date or "",
                x.series_name or "",
                x.issue_number or ""
            ))
            
            # Sort undated items by series, issue number  
            undated_items.sort(key=lambda x: (
                x.series_name or "",
                x.issue_number or ""
            ))
            
            all_related = dated_items + undated_items
        
        related_issues = all_related[:MAX_RELATED_ISSUES_PER_ARC]
        
        if window_saturated:
            total_count = await _arc_related_total(db, arc_id, identity_external_id)
        else:
            total_count = len(all_related)
            
        story_arcs.append(
            ComicVineStoryArc(
                comicvine_arc_id=arc_id,
                name=name,
                comicvine_url=_string(arc.get("site_detail_url")),
                related_issues=related_issues,
                total_related_count=total_count if total_count > len(related_issues) else None,
            )
        )
    
    return story_arcs


async def get_issue_intelligence_optimized(
    db: AsyncSession,
    issue_id: int,
    user_id: int,
) -> ComicVineIssueIntelligence | None:
    """Build curated metadata and explicit story-arc relationships for one issue.

    This optimized version reduces application processing time through:
    - Optimized JSONB queries using array operations
    - Improved data structures (defaultdict, sets)
    - Reduced nested operations and loops
    - Optimized string processing with caching
    - Improved sorting algorithms

    Args:
        db: Async database session.
        issue_id: ComicPile issue identifier.
        user_id: Owner whose ComicPile representations may be returned.

    Returns:
        Curated ComicVine intelligence, or ``None`` when no confirmed mapping exists.
    """
    identity = await _confirmed_identity(db, issue_id)
    if identity is None:
        await schedule_series_issue_resolution(db, issue_id, user_id)
        return None

    if metadata_needs_hydration(identity):
        schedule_issue_metadata_refresh(identity.id)

    metadata = identity.metadata_json
    arc_refs = _arc_references(metadata)
    arc_ids = [arc_id for arc in arc_refs if (arc_id := _integer(arc.get("id"))) is not None]
    
    # Batch process related rows with optimized query
    related_rows, window_saturated = await _related_external_rows_optimized(
        db, arc_ids, identity.external_id
    )
    
    # Extract identity IDs once and get matches
    identity_ids = [int(row["identity_id"]) for row in related_rows]
    matches = await _comicpile_matches(db, identity_ids, user_id)

    # Pre-build arc_id to arc mapping for faster lookups
    arc_id_to_arc = {arc_id: arc for arc in arc_refs if (arc_id := _integer(arc.get("id"))) is not None}
    
    # Use defaultdict for faster list building
    related_by_arc: defaultdict[int, list[ComicVineRelatedIssue]] = defaultdict(list)
    
    # Process related rows in a single optimized pass
    for row in related_rows:
        related_metadata = row["metadata_json"]
        if not isinstance(related_metadata, dict):
            continue
            
        series_id, series_name = _series(related_metadata)
        related = ComicVineRelatedIssue(
            comicvine_issue_id=str(row["external_id"]),
            series_name=series_name,
            issue_number=_string(related_metadata.get("issue_number")),
            name=_string(related_metadata.get("name")),
            cover_date=_string(related_metadata.get("cover_date")),
            comicvine_url=_string(row["external_url"]) or _string(related_metadata.get("site_detail_url")),
            comicpile_matches=matches.get(int(row["identity_id"]), []),
        )
        
        # Get arc IDs once and add to relevant arcs
        row_arc_ids = {
            arc_id
            for arc in _arc_references(related_metadata)
            if (arc_id := _integer(arc.get("id"))) is not None
        }
        for arc_id in row_arc_ids:
            if arc_id in arc_id_to_arc:  # Only include arcs we care about
                related_by_arc[arc_id].append(related)

    # Build story arcs with optimized processing
    story_arcs = await _build_story_arcs_optimized(
        arc_refs, related_by_arc, arc_ids, window_saturated, identity.external_id, db
    )

    series_id, series_name = _series(metadata)
    return ComicVineIssueIntelligence(
        comicvine_issue_id=identity.external_id,
        comicvine_url=identity.external_url or _string(metadata.get("site_detail_url")),
        series_name=series_name,
        series_id=series_id,
        issue_number=_string(metadata.get("issue_number")),
        name=_string(metadata.get("name")),
        description=_plain_text_cached(metadata.get("description")),
        image_url=_image(metadata),
        cover_date=_string(metadata.get("cover_date")),
        store_date=_string(metadata.get("store_date")),
        creators=_creators_optimized(metadata),
        story_arcs=story_arcs,
    )