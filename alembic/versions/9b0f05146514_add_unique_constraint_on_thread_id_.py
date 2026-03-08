"""add unique constraint on thread_id issue_number.

Revision ID: 9b0f05146514
Revises: f616f65e0f1f
Create Date: 2026-03-08 11:27:33.001449

"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9b0f05146514"
down_revision: str | Sequence[str] | None = "f616f65e0f1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TEMP TABLE issue_dedup_map ON COMMIT DROP AS
        WITH ranked_issues AS (
            SELECT
                id AS duplicate_id,
                thread_id,
                issue_number,
                MIN(id) OVER (PARTITION BY thread_id, issue_number) AS keeper_id,
                ROW_NUMBER() OVER (PARTITION BY thread_id, issue_number ORDER BY id) AS duplicate_rank
            FROM issues
        )
        SELECT duplicate_id, thread_id, issue_number, keeper_id
        FROM ranked_issues
        WHERE duplicate_rank > 1
    """)

    op.execute("""
        UPDATE threads
        SET next_unread_issue_id = issue_dedup_map.keeper_id
        FROM issue_dedup_map
        WHERE threads.next_unread_issue_id = issue_dedup_map.duplicate_id
    """)

    op.execute("""
        UPDATE sessions
        SET pending_issue_id = issue_dedup_map.keeper_id
        FROM issue_dedup_map
        WHERE sessions.pending_issue_id = issue_dedup_map.duplicate_id
    """)

    op.execute("""
        UPDATE events
        SET issue_id = issue_dedup_map.keeper_id
        FROM issue_dedup_map
        WHERE events.issue_id = issue_dedup_map.duplicate_id
    """)

    op.execute("""
        WITH remapped_dependencies AS (
            SELECT
                dependencies.id,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        COALESCE(source_map.keeper_id, dependencies.source_issue_id),
                        COALESCE(target_map.keeper_id, dependencies.target_issue_id)
                    ORDER BY dependencies.id
                ) AS duplicate_rank
            FROM dependencies
            LEFT JOIN issue_dedup_map AS source_map
                ON source_map.duplicate_id = dependencies.source_issue_id
            LEFT JOIN issue_dedup_map AS target_map
                ON target_map.duplicate_id = dependencies.target_issue_id
            WHERE dependencies.source_issue_id IS NOT NULL
              AND dependencies.target_issue_id IS NOT NULL
        )
        DELETE FROM dependencies
        WHERE id IN (
            SELECT id
            FROM remapped_dependencies
            WHERE duplicate_rank > 1
        )
    """)

    op.execute("""
        UPDATE dependencies
        SET source_issue_id = issue_dedup_map.keeper_id
        FROM issue_dedup_map
        WHERE dependencies.source_issue_id = issue_dedup_map.duplicate_id
    """)

    op.execute("""
        UPDATE dependencies
        SET target_issue_id = issue_dedup_map.keeper_id
        FROM issue_dedup_map
        WHERE dependencies.target_issue_id = issue_dedup_map.duplicate_id
    """)

    op.execute("""
        DELETE FROM issues
        USING issue_dedup_map
        WHERE issues.id = issue_dedup_map.duplicate_id
    """)

    op.execute("""
        WITH affected_threads AS (
            SELECT DISTINCT thread_id
            FROM issue_dedup_map
        ),
        thread_counts AS (
            SELECT
                affected_threads.thread_id,
                COUNT(issues.id) AS total_issues,
                COUNT(issues.id) FILTER (WHERE issues.status = 'unread') AS unread_issues,
                (
                    SELECT next_issue.id
                    FROM issues AS next_issue
                    WHERE next_issue.thread_id = affected_threads.thread_id
                      AND next_issue.status = 'unread'
                    ORDER BY next_issue.position, next_issue.id
                    LIMIT 1
                ) AS next_unread_issue_id
            FROM affected_threads
            LEFT JOIN issues
                ON issues.thread_id = affected_threads.thread_id
            GROUP BY affected_threads.thread_id
        )
        UPDATE threads
        SET total_issues = CASE
                WHEN threads.total_issues IS NULL THEN threads.total_issues
                ELSE thread_counts.total_issues
            END,
            issues_remaining = CASE
                WHEN threads.total_issues IS NULL THEN threads.issues_remaining
                ELSE thread_counts.unread_issues
            END,
            next_unread_issue_id = CASE
                WHEN threads.total_issues IS NULL THEN threads.next_unread_issue_id
                ELSE thread_counts.next_unread_issue_id
            END,
            reading_progress = CASE
                WHEN threads.total_issues IS NULL THEN threads.reading_progress
                WHEN thread_counts.total_issues = 0 THEN 'completed'
                WHEN thread_counts.unread_issues = thread_counts.total_issues THEN 'not_started'
                WHEN thread_counts.unread_issues = 0 THEN 'completed'
                ELSE 'in_progress'
            END,
            status = CASE
                WHEN threads.total_issues IS NULL THEN threads.status
                WHEN thread_counts.unread_issues = 0 AND thread_counts.total_issues > 0
                    THEN 'completed'
                ELSE threads.status
            END
        FROM thread_counts
        WHERE threads.id = thread_counts.thread_id
    """)

    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.drop_index("ix_issue_thread_number")
        batch_op.create_unique_constraint(
            "uq_issue_thread_number",
            ["thread_id", "issue_number"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.drop_constraint("uq_issue_thread_number", type_="unique")
        batch_op.create_index("ix_issue_thread_number", ["thread_id", "issue_number"], unique=False)
