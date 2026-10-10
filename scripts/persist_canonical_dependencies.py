#!/usr/bin/env python3
"""Rehearse or apply canonical constraint compilation on an authorized database.

The deployment migration performs the initial cutover. This repair tool uses
exactly the authoring compiler used by plan/rule writes, with no fixed edge
counts, no historical CBL inference, and no implicit commit. Rehearsal is the
default; --apply is required to persist results.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def persist_canonical_constraints(db: AsyncSession) -> int:
    """Compile all users' proven constraints without committing the transaction.

    Args:
        db: Authorized asynchronous database session.

    Returns:
        Number of missing canonical edges inserted. Existing standalone edges,
        read state and frontiers are preserved; historical rows remain inert
        unless independent hard intent explicitly promotes the same pair.
    """
    from app.models.user import User
    from app.services.canonical_constraints import synchronize_canonical_constraints

    user_ids = list((await db.scalars(select(User.id).order_by(User.id))).all())
    inserted = 0
    for user_id in user_ids:
        inserted += await synchronize_canonical_constraints(db, user_id)
    return inserted


async def main(*, apply: bool = False) -> None:
    """Compile constraints and commit only when explicitly invoked with --apply."""
    from importlib import import_module

    # Register the User relationship target in a fresh operator process, where
    # importing auth routers has not already initialized this model.
    import_module("app.models.password_reset_token")
    from app.database import async_engine
    from app.models.user import User
    from comic_pile.dependencies import refresh_user_blocked_status

    async with AsyncSession(async_engine) as db:
        inserted = await persist_canonical_constraints(db)
        user_ids = list((await db.scalars(select(User.id))).all())
        for user_id in user_ids:
            await refresh_user_blocked_status(user_id, db)
        if apply:
            await db.commit()
        else:
            await db.rollback()
        print(
            f"{'Applied' if apply else 'Rehearsed (rolled back)'}: {inserted} missing canonical edges"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(apply=parser.parse_args().apply))
