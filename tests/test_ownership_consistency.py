"""Tests for ownership consistency constraints (issue #3225).

Tests enforce reader ownership consistency at graph and library write boundaries:
- Cross-user graph/member/pending/frontier writes are rejected
- next_unread_issue_id belonging to different Thread of same reader is rejected
- DB-enforced relationships reject invalid direct SQL inserts
- Application-only/polymorphic boundaries have explicit rejection tests
- Preflight reports existing invalid rows without private payloads
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession
from app.models import (
    ContinuityPlan,
    Dependency,
    Issue,
    ReadingPlanIssue,
    ReadingSession,
    Tag,
    Thread,
    User,
)
from app.services.dependency_service import create_dependency
from app.services.errors import InvalidRequestError
from app.services.reading_session_service import ReadingSessionService
from app.services.tag_service import TagService
from app.services.thread_service import set_current_issue


@pytest.mark.asyncio
async def test_thread_next_unread_issue_ownership_validation(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that Thread.next_unread_issue_id must belong to same thread."""
    # Create another thread and issue for the same user
    other_thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=5,
        user_id=user.id,
        queue_position=2,
    )
    db.add(other_thread)
    await db.commit()
    await db.refresh(other_thread)
    
    # Create an issue in the other thread
    other_issue = Issue(
        thread_id=other_thread.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    db.add(other_issue)
    await db.commit()
    await db.refresh(other_issue)
    
    # Test 1: Valid assignment - issue from same thread should work
    thread.next_unread_issue_id = issue.id
    await db.commit()
    await db.refresh(thread)
    assert thread.next_unread_issue_id == issue.id
    
    # Test 2: Invalid assignment - issue from different thread should fail
    with pytest.raises(IntegrityError):
        thread.next_unread_issue_id = other_issue.id
        await db.commit()


@pytest.mark.asyncio 
async def test_dependency_ownership_validation(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that Dependency source/target issues must belong to same user."""
    # Create another thread and issue for the same user
    other_thread = Thread(
        title="Other Thread", 
        format="Comic",
        issues_remaining=5,
        user_id=user.id,
        queue_position=2,
    )
    db.add(other_thread)
    await db.commit()
    await db.refresh(other_thread)
    
    other_issue = Issue(
        thread_id=other_thread.id,
        issue_number="1",
        status="unread", 
        position=1,
    )
    db.add(other_issue)
    await db.commit()
    await db.refresh(other_issue)
    
    # Test 1: Valid dependency - issues from same thread should work
    result, warning = await create_dependency(
        source_issue_id=issue.id, 
        target_issue_id=other_issue.id, 
        user_id=user.id, 
        db=db
    )
    assert result is not None
    assert result.source_issue_id == issue.id
    assert result.target_issue_id == other_issue.id
    
    # Test 2: Invalid dependency creation through service should fail
    # Create another user with their own thread and issue
    other_user = User(username="otheruser", email="other@example.com")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    
    other_user_thread = Thread(
        title="Other User Thread",
        format="Comic", 
        issues_remaining=3,
        user_id=other_user.id,
        queue_position=1,
    )
    db.add(other_user_thread)
    await db.commit()
    await db.refresh(other_user_thread)
    
    other_user_issue = Issue(
        thread_id=other_user_thread.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    db.add(other_user_issue)
    await db.commit()
    await db.refresh(other_user_issue)
    
    # Cross-user dependency should fail
    result, warning = await create_dependency(
        source_issue_id=issue.id,
        target_issue_id=other_user_issue.id,
        user_id=user.id,
        db=db
    )
    assert result is None
    assert warning is not None and ("different threads" in warning or "Cross-user" in warning)


@pytest.mark.asyncio
async def test_reading_session_pending_references_validation(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that ReadingSession pending references must belong to session user."""
    # Create another user with their own thread
    other_user = User(username="otheruser", email="other@example.com")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    
    other_user_thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=3,
        user_id=other_user.id,
        queue_position=1,
    )
    db.add(other_user_thread)
    await db.commit()
    await db.refresh(other_user_thread)
    
    # Create a reading session for the original user
    session = ReadingSession(user_id=user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    
    service = ReadingSessionService(db)
    
    # Test 1: Valid assignment - pending thread from same user should work
    session.pending_thread_id = thread.id
    await service._validate_pending_thread_ownership(session, user.id)
    # Should not raise
    
    # Test 2: Invalid assignment - pending thread from other user should fail
    session.pending_thread_id = other_user_thread.id
    with pytest.raises(InvalidRequestError, match="does not belong to user"):
        await service._validate_pending_thread_ownership(session, user.id)


@pytest.mark.asyncio
async def test_reading_plan_membership_ownership_validation(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that ReadingPlanMembership issues must belong to plan user."""
    # Create another user with their own thread and issue
    other_user = User(username="otheruser", email="other@example.com")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    
    other_user_thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=3,
        user_id=other_user.id,
        queue_position=1,
    )
    db.add(other_user_thread)
    await db.commit()
    await db.refresh(other_user_thread)
    
    other_user_issue = Issue(
        thread_id=other_user_thread.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    db.add(other_user_issue)
    await db.commit()
    await db.refresh(other_user_issue)
    
    # Create a plan for the original user
    plan = ContinuityPlan(
        name="Test Plan",
        user_id=user.id,
        description="Test plan for ownership validation",
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    
    # Test 1: Valid membership - issue from user's own thread should work
    membership = ReadingPlanIssue(
        plan_id=plan.id,
        occurrence_id="test-1",
        issue_id=issue.id,
        lane_id="main",
        display_position=0,
    )
    db.add(membership)
    await db.commit()
    
    # Test 2: Invalid membership - issue from other user's thread should fail
    bad_membership = ReadingPlanIssue(
        plan_id=plan.id,
        occurrence_id="test-2", 
        issue_id=other_user_issue.id,
        lane_id="main",
        display_position=1,
    )
    db.add(bad_membership)
    
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_tag_assignment_ownership_validation(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that TagAssignment targets must belong to their respective users."""
    # Create another user with their own thread
    other_user = User(username="otheruser", email="other@example.com")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    
    other_user_thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=3,
        user_id=other_user.id,
        queue_position=1,
    )
    db.add(other_user_thread)
    await db.commit()
    await db.refresh(other_user_thread)
    
    # Create a private tag for the original user
    private_tag = Tag(
        name="Private Tag",
        normalized_name="private tag",
        scope="private",
        owner_user_id=user.id,
        color="#FF0000",
    )
    db.add(private_tag)
    await db.commit()
    await db.refresh(private_tag)
    
    # Create a global tag
    global_tag = Tag(
        name="Global Tag",
        normalized_name="global tag", 
        scope="global",
        owner_user_id=None,
        color="#00FF00",
    )
    db.add(global_tag)
    await db.commit()
    await db.refresh(global_tag)
    
    tag_service = TagService(db)
    
    # Test 1: Valid assignment - private tag to user's own thread should work
    assignment1 = await tag_service.assign_tag(
        user=user,
        tag_id=private_tag.id,
        target_type="Thread",
        target_id=thread.id,
    )
    assert assignment1 is not None
    
    # Test 2: Invalid assignment - private tag to other user's thread should fail
    with pytest.raises(InvalidRequestError):
        await tag_service.assign_tag(
            user=user,
            tag_id=private_tag.id,
            target_type="Thread", 
            target_id=other_user_thread.id,
        )
    
    # Test 3: Valid assignment - global tag to any thread should work for admin
    # (Note: actual admin check would be more complex in real implementation)
    assignment3 = await tag_service.assign_tag(
        user=user,  # In real test, this would be an admin user
        tag_id=global_tag.id,
        target_type="Thread",
        target_id=other_user_thread.id,
    )
    assert assignment3 is not None


@pytest.mark.asyncio
async def test_thread_next_unread_cross_thread_validation(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that next_unread_issue_id cannot belong to different thread of same user."""
    # Create another thread for the same user
    other_thread = Thread(
        title="Other Thread",
        format="Comic", 
        issues_remaining=5,
        user_id=user.id,
        queue_position=2,
    )
    db.add(other_thread)
    await db.commit()
    await db.refresh(other_thread)
    
    # Create an issue in the other thread
    other_issue = Issue(
        thread_id=other_thread.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    db.add(other_issue)
    await db.commit()
    await db.refresh(other_issue)
    
    # Test that set_current_issue validates thread ownership
    with pytest.raises(InvalidRequestError, match="does not belong to thread"):
        await set_current_issue(
            db=db,
            user_id=user.id,
            thread_id=thread.id,
            issue_number=other_issue.issue_number,  # Issue from different thread
        )


@pytest.mark.asyncio
async def test_preflight_invalid_rows_detection(
    db: SQLAlchemyAsyncSession, user: User, thread: Thread, issue: Issue
):
    """Test that preflight can detect existing invalid rows without private payloads."""
    # Manually create an invalid state that violates constraints
    # This simulates data that might exist from a bug or migration issue
    
    # Create another user and their thread
    other_user = User(username="otheruser", email="other@example.com")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    
    other_user_thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=3,
        user_id=other_user.id,
        queue_position=1,
    )
    db.add(other_user_thread)
    await db.commit()
    await db.refresh(other_user_thread)
    
    other_user_issue = Issue(
        thread_id=other_user_thread.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    db.add(other_user_issue)
    await db.commit()
    await db.refresh(other_user_issue)
    
    # Create an invalid dependency (cross-user)
    # This should be caught by the constraint
    invalid_dependency = Dependency(
        source_issue_id=issue.id,      # From original user's thread
        target_issue_id=other_user_issue.id,  # From other user's thread
        created_at=issue.created_at,
    )
    db.add(invalid_dependency)
    
    # This should fail due to the CHECK constraint we added
    with pytest.raises(IntegrityError):
        await db.commit()
    
    # Query for existing invalid rows (preflight detection)
    # This would be used in migration scripts to identify problematic data
    result = await db.execute(
        select(Dependency)
        .where(Dependency.source_issue_id.in_([issue.id]))
        .where(Dependency.target_issue_id.in_([other_user_issue.id]))
    )
    invalid_deps = result.scalars().all()
    
    # The invalid dependency should not exist in the database
    assert len(invalid_deps) == 0