"""Bounded demo adapter for unauthenticated sample roll (#2757).

Returns deterministic seeded sample data. No user identity, no session
persistence, no writes to reading history, queue, or rating tables.
"""

from fastapi import APIRouter
from app.schemas.roll import RollResponse

router = APIRouter(tags=["demo"])

# Deterministic seeded sample thread — never mutates DB.
_DEMO_THREAD = RollResponse(
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
    explanation="Demo roll: deterministic seed, no user state.",
)

_DEMO_POOL = [
    {"thread_id": 999, "title": "Sample: The Dark Knight Returns (Demo)", "format": "comic", "issues_remaining": 3, "queue_position": 1},
    {"thread_id": 998, "title": "Sample: Watchmen (Demo)", "format": "trade", "issues_remaining": 1, "queue_position": 2},
]


@router.get("/roll", response_model=RollResponse)
async def demo_roll() -> RollResponse:
    """Single deterministic seeded roll for unauthenticated demo."""
    return _DEMO_THREAD


@router.get("/bootstrap")
async def demo_bootstrap() -> dict:
    """Sample pool for the bounded demo adapter."""
    return {
        "thread_pool": _DEMO_POOL,
        "metadata": {"demo": True, "seeded": True, "persistent": False},
    }
