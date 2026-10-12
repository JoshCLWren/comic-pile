"""Refresh stored threads.is_blocked after the Roll-authority cutover (#3512).

Revision ID: c35120000001
Revises: n7c4a1000001
Create Date: 2026-10-12

``c25530000001`` (#3359/#3495) changed Roll blocking to canonical
Dependencies only. Historical ``cbl-order:%`` rows became inert, but that
migration did not recompute the denormalized ``threads.is_blocked`` flag
Roll actually filters on.

This revision runs the set-based equivalent of
``refresh_user_blocked_status`` for every user inside the migration
transaction and logs the per-user changed-row counts. It is idempotent:
a second upgrade (or a re-run of the helper) changes zero rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.services.blocked_flag_refresh import refresh_all_users_blocked_status

revision: str = "c35120000001"
down_revision: str | Sequence[str] | None = "n7c4a1000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recompute every stored ``threads.is_blocked`` flag from canonical edges."""
    bind = op.get_bind()
    changed_by_user = refresh_all_users_blocked_status(bind)
    total = sum(changed_by_user.values())
    print(
        f"[c35120000001] refreshed is_blocked for {len(changed_by_user)} user(s); "
        f"{total} flag(s) changed"
    )
    for user_id, changed in changed_by_user.items():
        print(f"[c35120000001]   user {user_id}: {changed} flag(s) changed")


def downgrade() -> None:
    """No-op: prior denormalized flags cannot be reconstructed.

    The refresh is a projection of live canonical Dependencies. Rolling
    the revision back does not restore the stale pre-cutover flags.
    """
    return
