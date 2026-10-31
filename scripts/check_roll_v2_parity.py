"""Run the read-only Roll v2 parity/performance diagnostic on stored data.

Usage: uv run python -m scripts.check_roll_v2_parity --user-id ID --session-id ID
Use seeded fixtures of the desired size (for example 1, 20, and 100 candidates).
Exit status is nonzero when an independently queried field differs.
"""

import argparse
import asyncio
from dataclasses import asdict
import json
from time import perf_counter

from app.database import AsyncSessionLocal
from app.services.roll_v2_parity import compare_roll_projection
from app.services.roll_v2_projection import get_v2_rollable_projection


async def run(user_id: int, session_id: int, die_size: int) -> int:
    """Measure the projection and independently validate its returned fields.

    Args:
        user_id: Reader whose fixture should be measured.
        session_id: That reader's reading-history session.
        die_size: Maximum candidate pool size.

    Returns:
        Zero on agreement, one when a named mismatch is found.
    """
    async with AsyncSessionLocal() as db:
        await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        started = perf_counter()
        items, last_read, omitted = await get_v2_rollable_projection(
            db,
            user_id=user_id,
            session_id=session_id,
            die_size=die_size,
            excluded_thread_ids=[],
        )
        projection_ms = (perf_counter() - started) * 1000
        report = await compare_roll_projection(
            db,
            user_id=user_id,
            session_id=session_id,
            items=items,
            last_read=last_read,
        )
        print(
            json.dumps(
                {**asdict(report), "projection_ms": projection_ms, "omitted_thread_ids": omitted},
                default=str,
                indent=2,
            )
        )
        await db.rollback()
    return int(bool(report.differences))


def main() -> int:
    """Parse fixture identifiers and run one measured comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--die-size", type=int, default=20)
    args = parser.parse_args()
    return asyncio.run(run(args.user_id, args.session_id, args.die_size))


if __name__ == "__main__":
    raise SystemExit(main())
