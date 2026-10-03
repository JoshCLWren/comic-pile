"""Bounded guest demo adapter for the unauthenticated sample roll (#2757).

The demo surface is deliberately read-only and identity-free. It serves a
product-owned deterministic seed so a logged-out visitor can see one
representative Roll moment before signup. It holds no user identity, opens no
database session, and writes nothing to reading history, queue, or rating
tables, so no demo interaction can reach a real account.
"""

from typing import Final

from fastapi import APIRouter

from app.schemas.roll import RollResponse

router = APIRouter(tags=["demo"])

# The product-owned sample roll for the guest demo, drawn from a fixed seed so
# every visitor sees the same moment. It is a fabricated fixture rather than a
# database read: the demo can neither leak nor depend on a real library.
_DEMO_SAMPLE_ROLL: Final[RollResponse] = RollResponse(
    thread_id=999,
    title="Sample: The Dark Knight Returns (Demo)",
    format="comic",
    issues_remaining=3,
    queue_position=1,
    die_size=6,
    result=4,
    offset=0,
    snoozed_count=0,
    issue_id=1001,
    issue_number="#4",
    next_issue_id=1002,
    next_issue_number="#5",
    total_issues=12,
    reading_progress="Late in arc — the final act is building.",
    explanation="Demo roll: seeded sample data, no account state.",
)


@router.get("/roll", response_model=RollResponse)
async def demo_roll() -> RollResponse:
    """Return the single deterministic seeded demo roll.

    Returns:
        A fresh copy of the seeded sample roll. No authentication, database
        session, or persistence is involved, so a guest demo interaction can
        never create library, queue, or reading-history rows.
    """
    return _DEMO_SAMPLE_ROLL.model_copy()
