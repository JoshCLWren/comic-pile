"""Re-refresh stored threads.is_blocked after the read-frontier blocking fix (#3590).

Revision ID: c36800000001
Revises: c32320000001
Create Date: 2026-10-20

``c35120000001`` already ran the all-users ``threads.is_blocked`` refresh on
every deployed database. Its SQL lived in
:mod:`app.services.blocked_flag_refresh`, so widening the canonical blocking
predicate afterwards (a frontier issue that is already ``read`` can no longer
block its thread) does not re-run that revision: the stored flags stay exactly
as the old predicate left them. With ``OPTION_E_ENABLED`` off, Roll and Queue
read the stored flag, so affected threads remain blocked until some other
action happens to refresh them.

This revision runs the same set-based refresh again with the corrected
predicate, so every already-deployed database clears the stale flags on
upgrade. It is idempotent: a second upgrade (or a re-run of the helper)
changes zero rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.services.blocked_flag_refresh import refresh_all_users_blocked_status

revision: str = "c36800000001"
down_revision: str | Sequence[str] | None = "c32320000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recompute every stored ``threads.is_blocked`` flag from canonical edges."""
    bind = op.get_bind()
    changed_by_user = refresh_all_users_blocked_status(bind)
    total = sum(changed_by_user.values())
    print(
        f"[c36800000001] refreshed is_blocked for {len(changed_by_user)} user(s); "
        f"{total} flag(s) changed"
    )
    for user_id, changed in changed_by_user.items():
        print(f"[c36800000001]   user {user_id}: {changed} flag(s) changed")


def downgrade() -> None:
    """No-op: prior denormalized flags cannot be reconstructed.

    The refresh is a projection of live canonical Dependencies. Rolling the
    revision back does not restore the stale pre-fix flags.
    """
    return
