"""ComicVine taste-feature extraction for Taste Bank discovery.

Extracts stable, normalized taste features from confirmed ComicVine issue
metadata. Implements the feature-extraction layer from issue #1743:
creators (with role), characters, teams, publisher, and publication-era bucket.

Duplicate credits are deduplicated by stable ID when available, falling back
to display name. Missing or unconfirmed metadata yields no fabricated evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.schemas.comicvine import ComicVineCreator


@dataclass(frozen=True, slots=True)
class TasteFeature:
    """One normalized taste feature extracted from ComicVine metadata.

    Attributes:
        signal_type: Category of the taste feature.
        stable_key: Stable identifier - external ID when available, otherwise
            a normalized display string.
        display_name: Human-readable name for UI display.
        role: For creator features, the primary role (e.g. "writer", "artist").
    """

    signal_type: str
    stable_key: str
    display_name: str
    role: str | None = None


def _string(value: object) -> str | None:
    """Normalize a raw metadata value to a trimmed string or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _integer(value: object) -> int | None:
    """Normalize a raw metadata value to an int or None."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _reference_list(metadata: dict[str, object], *keys: str) -> list[dict[str, object]]:
    """Return the first list found under any of the provided keys."""
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_creators(metadata: dict[str, object]) -> list[TasteFeature]:
    """Extract creator features with role preservation from ComicVine metadata.

    Deduplicates by (name, roles) tuple to avoid double-counting the same
    creator with different role representations.

    Args:
        metadata: Confirmed ComicVine issue metadata dict.

    Returns:
        List of TasteFeature instances with signal_type="creator".
    """
    seen: set[tuple[str, tuple[str, ...]]] = set()
    features: list[TasteFeature] = []

    for credit in _reference_list(metadata, "person_credits", "creator_credits"):
        name = _string(credit.get("name"))
        if not name:
            continue
        role_value = _string(credit.get("role")) or ""
        roles = tuple(sorted({role.strip() for role in role_value.split(",") if role.strip()}))
        dedup_key = (name.lower(), roles)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        primary_role = roles[0] if roles else None
        features.append(
            TasteFeature(
                signal_type="creator",
                stable_key=name.lower().strip(),
                display_name=name.strip(),
                role=primary_role,
            )
        )

    return features


def _extract_characters(metadata: dict[str, object]) -> list[TasteFeature]:
    """Extract character features from ComicVine metadata.

    Checks story_arc_credits first, then character_credits as fallback.
    Deduplicates by character id (preferred) or name.

    Args:
        metadata: Confirmed ComicVine issue metadata dict.

    Returns:
        List of TasteFeature instances with signal_type="character".
    """
    seen: set[str] = set()
    features: list[TasteFeature] = []

    for credit in _reference_list(metadata, "story_arc_credits", "character_credits"):
        char_id = _integer(credit.get("id"))
        name = _string(credit.get("name"))
        if not name:
            continue
        stable_key = f"char:{char_id}" if char_id is not None else name.lower().strip()
        if stable_key in seen:
            continue
        seen.add(stable_key)
        features.append(
            TasteFeature(
                signal_type="character",
                stable_key=stable_key,
                display_name=name.strip(),
            )
        )

    return features


def _extract_teams(metadata: dict[str, object]) -> list[TasteFeature]:
    """Extract team features from ComicVine metadata.

    Deduplicates by team id (preferred) or name.

    Args:
        metadata: Confirmed ComicVine issue metadata dict.

    Returns:
        List of TasteFeature instances with signal_type="team".
    """
    seen: set[str] = set()
    features: list[TasteFeature] = []

    for credit in _reference_list(metadata, "team_credits"):
        team_id = _integer(credit.get("id"))
        name = _string(credit.get("name"))
        if not name:
            continue
        stable_key = f"team:{team_id}" if team_id is not None else name.lower().strip()
        if stable_key in seen:
            continue
        seen.add(stable_key)
        features.append(
            TasteFeature(
                signal_type="team",
                stable_key=stable_key,
                display_name=name.strip(),
            )
        )

    return features


def _extract_publisher(metadata: dict[str, object]) -> list[TasteFeature]:
    """Extract publisher feature from ComicVine metadata.

    Uses the first non-empty publisher value found in the metadata.

    Args:
        metadata: Confirmed ComicVine issue metadata dict.

    Returns:
        List containing one TasteFeature with signal_type="publisher", or an
        empty list when no publisher is present.
    """
    publisher = (
        _string(metadata.get("publisher"))
        or _string(metadata.get("publisher_name"))
        or _string((metadata.get("volume") or {}).get("publisher_name"))
    )
    if not publisher:
        return []

    return [
        TasteFeature(
            signal_type="publisher",
            stable_key=publisher.lower().strip(),
            display_name=publisher.strip(),
        )
    ]


def _extract_era(metadata: dict[str, object]) -> list[TasteFeature]:
    """Extract publication-era feature from ComicVine issue metadata.

    Converts cover_date or store_date into a decade bucket string such as
    "1990s" or "2000s". Returns no feature when no date is available.

    Args:
        metadata: Confirmed ComicVine issue metadata dict.

    Returns:
        List containing one TasteFeature with signal_type="era", or an empty
        list when no parseable date is present.
    """
    date_str = (
        _string(metadata.get("cover_date"))
        or _string(metadata.get("store_date"))
        or _string((metadata.get("volume") or {}).get("start_year"))
    )

    if not date_str:
        return []

    year: int | None = None

    if isinstance(date_str, str) and date_str.strip().isdigit():
        year = int(date_str.strip())
    elif isinstance(date_str, str) and len(date_str) >= 4:
        year_candidate = date_str.strip()[:4]
        if year_candidate.isdigit():
            year = int(year_candidate)

    if year is None or year <= 0:
        return []

    decade_start = (year // 10) * 10
    display = f"{decade_start}s"

    return [
        TasteFeature(
            signal_type="era",
            stable_key=display,
            display_name=display,
        )
    ]


def extract_taste_features(
    metadata: dict[str, object],
) -> list[TasteFeature]:
    """Extract all normalized taste features from confirmed ComicVine metadata.

    Groups features by type against the ComicVine metadata payload and
    deduplicates each group. Does not fabricate features for missing or
    unconfirmed metadata.

    Args:
        metadata: Confirmed ComicVine issue metadata dict from
            ``external_identities.metadata_json``.

    Returns:
        Deduplicated list of TasteFeature instances covering creators,
        characters, teams, publisher, and publication era.
    """
    if not isinstance(metadata, dict) or not metadata:
        return []

    features: list[TasteFeature] = []
    features.extend(_extract_creators(metadata))
    features.extend(_extract_characters(metadata))
    features.extend(_extract_teams(metadata))
    features.extend(_extract_publisher(metadata))
    features.extend(_extract_era(metadata))

    return features