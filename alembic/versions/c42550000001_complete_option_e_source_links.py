"""Complete remaining explicit Option E source links without rewriting reading data.

Revision ID: c42550000001
Revises: c42100000001

Migrates legacy-only Reading Plans to newly owned Reading Lists. Previously
linked Plans retain their explicit authority and provenance. Existing
Reading Lists, ratings, Issue status, historical plan membership and source
placements are never modified. This is deliberately additive and idempotent.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "c42550000001"
down_revision = "c42100000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill an owned List and immutable List-source record for every Plan."""
    db = op.get_bind()
    plans = db.execute(text(
        "SELECT p.id, p.user_id, p.name, p.ordering_mode "
        "FROM continuity_plans p ORDER BY p.id"
    )).all()
    for plan_id, user_id, plan_name, ordering_mode in plans:
        linked = db.execute(text(
            "SELECT DISTINCT s.custom_cbl_list_id FROM reading_plan_sources s "
            "WHERE s.plan_id=:p AND s.custom_cbl_list_id IS NOT NULL"
        ), {"p": plan_id}).scalars().all()
        if linked:
            if len(linked) != 1:
                raise RuntimeError(f"Plan {plan_id} has multiple Reading List authorities")
            owned = db.execute(text(
                "SELECT 1 FROM custom_cbl_lists WHERE id=:l AND user_id=:u"
            ), {"l": linked[0], "u": user_id}).scalar()
            if not owned:
                raise RuntimeError(f"Plan {plan_id} references an unowned Reading List")
            continue
        # Always create a new owned List for an unlinked legacy Plan.
        # Never infer authority from names, IDs or overlapping issue sets.
        # A new List keeps the complete legacy issue sequence without touching
        # historical membership/provenance. All presently unlinked plans have
        # at most one populated lane. Fail rather than flatten any new
        # multi-lane plan into an unintended strict sequence.
        lane_count = db.execute(text(
            "SELECT count(DISTINCT lane_id) FROM reading_plan_issues "
            "WHERE plan_id=:p"
        ), {"p": plan_id}).scalar_one()
        if lane_count > 1:
            raise RuntimeError(f"Plan {plan_id} has independent lanes requiring review")
        clash = db.execute(text(
            "SELECT 1 FROM custom_cbl_lists "
            "WHERE user_id=:u AND lower(name)=lower(:n) LIMIT 1"
        ), {"u": user_id, "n": plan_name}).scalar()
        suffix = f" [Plan {plan_id}]"
        name = f"{plan_name[:200 - len(suffix)]}{suffix}" if clash else plan_name
        mode = "strict" if ordering_mode == "strict_sequential" else "loose"
        list_id = db.execute(text(
            "INSERT INTO custom_cbl_lists (user_id,name,mode,created_at,updated_at) "
            "VALUES (:u,:n,:m,now(),now()) RETURNING id"
        ), {"u": user_id, "n": name, "m": mode}).scalar_one()
        db.execute(text(
            "INSERT INTO custom_cbl_entries "
            "(list_id,issue_id,position,gate,skipped,is_checkpoint,created_at) "
            "SELECT :l, ranked.issue_id, ranked.idx,'none',false,ranked.is_checkpoint,now() "
            "FROM (SELECT issue_id,is_checkpoint,"
            " row_number() OVER (ORDER BY display_position,occurrence_id)-1 AS idx "
            " FROM reading_plan_issues WHERE plan_id=:p) ranked"
        ), {"l": list_id, "p": plan_id})

        db.execute(text(
            "INSERT INTO reading_plan_sources "
            "(plan_id,raw_source_path,custom_cbl_list_id,recorded_at) "
            "VALUES (:p,:path,:l,now())"
        ), {"p": plan_id, "l": list_id, "path": f"custom-cbl:{list_id}"})

    # Verify every Plan now resolves to exactly one owned List, including
    # previously empty legacy Plans. Any violation rolls back the migration.
    errors = db.execute(text(
        "SELECT p.id FROM continuity_plans p "
        "LEFT JOIN reading_plan_sources s ON s.plan_id=p.id AND s.custom_cbl_list_id IS NOT NULL "
        "LEFT JOIN custom_cbl_lists l ON l.id=s.custom_cbl_list_id AND l.user_id=p.user_id "
        "GROUP BY p.id HAVING count(DISTINCT l.id) <> 1 "
        "OR count(DISTINCT s.custom_cbl_list_id) <> 1"
    )).scalars().all()
    if errors:
        raise RuntimeError(f"Unconverted/unowned Reading Plans: {errors}")


def downgrade() -> None:
    """Never automatically discard migrated user Reading Lists."""
    raise RuntimeError("Option E source-link backfill is an irreversible data migration")
