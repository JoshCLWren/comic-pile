"""ComicVine hydration services built on provider-independent external identities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import MetadataMerger, upsert_external_identity
from app.models.external_identity import ExternalIdentity
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError

COMICVINE_PROVIDER = "comicvine"

DEEP_ISSUE_RAW_FIELDS = frozenset(
    {
        "id",
        "name",
        "issue_number",
        "cover_date",
        "store_date",
        "image",
        "volume",
        "person_credits",
        "character_credits",
        "team_credits",
        "story_arc_credits",
        "date_last_updated",
    }
)
"""Raw provider fields supplied only by a singular, deep ComicVine issue response.

Volume-roster rows omit these relationship and date fields, so a roster write must never
be allowed to replace metadata that a singular issue response produced (#4147).
"""

DEEP_METADATA_REFRESHED_AT_KEY = "deep_metadata_refreshed_at"
"""Metadata key recording when a full singular issue payload was persisted.

ComicVine's ``date_last_updated`` (stored as ``provider_updated_at``) records when the
provider last edited the issue, not when this application last fetched its deep payload.
Freshness checks must use this application-side timestamp so an issue ComicVine has not
edited in over 30 days is not re-fetched on every read. Roster writes merge into stored
metadata and therefore never advance this marker. A deep payload the provider served from
its local cache is not proof of a recent fetch either, so it never advances it either;
only a live singular response does (#4147).
"""


def _result_object(payload: dict[str, object]) -> dict[str, object]:
    result = payload.get("results")
    if not isinstance(result, dict):
        raise ComicVineError("ComicVine resource response did not contain an object result")
    return cast(dict[str, object], result)


def _external_url(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _provider_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _compact_reference(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    allowed = ("id", "name", "api_detail_url", "site_detail_url")
    return {key: value[key] for key in allowed if key in value}


def _compact_references(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for item in value:
        compact = _compact_reference(item)
        if compact is not None:
            if isinstance(item, dict) and "role" in item:
                compact["role"] = item["role"]
            result.append(compact)
    return result


def is_deep_issue_result(result: dict[str, object]) -> bool:
    """Return whether a raw issue result carries the full singular-issue field set.

    Args:
        result: Raw ComicVine issue result (singular response or roster row).

    Returns:
        True when the result contains every deep-issue field.
    """
    return DEEP_ISSUE_RAW_FIELDS.issubset(result)


def _has_metadata_value(value: object) -> bool:
    """Return whether a normalized metadata value carries usable provider data."""
    if value is None:
        return False
    if isinstance(value, str | list | dict) and not value:
        return False
    return True


def _merge_raw_issue_payload(existing: object, incoming: object) -> object:
    """Merge raw issue evidence so a sparse row cannot shadow a deep payload."""
    if not isinstance(existing, dict):
        return incoming
    if not isinstance(incoming, dict):
        return existing
    if is_deep_issue_result(incoming):
        # A fresh singular response is richer evidence and replaces the raw row.
        return incoming
    if is_deep_issue_result(existing):
        # A roster row is a strict subset; keep the deep payload the UI relies on,
        # but merge any supplied basic fields (name, cover_date, ...) so the
        # stored raw payload does not revert them on later normalization.
        merged = dict(existing)
        for key, value in incoming.items():
            if key == "date_last_updated":
                # The roster row's revision describes the roster write, not the deep
                # payload it is merged into. Advancing it would make a legacy identity
                # (one without ``deep_metadata_refreshed_at``) look freshly deep-hydrated
                # and skip the singular refresh that #4147 requires. Keeping the deep
                # payload's own revision lets freshness compare it with the identity's
                # provider revision.
                continue
            if _has_metadata_value(value):
                merged[key] = value
        return merged
    merged = dict(existing)
    for key, value in incoming.items():
        if _has_metadata_value(value) or key not in merged:
            merged[key] = value
    return merged


def merge_sparse_issue_metadata(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Merge a sparse volume-roster row into already-stored issue metadata.

    Roster rows are intentionally shallow. Replacing stored metadata with one erased
    creator credits, characters, teams, story arcs, covers, and the deep raw payload for
    issues that had already been hydrated from a singular response (#4147). Sparse fields
    therefore replace stored values only when they carry actual provider data. Explicit
    empty arrays from a *deep* response still replace, because ``persist_issue_result``
    does not use this merger for full singular rows.

    Args:
        existing: Metadata already stored on the external identity.
        incoming: Metadata normalized from a sparse volume-roster row.

    Returns:
        Merged metadata that preserves richer stored evidence.
    """
    merged = dict(existing)
    for key, value in incoming.items():
        if key == "raw_provider_payload":
            merged[key] = _merge_raw_issue_payload(existing.get(key), value)
        elif _has_metadata_value(value) or key not in merged:
            merged[key] = value
    return merged


def merge_cached_deep_metadata(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Persist a cache-served deep payload without advancing the deep-refresh clock.

    ComicVine can serve a deep singular payload from the local cache (adoption cache
    reuse, or a live request that fell back to cache after throttling), and that payload
    can be arbitrarily old. Writing it with ``deep_metadata_refreshed_at = now`` would
    hide stale credits for another full refresh window, so the stored clock survives the
    write; a row without one stays legacy and is re-evaluated by
    ``metadata_needs_hydration`` (#4147).

    Args:
        existing: Metadata already stored on the external identity.
        incoming: Metadata normalized from a cache-served deep issue response.

    Returns:
        The incoming deep payload with any stored refresh clock carried forward.
    """
    merged = dict(incoming)
    marker = existing.get(DEEP_METADATA_REFRESHED_AT_KEY)
    if isinstance(marker, str) and marker:
        merged[DEEP_METADATA_REFRESHED_AT_KEY] = marker
    return merged


def normalize_issue(result: dict[str, object]) -> dict[str, object]:
    """Normalize useful singular issue metadata while retaining the complete raw provider row.

    Args:
        result: ComicVine singular issue result.

    Returns:
        Stable metadata suitable for ``ExternalIdentity.metadata_json``.
    """
    volume = _compact_reference(result.get("volume"))
    image = result.get("image") if isinstance(result.get("image"), dict) else None
    primary_image = None
    if isinstance(image, dict):
        for key in ("original_url", "super_url", "medium_url", "small_url"):
            candidate = image.get(key)
            if isinstance(candidate, str) and candidate:
                primary_image = candidate
                break
    return {
        "name": result.get("name"),
        "issue_number": result.get("issue_number"),
        "cover_date": result.get("cover_date"),
        "store_date": result.get("store_date"),
        "volume": volume,
        "primary_image": primary_image,
        "creator_credits": _compact_references(result.get("person_credits")),
        "characters": _compact_references(result.get("character_credits")),
        "teams": _compact_references(result.get("team_credits")),
        "story_arcs": _compact_references(result.get("story_arc_credits")),
        "raw_provider_payload": result,
    }


def normalize_volume(result: dict[str, object]) -> dict[str, object]:
    """Normalize useful volume metadata while retaining the complete raw provider row.

    Args:
        result: ComicVine singular volume result.

    Returns:
        Stable metadata suitable for ``ExternalIdentity.metadata_json``.
    """
    publisher = _compact_reference(result.get("publisher"))
    image = result.get("image") if isinstance(result.get("image"), dict) else None
    primary_image = None
    if isinstance(image, dict):
        for key in ("original_url", "super_url", "medium_url", "small_url"):
            candidate = image.get(key)
            if isinstance(candidate, str) and candidate:
                primary_image = candidate
                break
    return {
        "name": result.get("name"),
        "publisher": publisher,
        "start_year": result.get("start_year"),
        "count_of_issues": result.get("count_of_issues"),
        "primary_image": primary_image,
        "raw_provider_payload": result,
    }


async def persist_issue_result(
    db: AsyncSession,
    result: dict[str, object],
    *,
    roster_row: bool = False,
    from_cache: bool = False,
) -> ExternalIdentity:
    """Upsert one ComicVine issue result into the provider-independent identity store.

    Args:
        db: Async database session.
        result: ComicVine issue result object.
        roster_row: True when ``result`` came from a volume's basic issue roster
            instead of a singular issue response. Roster rows are sparse, so they
            are merged into stored metadata rather than replacing it wholesale.
            Results that omit any deep singular-issue field are treated the same
            way even when this flag is not set.
        from_cache: True when the provider client served ``result`` from its local
            cache instead of a live request. A cached deep payload can be old, so it
            is persisted but never advances the deep-refresh clock.

    Returns:
        Persisted issue identity.

    Raises:
        ComicVineError: If the provider row has no stable numeric identity.
    """
    external_id = result.get("id")
    if not isinstance(external_id, int):
        raise ComicVineError("ComicVine issue result is missing an integer id")
    sparse_result = roster_row or not is_deep_issue_result(result)
    metadata = normalize_issue(result)
    metadata_merger: MetadataMerger | None = (
        merge_sparse_issue_metadata if sparse_result else None
    )
    if not sparse_result:
        if from_cache:
            # The payload came from cache (adoption reuse or a throttled live request
            # that fell back to cache), so it may be arbitrarily old. Persist it without
            # moving the refresh clock, or stale credits would look fresh for another
            # window and the retry that follows the throttle would be skipped.
            metadata_merger = merge_cached_deep_metadata
        else:
            # Record when this application fetched the deep payload. ComicVine's own
            # ``date_last_updated`` is a provider edit date and must not double as the
            # refresh clock, or an unedited issue would be re-fetched on every read.
            metadata[DEEP_METADATA_REFRESHED_AT_KEY] = datetime.now(UTC).isoformat()
    return await upsert_external_identity(
        db,
        provider=COMICVINE_PROVIDER,
        entity_type="issue",
        external_id=str(external_id),
        external_url=_external_url(result.get("site_detail_url")),
        metadata_json=metadata,
        provider_updated_at=_provider_timestamp(result.get("date_last_updated")),
        metadata_merger=metadata_merger,
    )


async def persist_volume_result(
    db: AsyncSession,
    result: dict[str, object],
) -> ExternalIdentity:
    """Upsert one ComicVine volume result into the provider-independent identity store.

    Args:
        db: Async database session.
        result: ComicVine volume result object.

    Returns:
        Persisted series identity.

    Raises:
        ComicVineError: If the provider row has no stable numeric identity.
    """
    external_id = result.get("id")
    if not isinstance(external_id, int):
        raise ComicVineError("ComicVine volume result is missing an integer id")
    return await upsert_external_identity(
        db,
        provider=COMICVINE_PROVIDER,
        entity_type="series",
        external_id=str(external_id),
        external_url=_external_url(result.get("site_detail_url")),
        metadata_json=normalize_volume(result),
        provider_updated_at=_provider_timestamp(result.get("date_last_updated")),
    )


async def hydrate_issue(
    db: AsyncSession,
    client: ComicVineClient,
    issue_id: int,
    *,
    refresh: bool = False,
) -> ExternalIdentity:
    """Deep-hydrate one issue and cache every story arc it explicitly references.

    Each provider resource is fetched independently. Story-arc failures do not discard the
    successfully persisted issue metadata; callers can commit the returned identity and retry the
    missing cached resource later.

    Cache provenance is forwarded to :func:`persist_issue_result`, so a payload the provider
    served from its local cache updates stored evidence without advancing the deep-refresh
    clock (#4147).

    Args:
        db: Async database session.
        client: Configured ComicVine provider client.
        issue_id: ComicVine issue ID.
        refresh: Force live provider fetches instead of cache reuse.

    Returns:
        Persisted external issue identity.
    """
    response = await client.fetch_issue(issue_id, refresh=refresh)
    result = _result_object(response.payload)
    identity = await persist_issue_result(db, result, from_cache=response.from_cache)
    arcs = result.get("story_arc_credits")
    if isinstance(arcs, list):
        seen: set[int] = set()
        for arc in arcs:
            if not isinstance(arc, dict):
                continue
            arc_id = arc.get("id")
            if not isinstance(arc_id, int) or arc_id in seen:
                continue
            seen.add(arc_id)
            try:
                await client.fetch_story_arc(arc_id, refresh=refresh)
            except ComicVineError:
                continue
    return identity


async def hydrate_volume(
    db: AsyncSession,
    client: ComicVineClient,
    volume_id: int,
    *,
    refresh: bool = False,
) -> tuple[ExternalIdentity, list[ExternalIdentity]]:
    """Hydrate one volume and its complete basic issue roster idempotently.

    Args:
        db: Async database session.
        client: Configured ComicVine provider client.
        volume_id: ComicVine volume ID.
        refresh: Force live provider fetches instead of cache reuse.

    Returns:
        Persisted series identity and persisted basic issue identities.
    """
    volume_response = await client.fetch_volume(volume_id, refresh=refresh)
    volume_identity = await persist_volume_result(db, _result_object(volume_response.payload))
    issue_rows = await client.fetch_volume_issues(volume_id, refresh=refresh)
    issue_identities: list[ExternalIdentity] = []
    for row in issue_rows:
        issue_identities.append(await persist_issue_result(db, row, roster_row=True))
    return volume_identity, issue_identities
