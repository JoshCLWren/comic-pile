"""Keep legacy dependency writes synchronized with continuity rules.

Revision ID: c84400000002
Revises: c84400000001
Create Date: 2026-08-07 08:54:00.000000

The legacy ``dependencies`` table remains an active compatibility API during the
continuity migration.  This database-level bridge makes every insert and update
produce the same issue-to-issue ``item_read`` rule, regardless of which code path
writes the legacy table.  Deletes are handled by the foreign key added in the
preceding migration with ``ON DELETE CASCADE``.

The trigger intentionally makes the legacy representation authoritative for an
edge while compatibility mode is active.  If an equivalent generalized edge
already exists, it is linked to the legacy dependency and normalized to
``item_read`` so the two public APIs cannot disagree about whether the target is
blocked.  Removing this migration restores the pre-trigger behavior without
removing either representation; the preceding migration owns removal of the
backfilled compatibility rows.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84400000002"
down_revision: str | Sequence[str] | None = "c84400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYNC_FUNCTION = "sync_legacy_dependency_to_continuity_rule"
_SYNC_TRIGGER = "trg_sync_legacy_dependency_to_continuity_rule"


def upgrade() -> None:
    """Mirror legacy dependency inserts and updates into continuity rules."""
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {_SYNC_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                source_owner_id integer;
                target_owner_id integer;
            BEGIN
                SELECT thread.user_id
                  INTO source_owner_id
                  FROM issues AS issue
                  JOIN threads AS thread ON thread.id = issue.thread_id
                 WHERE issue.id = NEW.source_issue_id;

                SELECT thread.user_id
                  INTO target_owner_id
                  FROM issues AS issue
                  JOIN threads AS thread ON thread.id = issue.thread_id
                 WHERE issue.id = NEW.target_issue_id;

                IF source_owner_id IS NULL
                   OR target_owner_id IS NULL
                   OR source_owner_id <> target_owner_id THEN
                    RAISE EXCEPTION
                        'legacy dependency % does not reference issues owned by one user',
                        NEW.id;
                END IF;

                -- An UPDATE may move an existing legacy dependency to a new edge.
                -- Remove its old compatibility row before claiming the new edge.
                DELETE FROM continuity_rules
                 WHERE legacy_dependency_id = NEW.id;

                INSERT INTO continuity_rules (
                    user_id,
                    source_type,
                    source_id,
                    target_type,
                    target_id,
                    satisfaction_type,
                    checkpoint_issue_id,
                    legacy_dependency_id,
                    note,
                    created_at,
                    updated_at
                )
                VALUES (
                    source_owner_id,
                    'issue',
                    NEW.source_issue_id,
                    'issue',
                    NEW.target_issue_id,
                    'item_read',
                    NULL,
                    NEW.id,
                    NEW.note,
                    NEW.created_at,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (user_id, source_type, source_id, target_type, target_id)
                DO UPDATE SET
                    satisfaction_type = 'item_read',
                    checkpoint_issue_id = NULL,
                    legacy_dependency_id = EXCLUDED.legacy_dependency_id,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP;

                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_SYNC_TRIGGER}
            AFTER INSERT OR UPDATE OF source_issue_id, target_issue_id, note
            ON dependencies
            FOR EACH ROW
            EXECUTE FUNCTION {_SYNC_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    """Stop future mirroring while leaving both existing data models intact."""
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_SYNC_TRIGGER} ON dependencies"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS {_SYNC_FUNCTION}()"))
