"""Read-only Roll v2 comparisons against independent database observations.

This diagnostic is intentionally outside the request path. Run it against a
stable fixture or a repeatable-read transaction, not a changing live response.
It checks returned targets, thread facts, routes, canonical progress/ratings,
and session last-read without calling production projection query helpers.
"""

from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import normalize_format_value
from app.repositories import roll_v2_parity as reference
from app.schemas.roll_v2 import RollableItem, RollLastRead


@dataclass(frozen=True)
class ParityDifference:
    """One observable discrepancy between reference facts and a response."""

    field: str
    thread_id: int | None
    expected: object
    actual: object


@dataclass(frozen=True)
class ParityReport:
    """Independent comparison results and reference-read wall time."""

    compared_items: int
    reference_ms: float
    differences: tuple[ParityDifference, ...]


def _volume(metadata: dict[str, object] | None) -> int | None:
    if metadata is None:
        return None
    nested = metadata.get("volume")
    value = nested.get("id") if isinstance(nested, dict) else metadata.get("volume_id")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


async def compare_roll_projection(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: int,
    items: list[RollableItem],
    last_read: RollLastRead | None,
) -> ParityReport:
    """Compare a v2 projection with independently queried stored facts.

    Args:
        db: A stable transaction containing the response's source data.
        user_id: Owner scope for every reader-specific reference query.
        session_id: Reading-history session whose last-read must match.
        items: Actual production rollable items, in response order.
        last_read: Actual production last-read value.

    Returns:
        Named mismatches and measured reference time; an empty differences
        tuple means the checked fields agree. The diagnostic does not modify data.
    """
    started = perf_counter()
    thread_ids = [item.thread.id for item in items]
    issue_ids = [item.issue.id for item in items]
    frontiers = await reference.fetch_parity_frontiers(db, user_id, thread_ids)
    facts = await reference.fetch_parity_thread_facts(db, user_id, thread_ids)
    mappings = await reference.fetch_parity_issue_mappings(db, user_id, issue_ids)
    series = await reference.fetch_parity_series_mappings(db, user_id, thread_ids)
    analytics = await reference.fetch_parity_series_analytics(db, user_id)
    memberships = await reference.fetch_parity_route_memberships(db, user_id, thread_ids, issue_ids)
    latest = await reference.fetch_parity_last_read(db, session_id, user_id)
    volumes = {
        volume
        for rows in mappings.values()
        for row in rows
        if row["mapping_status"] == "confirmed"
        and (volume := _volume(row["mapping_metadata"])) is not None
    }
    catalog = await reference.fetch_parity_series_catalog(db, sorted(volumes))
    differences: list[ParityDifference] = []

    def check(field: str, thread_id: int | None, expected: object, actual: object) -> None:
        if expected != actual:
            differences.append(ParityDifference(field, thread_id, expected, actual))

    for item in items:
        tid = item.thread.id
        frontier = frontiers.get(tid)
        check("issue.id", tid, frontier["issue_id"] if frontier else None, item.issue.id)
        check(
            "issue.number", tid, frontier["issue_number"] if frontier else None, item.issue.number
        )
        fact = facts.get(tid)
        if fact is None:
            check("thread.owner", tid, "owned thread", None)
            continue
        check("thread.title", tid, fact["title"], item.thread.title)
        check("thread.format", tid, normalize_format_value(fact["format"]), item.thread.format)
        routes = sorted(
            {
                row["group_name"]
                for row in memberships
                if row["thread_id"] == tid or row["issue_id"] == item.issue.id
            }
        )
        check("routes", tid, routes[:3], [route.name for route in item.routes])
        check("overflow_routes_count", tid, max(0, len(routes) - 3), item.overflow_routes_count)
        confirmed = [
            row for row in mappings.get(item.issue.id, []) if row["mapping_status"] == "confirmed"
        ]
        volume_ids = {_volume(row["mapping_metadata"]) for row in confirmed}
        volume_ids.discard(None)
        if len(volume_ids) != 1:
            check("reader.progress_scope", tid, "thread", item.reader.progress_scope.value)
            check("reader.read_count", tid, fact["read_count"], item.reader.read_count)
            check("reader.issue_count", tid, fact["issue_count"] or None, item.reader.issue_count)
            continue
        volume_id = next(iter(volume_ids))
        check(
            "identity.canonical_series_id", tid, str(volume_id), item.identity.canonical_series_id
        )
        check(
            "reader.progress_scope", tid, "canonical_series_run", item.reader.progress_scope.value
        )
        rows = [row for row in analytics if row["volume_id"] == volume_id]
        effective: dict[int, tuple[datetime, float]] = {}
        for row in rows:
            if row["rating"] is not None and row["rated_at"] is not None:
                candidate = (row["rated_at"], row["rating"])
                if row["issue_id"] not in effective or candidate > effective[row["issue_id"]]:
                    effective[row["issue_id"]] = candidate
        ratings = sorted(effective.values())
        check(
            "reader.read_count", tid, len({row["issue_id"] for row in rows}), item.reader.read_count
        )
        check("reader.rating_count", tid, len(ratings), item.reader.rating_count)
        check(
            "reader.latest_rating",
            tid,
            ratings[-1][1] if ratings else None,
            item.reader.latest_rating,
        )
        average = round(sum(value for _, value in ratings) / len(ratings), 2) if ratings else None
        check("reader.average_rating", tid, average, item.reader.average_rating)
        run_length = catalog[volume_id]["issue_count"] if volume_id in catalog else None
        if run_length is None:
            for mapping in series.get(tid, []):
                metadata = mapping["metadata"] or {}
                count = metadata.get("count_of_issues")
                if mapping["status"] == "confirmed" and mapping["external_id"] == str(volume_id):
                    if isinstance(count, int) and not isinstance(count, bool):
                        run_length = count
                        break
        check("reader.issue_count", tid, run_length, item.reader.issue_count)
    expected_last = dict(latest) if latest is not None else None
    actual_last = last_read.model_dump() if last_read is not None else None
    check("last_read", None, expected_last, actual_last)
    return ParityReport(len(items), (perf_counter() - started) * 1000, tuple(differences))
