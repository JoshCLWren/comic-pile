"""Performance test with detailed query timing."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, async_engine
from app.models import Event, Issue, Thread, User, ReadingSession
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.revoked_token import RevokedToken
from app.models.password_reset_token import PasswordResetToken
from app.models.user_preferences import UserPreferences
from app.services.creator_list import get_creator_list
from app.repositories.creator_summary import load_creator_summary_inputs, COMICVINE_PROVIDER, CreatorCredit, OwnedIssueSeries, CreatorSummaryInputs
from collections import defaultdict
from app.services.creator_summary import HEADLINE_ROLES


async def clean_test_data(db: AsyncSession):
    """Clean up test data."""
    await db.execute(text("TRUNCATE TABLE issue_external_identity_mappings, external_identities, events, issues, threads, users CASCADE"))
    await db.commit()


async def create_test_data(db: AsyncSession, num_threads: int = 200, issues_per_thread: int = 50) -> User:
    """Create production-scale test data."""
    # Create user
    user = User(username=f"perf_test_{uuid.uuid4().hex[:8]}", created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    await db.refresh(user)
    
    # Create threads and issues with creator credits
    creator_names = [
        "Alan Moore", "Frank Miller", "Neil Gaiman", "Grant Morrison", "Brian K. Vaughan",
        "G. Willow Wilson", "Tom King", "Scott Snyder", "Jonathan Hickman", "Mark Millar",
        "Ed Brubaker", "Matt Fraction", "Jason Aaron", "Kieron Gillen", "Chip Zdarsky",
        "James Tynion IV", "Ram V", "Al Ewing", "Donny Cates", "Geoff Johns",
        "Brian Michael Bendis", "Jeff Lemire", "Rick Remender", "Kelly Sue DeConnick", "Gerry Duggan",
    ]
    roles = ["writer", "artist", "cover", "penciler", "inker", "colorist", "letterer"]
    
    issue_id = 0
    batch_size = 200
    for thread_idx in range(num_threads):
        thread = Thread(
            user_id=user.id,
            title=f"Series {thread_idx}",
            format="Comic",
            issues_remaining=issues_per_thread,
            total_issues=issues_per_thread,
            queue_position=thread_idx + 1,
            status="active",
        )
        db.add(thread)
        await db.flush()
        
        for issue_idx in range(issues_per_thread):
            issue_id += 1
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(issue_idx + 1),
                position=issue_idx + 1,
                status="read",
                read_at=datetime.now(UTC),
            )
            db.add(issue)
            
            # Add creator credits (2-3 creators per issue)
            num_creators = 2 + (issue_idx % 2)
            for c in range(num_creators):
                creator_idx = (thread_idx * 3 + c) % len(creator_names)
                role_idx = (thread_idx + c) % len(roles)
                
                # Use unique external_id per issue/creator combination
                external_id = f"cv-issue-{user.id}-{issue_id}-{c}"
                
                identity = ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id=external_id,
                    metadata_json={
                        "creator_credits": [
                            {
                                "id": creator_idx + 1,
                                "name": creator_names[creator_idx],
                                "role": roles[role_idx]
                            }
                        ]
                    }
                )
                db.add(identity)
                await db.flush()
                
                mapping = IssueExternalIdentityMapping(
                    issue_id=issue.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                    confidence=1.0,
                )
                db.add(mapping)
            
            # Add multiple rating events per issue (to simulate history)
            for r in range(3):
                event = Event(
                    type="rate",
                    thread_id=thread.id,
                    issue_id=issue.id,
                    issue_number=issue.issue_number,
                    rating=3.0 + (issue_idx % 3),
                    timestamp=datetime.now(UTC),
                )
                db.add(event)
            
            if issue_id % batch_size == 0:
                await db.flush()
    
    await db.commit()
    return user


async def benchmark_detailed():
    """Benchmark with detailed timing."""
    async with AsyncSessionLocal() as db:
        await clean_test_data(db)
        
        # Create test data
        print("Creating test data...")
        start = time.perf_counter()
        user = await create_test_data(db, num_threads=200, issues_per_thread=50)
        create_time = time.perf_counter() - start
        print(f"Created {200*50} issues in {create_time:.2f}s")
        
        # Benchmark with detailed timing
        print("\nBenchmarking load_creator_summary_inputs with detailed timing...")
        
        for i in range(3):
            print(f"\n  Run {i+1}:")
            
            # Query 1: Owned issues
            start = time.perf_counter()
            issue_result = await db.execute(
                select(Issue.id, Issue.status, Issue.thread_id, Thread.title, Thread.manual_creator_credits)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Thread.user_id == user.id)
            )
            owned_issues: dict[int, str] = {}
            owned_issue_series: dict[int, OwnedIssueSeries] = {}
            thread_manual_credits: dict[int, list[dict[str, object]]] = {}
            for issue_id, status, thread_id, thread_title, manual_credits in issue_result.all():
                owned_issue_id = int(issue_id)
                owned_issues[owned_issue_id] = str(status)
                owned_issue_series[owned_issue_id] = OwnedIssueSeries(
                    thread_id=int(thread_id),
                    thread_title=str(thread_title),
                )
                thread_id_int = int(thread_id)
                if manual_credits and thread_id_int not in thread_manual_credits:
                    thread_manual_credits[thread_id_int] = manual_credits
            q1_time = time.perf_counter() - start
            print(f"    Query 1 (owned issues): {q1_time*1000:.2f}ms, {len(owned_issues)} issues")
            
            # Query 2: Confirmed creator credits
            start = time.perf_counter()
            metadata_result = await db.execute(
                select(Issue.id, ExternalIdentity.metadata_json)
                .join(Thread, Thread.id == Issue.thread_id)
                .join(
                    IssueExternalIdentityMapping,
                    IssueExternalIdentityMapping.issue_id == Issue.id,
                )
                .join(
                    ExternalIdentity,
                    ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                )
                .where(Thread.user_id == user.id)
                .where(IssueExternalIdentityMapping.status == "confirmed")
                .where(ExternalIdentity.provider == COMICVINE_PROVIDER)
            )
            per_issue_credits: dict[int, dict[tuple[int, tuple[str, ...]], CreatorCredit]] = {}
            issues_with_creator_metadata: set[int] = set()
            for issue_id, metadata in metadata_result.all():
                if not isinstance(metadata, dict):
                    continue
                credits = extract_creator_credits(metadata)
                owned_issue_id = int(issue_id)
                if credits:
                    issues_with_creator_metadata.add(owned_issue_id)
                by_key = per_issue_credits.setdefault(owned_issue_id, {})
                for credit in credits:
                    by_key.setdefault((credit.external_id, credit.roles), credit)
            q2_time = time.perf_counter() - start
            print(f"    Query 2 (creator credits): {q2_time*1000:.2f}ms, {len(per_issue_credits)} issues with credits")
            
            # Query 3: Manual credits (Python)
            start = time.perf_counter()
            for issue_id, series in owned_issue_series.items():
                if issue_id in issues_with_creator_metadata:
                    continue
                manual_credits = thread_manual_credits.get(series.thread_id, [])
                if manual_credits:
                    credits = extract_manual_creator_credits(manual_credits)
                    if credits:
                        issues_with_creator_metadata.add(issue_id)
                        by_key = per_issue_credits.setdefault(issue_id, {})
                        for credit in credits:
                            by_key.setdefault((credit.external_id, credit.roles), credit)
            q3_time = time.perf_counter() - start
            print(f"    Query 3 (manual credits): {q3_time*1000:.2f}ms")
            
            # Query 4: Latest ratings
            start = time.perf_counter()
            rate_result = await db.execute(
                select(Event.issue_id, Event.rating)
                .join(Issue, Issue.id == Event.issue_id)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Thread.user_id == user.id)
                .where(Event.type == "rate")
                .where(Event.issue_id.is_not(None))
                .where(Event.rating.is_not(None))
                .distinct(Event.issue_id)
                .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
            )
            effective_ratings: dict[int, float] = {
                int(issue_id): float(rating) for issue_id, rating in rate_result.all() if issue_id is not None
            }
            q4_time = time.perf_counter() - start
            print(f"    Query 4 (ratings): {q4_time*1000:.2f}ms, {len(effective_ratings)} ratings")
            
            total = q1_time + q2_time + q3_time + q4_time
            print(f"    Total: {total*1000:.2f}ms")


def extract_creator_credits(metadata: dict[str, object]) -> list[CreatorCredit]:
    """Extract deduplicated creator credits from confirmed issue metadata."""
    raw = metadata.get("creator_credits")
    if not isinstance(raw, list):
        return []
    credits: list[CreatorCredit] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        creator_id = _coerce_creator_id(item.get("id"))
        name = item.get("name")
        if creator_id is None or not isinstance(name, str) or not name.strip():
            continue
        role_value = item.get("role")
        roles: tuple[str, ...] = ()
        if role_value is not None:
            parsed = {part.strip() for part in str(role_value).split(",") if part.strip()}
            roles = tuple(sorted(parsed))
        dedupe = (creator_id, roles)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        credits.append(
            CreatorCredit(
                external_id=creator_id,
                roles=roles,
                display_name=name.strip(),
            )
        )
    return credits


def extract_manual_creator_credits(manual_credits: list[dict[str, object]]) -> list[CreatorCredit]:
    """Extract deduplicated creator credits from manual thread metadata."""
    from hashlib import sha256
    MANUAL_CREATOR_ID_BASE = 1_000_000_000
    _MANUAL_ROLE_ALIASES: dict[str, str] = {
        "cover artist": "cover",
        "penciller": "penciler",
    }
    
    def manual_creator_id(name: str) -> int:
        digest = sha256(name.encode("utf-8")).hexdigest()
        return MANUAL_CREATOR_ID_BASE + int(digest, 16) % MANUAL_CREATOR_ID_BASE
    
    def _split_roles(item: dict[str, object]) -> list[str]:
        role_value = item.get("roles")
        if isinstance(role_value, list):
            return [part for part in role_value if isinstance(part, str)]
        if isinstance(role_value, str):
            return role_value.split(",")
        return []
    
    def _normalize_manual_role(role: str) -> str | None:
        normalized = " ".join(role.split()).lower()
        if not normalized:
            return None
        return _MANUAL_ROLE_ALIASES.get(normalized, normalized)
    
    credits: list[CreatorCredit] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    for item in manual_credits:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized_name = " ".join(name.split())
        roles = tuple(
            sorted(
                {
                    role
                    for role in (_normalize_manual_role(part) for part in _split_roles(item))
                    if role is not None
                }
            )
        )
        synthetic_id = manual_creator_id(normalized_name)
        dedupe = (synthetic_id, roles)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        credits.append(
            CreatorCredit(
                external_id=synthetic_id,
                roles=roles,
                display_name=normalized_name,
            )
        )
    return credits


def _coerce_creator_id(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


if __name__ == "__main__":
    asyncio.run(benchmark_detailed())
