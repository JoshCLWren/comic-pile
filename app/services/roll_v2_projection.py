"""Bounded Roll v2 bootstrap projection assembly (issue #2717).

Builds the frozen v2 ``rollable[]`` read model and session ``last_read``
from exactly three bulk repository round trips, independent of pool size:

1. candidate threads with next-issue, identity mappings, routes, thread counts;
2. canonical-series aggregates (effective ratings, read counts, catalog size);
3. the latest session ``rate`` event.

No per-row queries exist: identity, cover, rating, progress, and route data
all come from these bulk rows. ComicVine is never called synchronously;
missing stored metadata yields nulls. Threads with no next unread issue are
omitted and reported as omitted so callers can prove they hold no roll target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import normalize_format_value
from app.repositories import roll_v2_projection as projection_repo
from app.schemas.roll_v2 import (
    IdentityState,
    ProgressScope,
    RollableIdentity,
    RollableIssue,
    RollableItem,
    RollableReader,
    RollableRoute,
    RollableThread,
    RollLastRead,
    RouteKind,
)

COVER_WIDTH = 480
MAX_ROUTES = 3


def _integer(value: object) -> int | None:
    """Coerce a stored provider value to an int.

    Args:
        value: Raw provider value.

    Returns:
        The integer value, or None when not numeric.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _string(value: object) -> str | None:
    """Coerce a stored provider value to a trimmed non-empty string.

    Args:
        value: Raw provider value.

    Returns:
        The trimmed string, or None when empty or not a string.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def extract_volume(metadata: dict[str, object] | None) -> tuple[int | None, str | None]:
    """Extract the canonical ComicVine volume id and name from stored metadata.

    The canonical series is always derived from the next unread issue's own
    confirmed identity, never from thread-level mappings, so composite
    threads with mixed ComicVine volumes never flatten into one fake series.

    Args:
        metadata: Confirmed ComicVine issue identity metadata.

    Returns:
        Tuple of (volume id, volume name), either of which may be None.
    """
    if not metadata:
        return None, None
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        return _integer(volume.get("id")), _string(volume.get("name"))
    return _integer(metadata.get("volume_id")), _string(metadata.get("volume_name"))


def extract_cover_source(metadata: dict[str, object] | None) -> str | None:
    """Extract the stored canonical cover source URL from identity metadata.

    Args:
        metadata: Confirmed ComicVine issue identity metadata.

    Returns:
        The first available stored image URL, or None when absent.
    """
    if not metadata:
        return None
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


def build_cover_url(source: str | None) -> str | None:
    """Build the same-origin optimized cover URL for a stored source.

    Raw provider URLs are never exposed as the Roll contract; remote http(s)
    sources are routed through the edge-cacheable image proxy. Non-remote or
    missing sources yield nulls, not bootstrap failure.

    Args:
        source: Stored canonical image URL.

    Returns:
        Same-origin ``/api/v1/images/optimize?...`` URL, or None.
    """
    if not source:
        return None
    lowered = source.lower()
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        return None
    return f"/api/v1/images/optimize?url={quote(source, safe='')}&width={COVER_WIDTH}"


def derive_identity_state(
    confirmed_external_ids: list[str],
    candidate_count: int,
    has_any_mapping: bool,
) -> IdentityState:
    """Derive the frozen identity state from stored mapping evidence.

    Args:
        confirmed_external_ids: Distinct confirmed external ids observed.
        candidate_count: Number of candidate/unresolved mappings observed.
        has_any_mapping: Whether any non-rejected mapping row exists.

    Returns:
        The frozen derived identity state.
    """
    if len(confirmed_external_ids) > 1:
        return IdentityState.CONFLICTING
    if len(confirmed_external_ids) == 1:
        return IdentityState.CONFIRMED
    if candidate_count > 1:
        return IdentityState.AMBIGUOUS
    if candidate_count == 1:
        return IdentityState.CANDIDATE
    if has_any_mapping:
        return IdentityState.UNRESOLVED
    return IdentityState.UNRESOLVED


class _CandidateGroup:
    """Per-thread accumulation of bulk candidate rows."""

    def __init__(self, first: projection_repo.RollableCandidateRow) -> None:
        """Seed the group from the first bulk row for the thread.

        Args:
            first: First candidate row for this thread.
        """
        self.thread_id = first["thread_id"]
        self.thread_title = first["thread_title"]
        self.thread_format = first["thread_format"]
        self.last_activity_at = first["last_activity_at"]
        self.issue_id = first["issue_id"]
        self.issue_number = first["issue_number"]
        self.issue_status = first["issue_status"]
        self.route_labels = first["route_labels"]
        self.thread_read_count = first["thread_read_count"]
        self.thread_total_count = first["thread_total_count"]
        self.issue_mappings: list[projection_repo.RollableCandidateRow] = []
        self.series_mappings: list[projection_repo.RollableCandidateRow] = []
        self.add(first)

    def add(self, row: projection_repo.RollableCandidateRow) -> None:
        """Fold one bulk row's mapping evidence into the group.

        Args:
            row: Bulk candidate row for the same thread.
        """
        if row["mapping_status"] is not None and row["mapping_external_id"] is not None:
            if not any(
                existing["mapping_external_id"] == row["mapping_external_id"]
                and existing["mapping_status"] == row["mapping_status"]
                for existing in self.issue_mappings
            ):
                self.issue_mappings.append(row)
        elif row["mapping_status"] is not None:
            self.issue_mappings.append(row)
        if row["series_mapping_status"] is not None and row["series_external_id"] is not None:
            if not any(
                existing["series_external_id"] == row["series_external_id"]
                and existing["series_mapping_status"] == row["series_mapping_status"]
                for existing in self.series_mappings
            ):
                self.series_mappings.append(row)
        elif row["series_mapping_status"] is not None:
            self.series_mappings.append(row)


def _best_confirmed_metadata(
    mappings: list[projection_repo.RollableCandidateRow],
) -> dict[str, object] | None:
    """Return the stored metadata of the best confirmed issue identity.

    Args:
        mappings: Deduplicated issue mapping rows for one thread.

    Returns:
        Metadata of the highest-confidence confirmed identity, or None.
    """
    confirmed = [row for row in mappings if row["mapping_status"] == "confirmed"]
    if not confirmed:
        return None
    confirmed.sort(
        key=lambda row: (
            -(row["mapping_confidence"] if row["mapping_confidence"] is not None else -1.0),
            row["mapping_external_id"] or "",
        )
    )
    return confirmed[0]["mapping_metadata"]


class _SeriesStats:
    """Per-volume aggregates using #1401 distinct-issue effective ratings."""

    def __init__(self) -> None:
        """Initialize empty per-volume accumulation."""
        self.read_issue_ids: set[int] = set()
        self.effective: dict[int, tuple[float, datetime]] = {}
        self.series_name: str | None = None
        self.series_issue_count: int | None = None


async def get_v2_rollable_projection(
    db: AsyncSession,
    *,
    user_id: int,
    die_size: int,
    excluded_thread_ids: list[int],
    session_id: int,
) -> tuple[list[RollableItem], RollLastRead | None, list[int]]:
    """Build v2 rollable items and session last-read in three round trips.

    Args:
        db: Async database session.
        user_id: Owner of the threads.
        die_size: Current die size capping the candidate pool.
        excluded_thread_ids: Snoozed/skipped thread ids to exclude.
        session_id: Active reading session for last-read resolution.

    Returns:
        Tuple of (rollable items, session last-read or None, omitted thread
        ids that held no next unread issue).
    """
    candidate_rows = await projection_repo.fetch_rollable_candidates(
        db,
        user_id=user_id,
        die_size=die_size,
        excluded_thread_ids=excluded_thread_ids,
    )
    groups: dict[int, _CandidateGroup] = {}
    order: list[int] = []
    for row in candidate_rows:
        group = groups.get(row["thread_id"])
        if group is None:
            group = _CandidateGroup(row)
            groups[row["thread_id"]] = group
            order.append(row["thread_id"])
        else:
            group.add(row)

    valid_groups: list[_CandidateGroup] = []
    omitted_thread_ids: list[int] = []
    for thread_id in order:
        group = groups[thread_id]
        if (
            group.issue_id is None
            or group.issue_number is None
            or group.issue_status != "unread"
        ):
            omitted_thread_ids.append(thread_id)
            continue
        valid_groups.append(group)

    volumes: list[int] = []
    group_volumes: dict[int, int | None] = {}
    group_volume_names: dict[int, str | None] = {}
    group_metadata: dict[int, dict[str, object] | None] = {}
    for group in valid_groups:
        metadata = _best_confirmed_metadata(group.issue_mappings)
        group_metadata[group.thread_id] = metadata
        volume_id, volume_name = extract_volume(metadata)
        group_volumes[group.thread_id] = volume_id
        group_volume_names[group.thread_id] = volume_name
        if volume_id is not None and volume_id not in volumes:
            volumes.append(volume_id)

    stats: dict[int, _SeriesStats] = {volume_id: _SeriesStats() for volume_id in volumes}
    if volumes:
        aggregate_rows = await projection_repo.fetch_series_aggregates(
            db, user_id=user_id, volume_ids=volumes
        )
        for agg_row in aggregate_rows:
            volume_id, _ = extract_volume(agg_row["identity_metadata"])
            if volume_id is None or volume_id not in stats:
                continue
            entry = stats[volume_id]
            entry.read_issue_ids.add(agg_row["issue_id"])
            if agg_row["rating"] is not None and agg_row["rated_at"] is not None:
                current = entry.effective.get(agg_row["issue_id"])
                candidate = (agg_row["rating"], agg_row["rated_at"])
                if current is None or (candidate[1], candidate[0]) > (current[1], current[0]):
                    entry.effective[agg_row["issue_id"]] = candidate
            if entry.series_name is None and agg_row["series_name"]:
                entry.series_name = agg_row["series_name"]
            if entry.series_issue_count is None and agg_row["series_issue_count"]:
                parsed = _integer(agg_row["series_issue_count"])
                if parsed is not None:
                    entry.series_issue_count = parsed

    rollable: list[RollableItem] = []
    for group in valid_groups:
        volume_id = group_volumes[group.thread_id]
        metadata = group_metadata[group.thread_id]
        confirmed_ids = sorted(
            {
                row["mapping_external_id"]
                for row in group.issue_mappings
                if row["mapping_status"] == "confirmed" and row["mapping_external_id"]
            }
        )
        candidate_count = sum(
            1
            for row in group.issue_mappings
            if row["mapping_status"] in ("candidate", "unresolved")
        )
        issue_state = derive_identity_state(
            confirmed_ids,
            candidate_count,
            has_any_mapping=bool(group.issue_mappings),
        )
        series_confirmed_ids = sorted(
            {
                row["series_external_id"]
                for row in group.series_mappings
                if row["series_mapping_status"] == "confirmed" and row["series_external_id"]
            }
        )
        series_candidate_count = sum(
            1
            for row in group.series_mappings
            if row["series_mapping_status"] in ("candidate", "unresolved")
        )
        series_state = derive_identity_state(
            series_confirmed_ids,
            series_candidate_count,
            has_any_mapping=bool(group.series_mappings),
        )
        if volume_id is not None:
            source: Literal["comicvine", "unavailable"] = "comicvine"
            canonical_series_id: str | None = str(volume_id)
        else:
            source = "unavailable"
            canonical_series_id = None

        issue_title = group_volume_names[group.thread_id]
        if issue_title is None and volume_id is not None:
            issue_title = stats[volume_id].series_name
        cover_url = build_cover_url(extract_cover_source(metadata))
        # The DTO requires ISO strings; normalize defensively without failing.
        activity = group.last_activity_at
        last_activity: str | None
        if activity is None:
            last_activity = None
        elif isinstance(activity, str):
            last_activity = activity
        else:
            last_activity = activity.isoformat()

        rollable_thread = RollableThread(
            id=group.thread_id,
            title=group.thread_title,
            format=normalize_format_value(group.thread_format),
            last_activity_at=last_activity,
        )
        assert group.issue_id is not None and group.issue_number is not None
        rollable_issue = RollableIssue(
            id=group.issue_id,
            number=group.issue_number,
            canonical_series_title=issue_title,
            cover_url=cover_url,
        )
        rollable_identity = RollableIdentity(
            source=source,
            canonical_series_id=canonical_series_id,
            state=issue_state,
            series_mapping_state=series_state,
        )
        if volume_id is not None:
            entry = stats[volume_id]
            ratings = sorted(entry.effective.values(), key=lambda item: (item[1], item[0]))
            average = (
                round(sum(value for value, _ in ratings) / len(ratings), 2) if ratings else None
            )
            latest = ratings[-1][0] if ratings else None
            read_count = len(entry.read_issue_ids)
            issue_count = entry.series_issue_count
            if issue_count is None:
                for series_row in group.series_mappings:
                    series_meta = series_row["series_metadata"]
                    if (
                        series_row["series_mapping_status"] == "confirmed"
                        and series_row["series_external_id"] == str(volume_id)
                        and isinstance(series_meta, dict)
                    ):
                        parsed = _integer(series_meta.get("count_of_issues"))
                        if parsed is not None:
                            issue_count = parsed
                            break
            rollable_reader = RollableReader(
                latest_rating=latest,
                average_rating=average,
                rating_count=len(ratings) if ratings else 0,
                read_count=read_count,
                issue_count=issue_count,
                progress_scope=ProgressScope.CANONICAL_SERIES_RUN,
            )
        else:
            total = group.thread_total_count
            rollable_reader = RollableReader(
                latest_rating=None,
                average_rating=None,
                rating_count=0,
                read_count=group.thread_read_count,
                issue_count=total if total > 0 else None,
                progress_scope=ProgressScope.THREAD,
            )
        visible_names = group.route_labels[:MAX_ROUTES]
        routes = [RollableRoute(kind=RouteKind.GROUP, name=name) for name in visible_names]
        rollable.append(
            RollableItem(
                thread=rollable_thread,
                issue=rollable_issue,
                identity=rollable_identity,
                reader=rollable_reader,
                routes=routes,
                overflow_routes_count=max(0, len(group.route_labels) - len(visible_names)),
            )
        )

    last_read_row = await projection_repo.fetch_session_last_read(
        db, session_id=session_id, user_id=user_id
    )
    last_read: RollLastRead | None = None
    if last_read_row is not None and (
        last_read_row["issue_id"] is not None or last_read_row["thread_id"] is not None
    ):
        read_at = last_read_row["read_at"]
        last_read = RollLastRead(
            issue_id=last_read_row["issue_id"],
            issue_number=last_read_row["issue_number"],
            thread_id=last_read_row["thread_id"],
            thread_title=last_read_row["thread_title"],
            read_at=read_at if isinstance(read_at, datetime) else None,
        )
    return rollable, last_read, omitted_thread_ids
