"""Read-only ComicVine intelligence for ComicPile's issue experience."""

from __future__ import annotations

from html.parser import HTMLParser
import json
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

COMICVINE_PROVIDER = "comicvine"
MAX_RELATED_ISSUES_PER_ARC = 60


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
    creators: list[ComicVineCreator] = []
    for credit in _reference_list(metadata, "person_credits", "creator_credits"):
        name = _string(credit.get("name"))
        if not name:
            continue
        role_value = _string(credit.get("role")) or ""
        roles = [role.strip() for role in role_value.split(",") if role.strip()]
        creators.append(ComicVineCreator(name=name, roles=roles))
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
) -> list[dict[str, object]]:
    if not arc_ids:
        return []
    arc_predicates: list[str] = []
    parameters: dict[str, object] = {
        "provider": COMICVINE_PROVIDER,
        "current_external_id": current_external_id,
    }
    for index, arc_id in enumerate(arc_ids):
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
            """
        ),
        parameters,
    )
    return [dict(row) for row in result.mappings().all()]


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

    Args:
        db: Async database session.
        issue_id: ComicPile issue identifier.
        user_id: Owner whose ComicPile representations may be returned.

    Returns:
        Curated ComicVine intelligence, or ``None`` when no confirmed mapping exists.
    """
    identity = await _confirmed_identity(db, issue_id)
    if identity is None:
        return None

    metadata = identity.metadata_json
    arc_refs = _arc_references(metadata)
    arc_ids = [arc_id for arc in arc_refs if (arc_id := _integer(arc.get("id"))) is not None]
    related_rows = await _related_external_rows(db, arc_ids, identity.external_id)
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
        related_issues = sorted(
            related_by_arc.get(arc_id, []),
            key=lambda item: (item.cover_date or "", item.series_name or "", item.issue_number or ""),
        )[:MAX_RELATED_ISSUES_PER_ARC]
        story_arcs.append(
            ComicVineStoryArc(
                comicvine_arc_id=arc_id,
                name=name,
                comicvine_url=_string(arc.get("site_detail_url")),
                related_issues=related_issues,
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
    )
