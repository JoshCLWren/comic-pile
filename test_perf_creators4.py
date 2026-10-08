"""Performance test for creator list endpoint with production-scale data."""

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
from app.repositories.creator_summary import load_creator_summary_inputs


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
                print(f"  Created {issue_id} issues...")
    
    await db.commit()
    return user


async def benchmark_load_inputs():
    """Benchmark the load_creator_summary_inputs function directly."""
    async with AsyncSessionLocal() as db:
        await clean_test_data(db)
        
        # Create test data
        print("Creating test data...")
        start = time.perf_counter()
        user = await create_test_data(db, num_threads=200, issues_per_thread=50)
        create_time = time.perf_counter() - start
        print(f"Created {200*50} issues in {create_time:.2f}s")
        
        # Benchmark the load_creator_summary_inputs function directly
        print("\nBenchmarking load_creator_summary_inputs...")
        times = []
        for i in range(3):
            start = time.perf_counter()
            inputs = await load_creator_summary_inputs(db, user.id)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            print(f"  Run {i+1}: {elapsed*1000:.2f}ms, "
                  f"owned_issues={len(inputs.owned_issues)}, "
                  f"ratings={len(inputs.effective_ratings)}, "
                  f"credits={sum(len(v) for v in inputs.issue_creator_credits.values())}")
        
        avg_time = sum(times) / len(times) * 1000
        print(f"\nAverage: {avg_time:.2f}ms")
        print(f"Min: {min(times)*1000:.2f}ms")
        print(f"Max: {max(times)*1000:.2f}ms")


if __name__ == "__main__":
    asyncio.run(benchmark_load_inputs())
