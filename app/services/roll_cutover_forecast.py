"""Read-only Roll forecast after the #3359 canonical Dependency backfill.

Simulates ``c25530000001`` using the migration's own pair selection
(``canonical_backfill._rule_native_pairs`` plus existing canonical
Dependencies), then applies the same blocked-frontier rule as
``comic_pile.dependencies._get_blocked_thread_ids_uncached``. Historical
``cbl-order:%`` rows stay inert. This module never writes.
"""

from __future__ import annotations

from typing import Any, TypedDict

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.services.canonical_backfill import _rule_native_pairs

class FrontierSource(TypedDict):
    """One unread source targeting a queued frontier."""

    source_title: str
    source_number: object
    note: object


class FrontierExplanation(TypedDict):
    """Actual unread prerequisites for one queued thread frontier."""

    thread_id: int
    title: str
    next_unread_issue_id: int | None
    next_number: object
    canonical: list[FrontierSource]
    item_read: list[FrontierSource]
    converged: list[FrontierSource]
    cbl_order_unread: list[FrontierSource]


_QUEUED_SQL = """
SELECT t.id, t.title, t.is_blocked, t.next_unread_issue_id
FROM threads t
WHERE t.user_id = :user_id
  AND t.status = 'active'
  AND t.queue_position >= 1
"""

_CANONICAL_FRONTIER_SQL = """
SELECT DISTINCT t.id
FROM threads t
JOIN dependencies d ON d.target_issue_id = t.next_unread_issue_id
JOIN issues src ON src.id = d.source_issue_id
JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
WHERE t.user_id = :user_id
  AND t.status = 'active'
  AND t.queue_position >= 1
  AND src.status <> 'read'
  AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%')
"""

_ITEM_READ_FRONTIER_SQL = """
SELECT DISTINCT t.id
FROM threads t
JOIN continuity_rules r
  ON r.target_id = t.next_unread_issue_id
 AND r.legacy_dependency_id IS NULL
 AND r.satisfaction_type = 'item_read'
 AND r.source_type = 'issue' AND r.target_type = 'issue'
 AND r.source_id <> r.target_id
JOIN issues src ON src.id = r.source_id
JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
WHERE t.user_id = :user_id
  AND t.status = 'active'
  AND t.queue_position >= 1
  AND src.status <> 'read'
"""

_CONVERGED_FRONTIER_SQL = """
SELECT DISTINCT t.id
FROM threads t
JOIN continuity_rules r
  ON r.target_id = t.next_unread_issue_id
 AND r.legacy_dependency_id IS NULL
 AND r.satisfaction_type = 'converged'
JOIN LATERAL json_array_elements(r.convergence_targets) AS elem ON true
JOIN issues src ON src.id = (elem->>'id')::int
JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
WHERE t.user_id = :user_id
  AND t.status = 'active'
  AND t.queue_position >= 1
  AND (elem->>'id')::int <> r.target_id
  AND src.status <> 'read'
"""


def _id_set(bind: Connection, sql: str, user_id: int) -> set[int]:
    """Return thread ids from one parameterized forecast query."""
    return {int(row[0]) for row in bind.execute(sa.text(sql), {"user_id": user_id}).all()}


def forecast_roll_eligibility(bind: Connection, user_id: int) -> dict[str, Any]:
    """Return before/after Roll buckets for one user after simulated backfill.

    Pair selection matches ``c25530000001`` (native item_read + converged
    pairs union existing canonical Dependencies). Blocked means the queued
    thread's ``next_unread_issue_id`` is the target of an unread source in
    that union. ``cbl-order:%`` rows never block.

    Args:
        bind: Read-only SQLAlchemy connection.
        user_id: Owner whose active queued threads are forecast.

    Returns:
        Counts, exclusive blocking buckets, newly available ids, and newly
        blocked ids. ``rule_native_pair_count`` is the migration pair count.
    """
    queued_rows = list(bind.execute(sa.text(_QUEUED_SQL), {"user_id": user_id}).all())
    queued = {
        int(row[0]): {
            "thread_id": int(row[0]),
            "title": row[1],
            "is_blocked": bool(row[2]),
            "next_unread_issue_id": None if row[3] is None else int(row[3]),
        }
        for row in queued_rows
    }
    canonical = _id_set(bind, _CANONICAL_FRONTIER_SQL, user_id)
    item_read = _id_set(bind, _ITEM_READ_FRONTIER_SQL, user_id)
    converged = _id_set(bind, _CONVERGED_FRONTIER_SQL, user_id)
    blocked_after = canonical | item_read | converged
    eligible_today = {tid for tid, row in queued.items() if not row["is_blocked"]}
    blocked_today = set(queued) - eligible_today
    newly_available = sorted(blocked_today - blocked_after)
    newly_blocked = sorted(eligible_today & blocked_after)
    item_read_only = item_read - canonical
    converged_only = converged - canonical - item_read
    return {
        "user_id": user_id,
        "queued": len(queued),
        "eligible_today": len(eligible_today),
        "blocked_canonical": len(canonical),
        "blocked_item_read_only": len(item_read_only),
        "blocked_converged_only": len(converged_only),
        "blocked_after": len(blocked_after),
        "rollable_after": len(queued) - len(blocked_after),
        "newly_available": newly_available,
        "newly_blocked": newly_blocked,
        "rule_native_pair_count": len(_rule_native_pairs(bind)),
        "threads": queued,
    }


def explain_frontier_prerequisites(
    bind: Connection,
    user_id: int,
    thread_ids: list[int],
) -> list[FrontierExplanation]:
    """Return the actual unread prerequisite for each requested frontier.

    Args:
        bind: Read-only SQLAlchemy connection.
        user_id: Owner.
        thread_ids: Queued thread ids to explain.

    Returns:
        One row per thread with canonical / item_read / converged / cbl-only
        unread sources targeting ``next_unread_issue_id``.
    """
    if not thread_ids:
        return []
    placeholders = ", ".join(f":tid_{index}" for index in range(len(thread_ids)))
    params: dict[str, object] = {"user_id": user_id}
    for index, thread_id in enumerate(thread_ids):
        params[f"tid_{index}"] = thread_id
    rows = bind.execute(
        sa.text(
            "SELECT t.id, t.title, t.next_unread_issue_id, i.issue_number "
            "FROM threads t "
            "LEFT JOIN issues i ON i.id = t.next_unread_issue_id "
            f"WHERE t.user_id = :user_id AND t.id IN ({placeholders}) "
            "ORDER BY t.id"
        ),
        params,
    ).all()
    explained: list[FrontierExplanation] = []
    for thread_id, title, next_id, next_number in rows:
        explained.append(
            {
                "thread_id": int(thread_id),
                "title": str(title),
                "next_unread_issue_id": None if next_id is None else int(next_id),
                "next_number": next_number,
                "canonical": _frontier_sources(
                    bind,
                    user_id=user_id,
                    next_id=next_id,
                    kind="canonical",
                ),
                "item_read": _frontier_sources(
                    bind,
                    user_id=user_id,
                    next_id=next_id,
                    kind="item_read",
                ),
                "converged": _frontier_sources(
                    bind,
                    user_id=user_id,
                    next_id=next_id,
                    kind="converged",
                ),
                "cbl_order_unread": _frontier_sources(
                    bind,
                    user_id=user_id,
                    next_id=next_id,
                    kind="cbl_order",
                ),
            }
        )
    return explained


def _frontier_sources(
    bind: Connection,
    *,
    user_id: int,
    next_id: int | None,
    kind: str,
) -> list[FrontierSource]:
    """Load unread sources of one kind that target a frontier issue."""
    if next_id is None:
        return []
    if kind == "canonical":
        sql = """
            SELECT st.title, src.issue_number, d.note
            FROM dependencies d
            JOIN issues src ON src.id = d.source_issue_id
            JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
            WHERE d.target_issue_id = :next_id AND src.status <> 'read'
              AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%')
            """
    elif kind == "cbl_order":
        sql = """
            SELECT st.title, src.issue_number, d.note
            FROM dependencies d
            JOIN issues src ON src.id = d.source_issue_id
            JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
            WHERE d.target_issue_id = :next_id AND src.status <> 'read'
              AND d.note LIKE 'cbl-order:%'
            """
    elif kind == "item_read":
        sql = """
            SELECT st.title, src.issue_number, r.note
            FROM continuity_rules r
            JOIN issues src ON src.id = r.source_id
            JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
            WHERE r.target_id = :next_id AND src.status <> 'read'
              AND r.legacy_dependency_id IS NULL
              AND r.satisfaction_type = 'item_read'
              AND r.source_type = 'issue' AND r.target_type = 'issue'
              AND r.source_id <> r.target_id
            """
    else:
        sql = """
            SELECT st.title, src.issue_number, r.note
            FROM continuity_rules r
            JOIN LATERAL json_array_elements(r.convergence_targets) AS elem ON true
            JOIN issues src ON src.id = (elem->>'id')::int
            JOIN threads st ON st.id = src.thread_id AND st.user_id = :user_id
            WHERE r.target_id = :next_id AND src.status <> 'read'
              AND r.legacy_dependency_id IS NULL
              AND r.satisfaction_type = 'converged'
              AND (elem->>'id')::int <> r.target_id
            """
    return [
        {"source_title": str(row[0]), "source_number": row[1], "note": row[2]}
        for row in bind.execute(
            sa.text(sql), {"user_id": user_id, "next_id": next_id}
        ).all()
    ]
