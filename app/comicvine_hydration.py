"""ComicVine hydration services built on provider-independent external identities."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import upsert_external_identity
from app.models.external_identity import ExternalIdentity
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError

COMICVINE_PROVIDER = "comicvine"


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


# Key names for the ``image`` object of a ComicVine resource, ordered from the
# highest-quality rendition to the lowest.
#
# The classic provider endpoint used by this repository
# (``https://comicvine.gamespot.com/api``) emits ``_url``-suffixed keys. Some
# normalized or third-party payloads instead drop the suffix and expose bare
# names. Both shapes are accepted so a provider payload never loses its cover
# merely because of which naming convention it used.
_PROVIDER_IMAGE_KEYS_BY_QUALITY = (
    "super",
    "screen_large",
    "large",
    "original_url",
    "super_url",
    "screen_large_url",
    "large_url",
    "medium",
    "medium_url",
    "small",
    "small_url",
    "screen_url",
    "thumb_url",
    "tiny_url",
    "icon",
    "icon_url",
)

# Bounded-size renditions first, then the large ones as a last resort. List and
# search surfaces render these at thumbnail sizes, so they must not be forced
# to download full-page cover art from the provider.
_PROVIDER_IMAGE_THUMB_KEYS_BY_QUALITY = (
    "medium",
    "small",
    "icon",
    "medium_url",
    "small_url",
    "screen_url",
    "thumb_url",
    "tiny_url",
    "icon_url",
    "screen_large",
    "large",
    "super",
    "screen_large_url",
    "large_url",
    "super_url",
    "original_url",
)


def _first_image_url(image_raw: object, keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty string image URL among ``keys`` in ``image_raw``.

    Args:
        image_raw: Raw ``image`` field of a ComicVine resource, or any other value.
        keys: Image object keys to probe, in preference order.

    Returns:
        The best available image URL as a non-empty string, or ``None``.
    """
    if not isinstance(image_raw, dict):
        return None
    for key in keys:
        candidate = image_raw.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def extract_image_url(image_raw: object) -> str | None:
    """Extract the best available cover image URL from a ComicVine image object.

    Cover surfaces (Roll cards, issue intelligence) want the highest-quality
    rendition the provider offers. The classic ``_url``-suffixed keys emitted by
    ``comicvine.gamespot.com/api`` and the bare names used by normalized
    payloads are both recognized.

    Args:
        image_raw: The raw ``image`` field of a ComicVine resource, or another
            value when no image object is available.

    Returns:
        The best available image URL as a non-empty string, or ``None`` when the
        field is absent or empty.
    """
    return _first_image_url(image_raw, _PROVIDER_IMAGE_KEYS_BY_QUALITY)


def extract_thumbnail_url(image_raw: object) -> str | None:
    """Extract the best bounded-size image URL for list and search surfaces.

    Search dialogs, identity-inbox candidate lists, and resolve confirmation
    cards render covers at thumbnail sizes. They must prefer medium/small
    renditions so fetching a candidate row never downloads full-page cover art.
    Large renditions are only used when no bounded-size rendition exists.

    Args:
        image_raw: The raw ``image`` field of a ComicVine resource, or another
            value when no image object is available.

    Returns:
        The best available thumbnail URL as a non-empty string, or ``None`` when
        the field is absent or empty.
    """
    return _first_image_url(image_raw, _PROVIDER_IMAGE_THUMB_KEYS_BY_QUALITY)


def normalize_issue(result: dict[str, object]) -> dict[str, object]:
    """Normalize useful singular issue metadata while retaining the complete raw provider row.

    Args:
        result: ComicVine singular issue result.

    Returns:
        Stable metadata suitable for ``ExternalIdentity.metadata_json``.
    """
    volume = _compact_reference(result.get("volume"))
    primary_image = extract_image_url(result.get("image"))
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
    primary_image = extract_image_url(result.get("image"))
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
) -> ExternalIdentity:
    """Upsert one ComicVine issue result into the provider-independent identity store.

    Args:
        db: Async database session.
        result: ComicVine issue result object.

    Returns:
        Persisted issue identity.

    Raises:
        ComicVineError: If the provider row has no stable numeric identity.
    """
    external_id = result.get("id")
    if not isinstance(external_id, int):
        raise ComicVineError("ComicVine issue result is missing an integer id")
    return await upsert_external_identity(
        db,
        provider=COMICVINE_PROVIDER,
        entity_type="issue",
        external_id=str(external_id),
        external_url=_external_url(result.get("site_detail_url")),
        metadata_json=normalize_issue(result),
        provider_updated_at=_provider_timestamp(result.get("date_last_updated")),
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
    identity = await persist_issue_result(db, result)
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
        issue_identities.append(await persist_issue_result(db, row))
    return volume_identity, issue_identities
