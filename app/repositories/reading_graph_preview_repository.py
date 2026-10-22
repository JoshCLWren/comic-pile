"""Read-only persistence inputs for the prospective reading-graph preview.

The preview needs the same owner-scoped constraints the canonical Option E
evaluator executes, plus the exact Comic Vine volume identity of every owned
Thread. Nothing here writes reader state: the queries only describe what the
reader already owns plus the source list being previewed.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping

from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogSeries
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.thread import Thread
from app.services.collection_exclusion_guard import normalize_volume

_COMICVINE_PROVIDER = "comicvine"
_VOLUME_ENTITY_TYPE = "series"
_COMICVINE_SERIES_ID_PATTERN = re.compile(r"^(?:4050-)?([0-9]+)$")


def canonical_volume_key(provider: str, external_id: str) -> str | None:
    """Return the canonical Comic Vine volume key, or None for other providers.

    Args:
        provider: Provider that owns the series identity.
        external_id: Provider external identifier of the series identity.

    Returns:
        ``comicvine:<normalized id>`` for a Comic Vine volume, otherwise None.
    """
    normalized_provider, normalized_id = normalize_volume(provider, external_id)
    if normalized_provider != _COMICVINE_PROVIDER or not normalized_id:
        return None
    return f"{_COMICVINE_PROVIDER}:{normalized_id}"


async def _volume_candidates(
    db: AsyncSession, user_id: int, thread_ids: Collection[int]
) -> dict[int, set[str]]:
    """Collect every exact Comic Vine volume claimed by each owned Thread."""
    if not thread_ids:
        return {}
    confirmed = (
        select(Thread.id, ExternalIdentity.provider, ExternalIdentity.external_id)
        .join(ThreadExternalSeriesMapping, ThreadExternalSeriesMapping.thread_id == Thread.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.entity_type == _VOLUME_ENTITY_TYPE,
        )
    )
    catalog = (
        select(Thread.id, ExternalIdentity.provider, ExternalIdentity.external_id)
        .join(CatalogSeries, CatalogSeries.id == Thread.catalog_series_id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == CatalogSeries.canonical_external_identity_id,
        )
        .where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
            ExternalIdentity.entity_type == _VOLUME_ENTITY_TYPE,
        )
    )
    rows = await db.execute(union_all(confirmed, catalog))
    candidates: dict[int, set[str]] = {}
    for thread_id, provider, external_id in rows.all():
        key = canonical_volume_key(provider, external_id)
        if key is not None:
            candidates.setdefault(thread_id, set()).add(key)
    return candidates


async def resolve_thread_volume_keys(
    db: AsyncSession, user_id: int, thread_ids: Collection[int]
) -> dict[int, str]:
    """Resolve owned Threads to one exact Comic Vine volume key when unambiguous.

    A Thread with missing, ambiguous, or non-Comic-Vine evidence is absent from
    the result, so no overlap decision can be applied to the wrong run.

    Args:
        db: Current read transaction.
        user_id: Reader whose Threads are resolved.
        thread_ids: Owned Thread identifiers to resolve.

    Returns:
        Mapping of Thread ID to canonical ``comicvine:<id>`` volume key.
    """
    candidates = await _volume_candidates(db, user_id, thread_ids)
    return {thread_id: next(iter(keys)) for thread_id, keys in candidates.items() if len(keys) == 1}


def _external_id_candidates(key: str) -> tuple[str, ...]:
    """Return stored external-id spellings that can produce one volume key."""
    prefix = f"{_COMICVINE_PROVIDER}:"
    if not key.startswith(prefix):
        return ()
    external_id = key[len(prefix) :]
    values = {external_id}
    if _COMICVINE_SERIES_ID_PATTERN.match(external_id):
        match = _COMICVINE_SERIES_ID_PATTERN.match(external_id)
        if match is not None:
            numeric = match.group(1)
            values.update({numeric, f"4050-{numeric}"})
    return tuple(sorted(values))


def _metadata_year(metadata: Mapping[str, object] | None) -> int | None:
    """Return a stored publication year from provider metadata, when valid."""
    if not isinstance(metadata, Mapping):
        return None
    for field in ("start_year", "year", "volume_year"):
        value = metadata.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if 1000 <= value <= 9999:
            return value
    return None


async def load_volume_years(db: AsyncSession, keys: Collection[str]) -> dict[str, int]:
    """Resolve canonical volume keys to a stored publication year when known.

    Args:
        db: Current read transaction.
        keys: Canonical ``comicvine:<id>`` volume keys in the graph.

    Returns:
        Mapping of canonical volume key to publication year for identities whose
        provider metadata declares a valid year.
    """
    wanted = {key for key in keys if key.startswith(f"{_COMICVINE_PROVIDER}:")}
    if not wanted:
        return {}
    external_ids = {spelling for key in wanted for spelling in _external_id_candidates(key)}
    if not external_ids:
        return {}
    rows = await db.execute(
        select(ExternalIdentity.external_id, ExternalIdentity.metadata_json).where(
            ExternalIdentity.provider == _COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == _VOLUME_ENTITY_TYPE,
            ExternalIdentity.external_id.in_(external_ids),
        )
    )
    years: dict[str, int] = {}
    for external_id, metadata in rows.all():
        key = canonical_volume_key(_COMICVINE_PROVIDER, external_id)
        if key is None or key not in wanted:
            continue
        year = _metadata_year(metadata)
        if year is not None:
            years[key] = year
    return years
