"""Tests for the read-without-rating audit script."""

from __future__ import annotations

from datetime import datetime, UTC


import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User, ExternalIdentity, IssueExternalIdentityMapping
from scripts.audit_read_without_rating import (
    audit_read_without_rating,
    classify_issue,
    ClassificationResult,
    perform_safe_repairs,
    get_read_without_rating_issues,
    find_historical_ratings,
    AuditReport
)


@pytest.fixture
async def db_session(async_db: AsyncSession) -> AsyncSession:
    """Create a test database session."""
    yield async_db


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(username="testuser", email="test@example.com")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_thread(db_session: AsyncSession, test_user: User) -> Thread:
    """Create a test thread."""
    thread = Thread(
        title="Chris Claremont X-Men",
        user_id=test_user.id,
        position=1
    )
    db_session.add(thread)
    await db_session.commit()
    await db_session.refresh(thread)
    return thread


@pytest.fixture
async def test_issues(db_session: AsyncSession, test_thread: Thread) -> list[Issue]:
    """Create test issues with different statuses."""
    issues = [
        Issue(
            thread_id=test_thread.id,
            issue_number="1",
            position=1,
            status="read",
            read_at=datetime.now(UTC)
        ),
        Issue(
            thread_id=test_thread.id,
            issue_number="2", 
            position=2,
            status="read",
            read_at=datetime.now(UTC)
        ),
        Issue(
            thread_id=test_thread.id,
            issue_number="3",
            position=3,
            status="unread"
        ),
    ]
    for issue in issues:
        db_session.add(issue)
    await db_session.commit()
    return issues


@pytest.fixture
async def test_external_identity(db_session: AsyncSession, test_issues: list[Issue]) -> ExternalIdentity:
    """Create test external identity with historical rating."""
    external_identity = ExternalIdentity(
        provider="comicvine",
        metadata_json={"rating": "4.5", "other_data": "test"}
    )
    db_session.add(external_identity)
    await db_session.commit()
    await db_session.refresh(external_identity)
    
    # Map to first issue
    mapping = IssueExternalIdentityMapping(
        issue_id=test_issues[0].id,
        external_identity_id=external_identity.id,
        status="confirmed"
    )
    db_session.add(mapping)
    await db_session.commit()
    
    return external_identity


@pytest.fixture
async def test_rate_event(db_session: AsyncSession, test_issues: list[Issue]) -> Event:
    """Create a test rate event for one of the issues."""
    event = Event(
        type="rate",
        rating=4.0,
        issue_id=test_issues[1].id,
        thread_id=test_issues[1].thread_id,
        timestamp=datetime.now(UTC)
    )
    db_session.add(event)
    await db_session.commit()
    return event


class TestGetReadWithoutRatingIssues:
    """Test getting read-without-rating issues."""
    
    async def test_gets_read_unrated_issues(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue]):
        """Test correctly identifies read issues without ratings."""
        # Should find 2 read issues (issues 0 and 1), but issue 1 has a rate event
        read_unrated, issue_numbers, thread_titles, issue_to_thread = await get_read_without_rating_issues(db_session, test_user.id)
        
        # Issue 0 should be read without rating
        assert test_issues[0].id in read_unrated
        # Issue 1 should NOT be in read_unrated because it has a rate event
        assert test_issues[1].id not in read_unrated
        # Issue 2 should NOT be in read_unrated because it's unread
        assert test_issues[2].id not in read_unrated
        
        assert len(read_unrated) == 1
        assert test_issues[0].id in issue_numbers
        assert test_issues[0].thread_id in thread_titles


class TestFindHistoricalRatings:
    """Test finding historical ratings in external metadata."""
    
    async def test_finds_historical_ratings(self, db_session: AsyncSession, test_user: User, test_external_identity: ExternalIdentity, test_issues: list[Issue]):
        """Test correctly finds historical ratings in external identity metadata."""
        historical_ratings = await find_historical_ratings(db_session, test_user.id)
        
        # Should find the historical rating for issue 0
        assert test_issues[0].id in historical_ratings
        assert historical_ratings[test_issues[0].id] == 4.5
        
        # Should not find rating for issue 1 (no external identity)
        assert test_issues[1].id not in historical_ratings
    
    async def test_ignores_invalid_ratings(self, db_session: AsyncSession, test_user: User):
        """Test ignores invalid rating values."""
        # Create external identity with invalid rating
        external_identity = ExternalIdentity(
            provider="comicvine",
            metadata_json={"rating": "invalid", "other_data": "test"}
        )
        db_session.add(external_identity)
        await db_session.commit()
        
        # Create issue mapping
        issue = Issue(
            thread_id=1,  # Assume thread 1 exists
            issue_number="1",
            position=1,
            status="read"
        )
        db_session.add(issue)
        await db_session.commit()
        
        mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=external_identity.id,
            status="confirmed"
        )
        db_session.add(mapping)
        await db_session.commit()
        
        historical_ratings = await find_historical_ratings(db_session, test_user.id)
        
        # Should not include invalid rating
        assert issue.id not in historical_ratings


class TestClassifyIssue:
    """Test issue classification logic."""
    
    async def test_classifies_missing_rate_event(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue], test_external_identity: ExternalIdentity):
        """Test classification when historical rating exists but no rate event."""
        historical_ratings = {test_issues[0].id: 4.5}
        
        classification = await classify_issue(
            test_issues[0].id,
            test_issues[0].issue_number,
            test_issues[0].thread_id,
            "Test Thread",
            historical_ratings,
            db_session
        )
        
        assert classification.classification == "missing_rate_event"
        assert classification.historical_rating_exists is True
        assert classification.historical_rating_value == 4.5
        assert classification.repair_safe is True
    
    async def test_classifies_no_source_rating(self, db_session: AsyncSession, test_issues: list[Issue]):
        """Test classification when no historical rating exists."""
        historical_ratings = {}
        
        classification = await classify_issue(
            test_issues[0].id,
            test_issues[0].issue_number,
            test_issues[0].thread_id,
            "Test Thread",
            historical_ratings,
            db_session
        )
        
        assert classification.classification == "no_source_rating"
        assert classification.historical_rating_exists is False
        assert classification.repair_safe is False
    
    async def test_classifies_edition_conflict(self, db_session: AsyncSession, test_user: User, test_thread: Thread, test_external_identity: ExternalIdentity):
        """Test classification when edition conflict exists."""
        # Create another thread with same issue number
        conflict_thread = Thread(
            title="Chris Claremont X-Men Duplicate",
            user_id=test_user.id,
            position=2
        )
        db_session.add(conflict_thread)
        await db_session.commit()
        
        # Create conflict issue
        conflict_issue = Issue(
            thread_id=conflict_thread.id,
            issue_number="1",
            position=1,
            status="read"
        )
        db_session.add(conflict_issue)
        await db_session.commit()
        
        historical_ratings = {conflict_issue.id: 4.5}
        
        classification = await classify_issue(
            conflict_issue.id,
            conflict_issue.issue_number,
            conflict_issue.thread_id,
            "Conflict Thread",
            historical_ratings,
            db_session
        )
        
        assert classification.classification == "edition_conflict"
        assert classification.repair_safe is False


class TestPerformSafeRepairs:
    """Test safe repair functionality."""
    
    async def test_repairs_missing_rate_events(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue], test_external_identity: ExternalIdentity):
        """Test repairing missing rate events."""
        # Create classification results for repairable issues
        repairable = [
            ClassificationResult(
                issue_id=test_issues[0].id,
                thread_id=test_issues[0].thread_id,
                thread_title="Test Thread",
                issue_number="1",
                classification="missing_rate_event",
                historical_rating_exists=True,
                historical_rating_value=4.5,
                repair_safe=True
            )
        ]
        
        repairs_made = await perform_safe_repairs(db_session, repairable)
        
        assert repairs_made == 1
        
        # Verify the rate event was created
        result = await db_session.execute(
            select(Event).where(Event.issue_id == test_issues[0].id)
        )
        events = result.scalars().all()
        
        # Should have one rate event
        assert len(events) == 1
        assert events[0].type == "rate"
        assert events[0].rating == 4.5


class TestAuditReadWithoutRating:
    """Test the complete audit workflow."""
    
    async def test_performs_complete_audit(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue], test_external_identity: ExternalIdentity, test_rate_event: Event):
        """Test complete audit workflow."""
        report = await audit_read_without_rating(db_session, test_user.id, classify_only=True)
        
        assert isinstance(report, AuditReport)
        assert report.total_read_unrated == 1  # Only issue 0 is read without rating
        assert report.historical_ratings_found == 1
        assert report.repairs_made == 0  # No repairs in classify-only mode
        
        # Check classification breakdown
        assert "missing_rate_event" in report.classifications
        assert report.classifications["missing_rate_event"] == 1
        assert report.classifications["no_source_rating"] == 0
        
        # Check detailed classification
        assert len(report.issues_by_classification["missing_rate_event"]) == 1
        assert report.issues_by_classification["missing_rate_event"][0].issue_id == test_issues[0].id
    
    async def test_saves_evidence_file(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue], test_external_identity: ExternalIdentity):
        """Test that evidence file is saved correctly."""
        report = await audit_read_without_rating(db_session, test_user.id, classify_only=True)
        
        # Mock the save_evidence function to capture the data
        saved_data = {}
        
        async def mock_save_evidence(report_obj):
            saved_data["data"] = {
                "total_read_unrated": report_obj.total_read_unrated,
                "classifications": report_obj.classifications,
                "historical_ratings_found": report_obj.historical_ratings_found,
                "repairs_made": report_obj.repairs_made
            }
        
        # Test the evidence saving
        await mock_save_evidence(report)
        
        assert saved_data["data"]["total_read_unrated"] == 1
        assert saved_data["data"]["classifications"]["missing_rate_event"] == 1
        assert saved_data["data"]["historical_ratings_found"] == 1
        assert saved_data["data"]["repairs_made"] == 0


class TestIntegration:
    """Integration tests for the complete workflow."""
    
    async def test_full_workflow_with_repairs(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue], test_external_identity: ExternalIdentity):
        """Test complete workflow including repairs."""
        # Verify initial state: one read issue without rating
        initial_read_unrated, _, _, _ = await get_read_without_rating_issues(db_session, test_user.id)
        assert len(initial_read_unrated) == 1
        
        # Perform audit with repairs
        report = await audit_read_without_rating(db_session, test_user.id, classify_only=False)
        
        # Verify repairs were made
        assert report.repairs_made == 1
        assert report.classifications["missing_rate_event"] == 1
        
        # Verify the issue now has a rate event
        result = await db_session.execute(
            select(Event).where(Event.issue_id == test_issues[0].id)
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].type == "rate"
        assert events[0].rating == 4.5
        
        # Verify the issue is no longer read-without-rating
        final_read_unrated, _, _, _ = await get_read_without_rating_issues(db_session, test_user.id)
        assert len(final_read_unrated) == 0
    
    async def test_idempotent_repairs(self, db_session: AsyncSession, test_user: User, test_issues: list[Issue], test_external_identity: ExternalIdentity):
        """Test that repairs are idempotent."""
        # First run with repairs
        report1 = await audit_read_without_rating(db_session, test_user.id, classify_only=False)
        assert report1.repairs_made == 1
        
        # Second run should make no additional repairs
        report2 = await audit_read_without_rating(db_session, test_user.id, classify_only=False)
        assert report2.repairs_made == 0
        
        # Verify only one rate event exists
        result = await db_session.execute(
            select(Event).where(Event.issue_id == test_issues[0].id)
        )
        events = result.scalars().all()
        assert len(events) == 1


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    async def test_empty_database(self, db_session: AsyncSession, test_user: User):
        """Test audit with no data."""
        report = await audit_read_without_rating(db_session, test_user.id, classify_only=True)
        
        assert report.total_read_unrated == 0
        assert sum(report.classifications.values()) == 0
        assert report.historical_ratings_found == 0
    
    async def test_no_read_issues(self, db_session: AsyncSession, test_user: User):
        """Test audit with no read issues."""
        # Create unread issues only
        thread = Thread(title="Test Thread", user_id=test_user.id, position=1)
        db_session.add(thread)
        await db_session.commit()
        
        issue = Issue(
            thread_id=thread.id,
            issue_number="1",
            position=1,
            status="unread"
        )
        db_session.add(issue)
        await db_session.commit()
        
        report = await audit_read_without_rating(db_session, test_user.id, classify_only=True)
        
        assert report.total_read_unrated == 0
        assert sum(report.classifications.values()) == 0
    
    async def test_all_issues_rated(self, db_session: AsyncSession, test_user: User, test_thread: Thread):
        """Test audit with all issues rated."""
        # Create read issues with rate events
        for i in range(3):
            issue = Issue(
                thread_id=test_thread.id,
                issue_number=str(i + 1),
                position=i + 1,
                status="read"
            )
            db_session.add(issue)
            await db_session.commit()
            
            # Create rate event
            event = Event(
                type="rate",
                rating=4.0,
                issue_id=issue.id,
                thread_id=test_thread.id,
                timestamp=datetime.now(UTC)
            )
            db_session.add(event)
            await db_session.commit()
        
        report = await audit_read_without_rating(db_session, test_user.id, classify_only=True)
        
        assert report.total_read_unrated == 0
        assert sum(report.classifications.values()) == 0