"""Read-only ComicVine intelligence for ComicPile's issue experience."""

from __future__ import annotations

import logging
from html.parser import HTMLParser
import json
from typing import cast
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories import comicvine_metadata_refresh_repository as refresh_repository
from app.repositories import issue_repository
from app.schemas.comicvine import (
    ComicVineComicPileMatch,
    ComicVineCreator,
    ComicVineIssueIntelligence,
    ComicVineRelatedIssue,
    ComicVineStoryArc,
)
from app.schemas.issue import IssueCreatorsEntry, ThreadIssueCreatorsResponse

from app.services.comicvine_fallback import metadata_needs_hydration
from app.services.comicvine_metadata_repair import (
    MetadataRepairState,
    describe_metadata_status,
    refresh_retry_after_seconds,
    request_issue_metadata_repair,
    schedule_metadata_repair_drain,
)
from app.services.comicvine_series_resolution import schedule_series_issue_resolution
from app.services.ownership import get_owned_thread_or_404

COMICVINE_PROVIDER = "comicvine"
MAX_RELATED_ISSUES_PER_ARC = 60
# A single issue rarely belongs to many story arcs, but provider metadata is
# unbounded. Capping the arcs considered keeps the containment query (one OR
# branch per arc) and the Python-side grouping bounded on the request path.
MAX_ARCS_PER_INTELLIGENCE_READ = 10
# Credit arrays are provider-supplied and theoretically unbounded; the bulk
# thread-creators read caps what one issue row can carry so the display
# response stays small even when provider metadata is bloated.
MAX_BULK_CREDITS_PER_ISSUE = 25

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


def _plain_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _PlainTextParser()
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


def _creators(metadata: dict[str, object]) -> list[ComicVineCreator]:
    """Build creator list grouped by stable provider ID.

    Credits sharing the same ``id`` are merged into a single creator
    identity with a combined, deduplicated role list.  Duplicate
    provider rows (same person, same role) do not produce extra entries.
    Credits without a usable stable ``id`` are returned as name-only
    rows with ``creator_id=None`` so they are not mistaken for
    analytics-addressable identities.
    """
    by_id: dict[int, tuple[str, list[str]]] = {}
    order: list[int] = []
    no_id: list[ComicVineCreator] = []

    for credit in _reference_list(metadata, "person_credits", "creator_credits"):
        name = _string(credit.get("name"))
        if not name:
            continue
        creator_id = _integer(credit.get("id"))
        role_value = _string(credit.get("role")) or ""
        roles = [role.strip() for role in role_value.split(",") if role.strip()]

        if creator_id is None:
            no_id.append(ComicVineCreator(name=name, roles=roles))
            continue

        existing = by_id.get(creator_id)
        if existing is None:
            by_id[creator_id] = (name, list(roles))
            order.append(creator_id)
        else:
            _, existing_roles = existing
            for role in roles:
                if role not in existing_roles:
                    existing_roles.append(role)

    creators: list[ComicVineCreator] = [
        ComicVineCreator(
            creator_id=cid,
            name=by_id[cid][0],
            roles=by_id[cid][1],
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


async def _related_external_rows(
    db: AsyncSession,
    arc_ids: list[int],
    current_external_id: str,
) -> tuple[list[dict[str, object]], bool]:
    """Fetch candidate arc members for the related-issues section.

    The read only displays ``MAX_RELATED_ISSUES_PER_ARC`` members per arc, so
    the query is bounded to that window (times the capped arc count) instead
    of hydrating every row that shares an arc. Ordering stays deterministic
    (``external_id``, then ``id``) and per-arc truncation still happens in
    Python where cover-date ordering is applied.

    Returns:
        The candidate rows plus whether the bounded window was saturated, so
        callers can resolve exact per-arc totals the truncated fetch can no
        longer count locally.
    """
    capped_arc_ids: list[int] = []
    for arc_id in arc_ids:
        if arc_id not in capped_arc_ids:
            capped_arc_ids.append(arc_id)
        if len(capped_arc_ids) >= MAX_ARCS_PER_INTELLIGENCE_READ:
            break
    if not capped_arc_ids:
        return [], False
    arc_predicates: list[str] = []
    parameters: dict[str, object] = {
        "provider": COMICVINE_PROVIDER,
        "current_external_id": current_external_id,
        "related_row_limit": MAX_RELATED_ISSUES_PER_ARC * len(capped_arc_ids),
    }
    for index, arc_id in enumerate(capped_arc_ids):
        credits_parameter = f"arc_credits_{index}"
        normalized_parameter = f"story_arcs_{index}"
        arc_predicates.extend(
            [
                f"ei.metadata_json::jsonb @> CAST(:{credits_parameter} AS jsonb)",
                f"ei.metadata_json::jsonb @> CAST(:{normalized_parameter} AS jsonb)",
            ]
        )
        parameters[credits_parameter] = json.dumps({"story_arc_credits": [{"id": arc_id}]})
        parameters[normalized_parameter] = json.dumps({"story_arcs": [{"id": arc_id}]})
    containment_sql = " OR ".join(arc_predicates)
    result = await db.execute(
        text(
            f"""
            SELECT DISTINCT ON (ei.external_id)
                ei.id AS identity_id,
                ei.external_id,
                ei.external_url,
                ei.metadata_json
            FROM external_identities ei
            WHERE ei.provider = :provider
              AND ei.entity_type = 'issue'
              AND ei.external_id <> :current_external_id
              AND ({containment_sql})
            ORDER BY ei.external_id, ei.id
            LIMIT :related_row_limit
            """
        ),
        parameters,
    )
    rows = [dict(row) for row in result.mappings().all()]
    row_limit = int(parameters["related_row_limit"])
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
                    ei.metadata_json::jsonb @> CAST(:arc_credits AS jsonb)
                 OR ei.metadata_json::jsonb @> CAST(:arc_normalized AS jsonb)
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


async def get_issue_intelligence(
    db: AsyncSession,
    issue_id: int,
    user_id: int,
) -> ComicVineIssueIntelligence | None:
    """Build curated metadata and explicit story-arc relationships for one issue.

    The response is served entirely from trusted stored data: missing or stale
    provider metadata schedules a non-blocking background refresh and the
    current database-backed result is returned immediately. Interactive reads
    never wait on live ComicVine network I/O (issue #3248). Related story-arc
    members are likewise bounded to the per-arc display window.

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

    repair_request: MetadataRepairState | None = None
    if metadata_needs_hydration(identity):
        repair_request = await request_issue_metadata_repair(db, identity.id)
        schedule_metadata_repair_drain()
        schedule_issue_metadata_refresh(identity.id)
    else:
        stored_request = await refresh_repository.get_request(db, identity.id)
        if stored_request is not None:
            repair_request = MetadataRepairState(
                state=stored_request.state,
                attempts=stored_request.attempts,
                next_attempt_at=stored_request.next_attempt_at,
                last_error=stored_request.last_error,
                refresh_requested=False,
            )

    metadata = identity.metadata_json
    arc_refs = _arc_references(metadata)
    arc_ids = [arc_id for arc in arc_refs if (arc_id := _integer(arc.get("id"))) is not None]
    related_rows, window_saturated = await _related_external_rows(
        db, arc_ids, identity.external_id
    )
    matches = await _comicpile_matches(
        db,
        [int(row["identity_id"]) for row in related_rows],
        user_id,
    )

    related_by_arc: dict[int, list[ComicVineRelatedIssue]] = {arc_id: [] for arc_id in arc_ids}
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
            comicvine_url=_string(row["external_url"])
            or _string(related_metadata.get("site_detail_url")),
            comicpile_matches=matches.get(int(row["identity_id"]), []),
        )
        row_arc_ids = {
            arc_id
            for arc in _arc_references(related_metadata)
            if (arc_id := _integer(arc.get("id"))) is not None
        }
        for arc_id in row_arc_ids.intersection(related_by_arc):
            related_by_arc[arc_id].append(related)

    story_arcs: list[ComicVineStoryArc] = []
    for arc in arc_refs:
        arc_id = _integer(arc.get("id"))
        name = _string(arc.get("name"))
        if arc_id is None or name is None:
            continue
        all_related = sorted(
            related_by_arc.get(arc_id, []),
            key=lambda item: (item.cover_date or "", item.series_name or "", item.issue_number or ""),
        )
        related_issues = all_related[:MAX_RELATED_ISSUES_PER_ARC]
        if window_saturated:
            total_count = await _arc_related_total(db, arc_id, identity.external_id)
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

    series_id, series_name = _series(metadata)
    return ComicVineIssueIntelligence(
        comicvine_issue_id=identity.external_id,
        comicvine_url=identity.external_url or _string(metadata.get("site_detail_url")),
        series_name=series_name,
        series_id=series_id,
        issue_number=_string(metadata.get("issue_number")),
        name=_string(metadata.get("name")),
        description=_plain_text(metadata.get("description")),
        image_url=_image(metadata),
        cover_date=_string(metadata.get("cover_date")),
        store_date=_string(metadata.get("store_date")),
        creators=_creators(metadata),
        story_arcs=story_arcs,
        metadata_status=describe_metadata_status(metadata, repair_request),
        refresh_retry_after_seconds=refresh_retry_after_seconds(
            repair_request, now=datetime.now(UTC)
        ),
    )


async def get_thread_issue_creators(
    db: AsyncSession,
    thread_id: int,
    user_id: int,
) -> ThreadIssueCreatorsResponse:
    """Read stored ComicVine creator credits for every mapped issue in one thread.

    This is the bulk display read behind the thread issue list's creator
    column. Unlike ``get_issue_intelligence`` it is a pure stored-data read:
    it never schedules background resolution or metadata refresh jobs and
    never builds story-arc intelligence, so expanding a full issue page stays
    one request instead of one heavy provider read per row. Issue-specific
    credits are returned regardless of whether the series carries manual
    creator credits, preserving per-issue provider credits as the preferred
    source with the series credits only a client-side fallback.

    Args:
        db: Async database session.
        thread_id: ComicPile thread whose issue credits are read.
        user_id: Owner who must own the thread.

    Returns:
        Per-issue creator credits for issues holding a confirmed ComicVine
        mapping with stored credit arrays; unmapped or credit-less issues are
        omitted.

    Raises:
        HTTPException: 404 when the thread does not exist or is not owned by
            ``user_id``.
    """
    await get_owned_thread_or_404(db, user_id, thread_id)
    rows = await issue_repository.confirmed_comicvine_credits_for_thread(db, thread_id)
    entries: list[IssueCreatorsEntry] = []
    for issue_id, person_credits, creator_credits in rows:
        metadata: dict[str, object] = {}
        if person_credits is not None:
            metadata["person_credits"] = person_credits
        if creator_credits is not None:
            metadata["creator_credits"] = creator_credits
        creators = _creators(metadata)[:MAX_BULK_CREDITS_PER_ISSUE]
        if not creators:
            continue
        entries.append(IssueCreatorsEntry(issue_id=issue_id, creators=creators))
    return ThreadIssueCreatorsResponse(thread_id=thread_id, issues=entries)


def schedule_issue_metadata_refresh(identity_id: int) -> bool:
    """Compatibility shim retained for legacy callers and monkeypatch-based tests.

    Durable repair requests now use ``request_issue_metadata_repair`` plus
    ``schedule_metadata_repair_drain``. This shim preserves the historical
    callable surface without launching a detached provider task.
    """
    return True
