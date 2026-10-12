"""Tests for catalog backfill functionality."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

from app.models.catalog_backfill import BackfillBatch
from app.models.catalog_commit_receipt import CatalogCommitReceipt
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.repositories.catalog_backfill_repository import (
    create_backfill_batch,
    count_eligible_catalog_links,
    find_eligible_catalog_links,
    count_conflicting_identities_for_user,
    find_conflicting_identities_for_user,
    count_duplicate_physical_issues_for_user,
    find_duplicate_physical_issues_for_user,
    count_already_catalog_linked_issues,
    find_already_catalog_linked_issues,
)
from app.services.catalog_backfill import (
    CatalogBackfillService,
    BackfillPlan,
    BackfillReceipt,
    BackfillStatus,
    LinkEligibility,
)


@pytest.fixture
async def mock_db():
    """Mock database session."""
    return AsyncMock()


@pytest.fixture
def backfill_service(mock_db):
    """Create a backfill service instance."""
    return CatalogBackfillService(mock_db)


class TestBackfillBatch:
    """Test BackfillBatch model."""

    def test_backfill_batch_creation(self):
        """Test creating a backfill batch record."""
        batch = BackfillBatch(
            user_id=1,
            status=BackfillStatus.PENDING,
            start_offset=0,
            end_offset=100,
            fingerprint="test_fingerprint",
            dry_run=True,
            apply_mode=False,
        )
        
        assert batch.user_id == 1
        assert batch.status == BackfillStatus.PENDING
        assert batch.start_offset == 0
        assert batch.end_offset == 100
        assert batch.fingerprint == "test_fingerprint"
        assert batch.dry_run is True
        assert batch.apply_mode is False
        assert batch.eligible_count == 0
        assert batch.conflict_count == 0
        assert batch.duplicate_count == 0
        assert batch.skipped_count == 0


class TestCatalogBackfillRepository:
    """Test catalog backfill repository functions."""

    @pytest.mark.asyncio
    async def test_create_backfill_batch(self, mock_db):
        """Test creating a backfill batch."""
        mock_batch = BackfillBatch(
            id=1,
            user_id=1,
            status=BackfillStatus.PENDING,
            start_offset=0,
            end_offset=100,
            fingerprint="test_fingerprint",
            dry_run=True,
            apply_mode=False,
        )
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        result = await create_backfill_batch(
            mock_db,
            user_id=1,
            status=BackfillStatus.PENDING,
            start_offset=0,
            end_offset=100,
            fingerprint="test_fingerprint",
            dry_run=True,
            apply_mode=False,
        )
        
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()
        assert result.user_id == 1
        assert result.status == BackfillStatus.PENDING

    @pytest.mark.asyncio
    async def test_count_eligible_catalog_links(self, mock_db):
        """Test counting eligible catalog links."""
        # Mock the result scalar
        mock_result = AsyncMock()
        mock_result.scalar_one.return_value = 42
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        count = await count_eligible_catalog_links(mock_db, user_id=1)
        
        assert count == 42
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_eligible_catalog_links(self, mock_db):
        """Test finding eligible catalog links."""
        # Mock result mappings
        mock_result = AsyncMock()
        mock_mappings = [
            {
                "mapping_id": 1,
                "issue_id": 1,
                "external_identity_id": 1,
                "provider": "comicvine",
                "entity_type": "issue",
                "external_id": "123",
                "metadata_json": {"name": "Test Issue"},
                "thread_id": 1,
                "thread_title": "Test Thread",
                "issue_number": "1",
                "issue_status": "unread",
                "issue_read_at": None,
                "issue_position": 1,
            }
        ]
        mock_result.mappings.return_value = mock_mappings
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        links = await find_eligible_catalog_links(mock_db, user_id=1, limit=10, offset=0)
        
        assert len(links) == 1
        assert links[0]["issue_id"] == 1
        assert links[0]["external_identity_id"] == 1
        assert mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_conflicting_identities_for_user(self, mock_db):
        """Test counting conflicting identities for a user."""
        mock_result = AsyncMock()
        mock_result.scalar_one.return_value = 5
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        count = await count_conflicting_identities_for_user(mock_db, user_id=1)
        
        assert count == 5
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_conflicting_identities_for_user(self, mock_db):
        """Test finding conflicting identities for a user."""
        mock_result = AsyncMock()
        mock_mappings = [
            {
                "issue_id": 1,
                "thread_id": 1,
                "thread_title": "Test Thread",
                "issue_number": "1",
                "external_ids": ["123", "456"],
                "distinct_identities": 2,
                "providers": ["comicvine", "another_provider"],
            }
        ]
        mock_result.mappings.return_value = mock_mappings
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        conflicts = await find_conflicting_identities_for_user(mock_db, user_id=1, limit=10, offset=0)
        
        assert len(conflicts) == 1
        assert conflicts[0]["issue_id"] == 1
        assert conflicts[0]["distinct_identities"] == 2
        assert len(conflicts[0]["external_ids"]) == 2

    @pytest.mark.asyncio
    async def test_count_duplicate_physical_issues_for_user(self, mock_db):
        """Test counting duplicate physical issues for a user."""
        mock_result = AsyncMock()
        mock_result.scalar_one.return_value = 3
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        count = await count_duplicate_physical_issues_for_user(mock_db, user_id=1)
        
        assert count == 3
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_duplicate_physical_issues_for_user(self, mock_db):
        """Test finding duplicate physical issues for a user."""
        mock_result = AsyncMock()
        mock_mappings = [
            {
                "external_id": "123",
                "external_identity_id": 1,
                "issue_ids": [1, 2],
                "thread_ids": [1, 2],
                "statuses": ["unread", "read"],
                "issue_details": [
                    {"issue_id": 1, "thread_id": 1, "thread_title": "Thread 1", "issue_number": "1", "status": "unread"},
                    {"issue_id": 2, "thread_id": 2, "thread_title": "Thread 2", "issue_number": "2", "status": "read"},
                ],
            }
        ]
        mock_result.mappings.return_value = mock_mappings
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        duplicates = await find_duplicate_physical_issues_for_user(mock_db, user_id=1, limit=10, offset=0)
        
        assert len(duplicates) == 1
        assert duplicates[0]["external_id"] == "123"
        assert len(duplicates[0]["issue_ids"]) == 2

    @pytest.mark.asyncio
    async def test_count_already_catalog_linked_issues(self, mock_db):
        """Test counting already catalog linked issues."""
        mock_result = AsyncMock()
        mock_result.scalar_one.return_value = 10
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        count = await count_already_catalog_linked_issues(mock_db, user_id=1)
        
        assert count == 10
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_already_catalog_linked_issues(self, mock_db):
        """Test finding already catalog linked issues."""
        mock_result = AsyncMock()
        mock_mappings = [
            {
                "mapping_id": 1,
                "issue_id": 1,
                "external_identity_id": 1,
                "provider": "comicvine",
                "entity_type": "issue",
                "external_id": "123",
                "catalog_issue_id": 1,
                "catalog_linked_at": datetime.now(UTC),
            }
        ]
        mock_result.mappings.return_value = mock_mappings
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        linked = await find_already_catalog_linked_issues(mock_db, user_id=1, limit=10, offset=0)
        
        assert len(linked) == 1
        assert linked[0]["issue_id"] == 1
        assert linked[0]["catalog_issue_id"] == 1


class TestCatalogBackfillService:
    """Test catalog backfill service."""

    @pytest.mark.asyncio
    async def test_generate_plan_fingerprint(self, backfill_service):
        """Test generating a plan fingerprint."""
        fingerprint = backfill_service._generate_plan_fingerprint(1, 0, 100)
        
        assert isinstance(fingerprint, str)
        assert len(fingerprint) == 64  # SHA256 hash length
        assert fingerprint != backfill_service._generate_plan_fingerprint(1, 0, 100)  # Different timestamp

    @pytest.mark.asyncio
    async def test_plan_backfill_batch_dry_run(self, backfill_service, mock_db):
        """Test planning a backfill batch in dry-run mode."""
        # Mock the repository functions
        backfill_service._find_eligible_links = AsyncMock(return_value=[])
        backfill_service._find_conflicts = AsyncMock(return_value=[])
        backfill_service._find_duplicates = AsyncMock(return_value=[])
        backfill_service._find_already_linked = AsyncMock(return_value=[])
        backfill_service._create_backfill_batch = AsyncMock(return_value=1)
        
        plan = await backfill_service.plan_backfill_batch(
            user_id=1,
            batch_size=100,
            start_offset=0,
            dry_run=True,
            apply_mode=False,
        )
        
        assert isinstance(plan, BackfillPlan)
        assert plan.batch_id == 1
        assert plan.user_id == 1
        assert plan.start_offset == 0
        assert plan.dry_run is True
        assert plan.apply_mode is False

    @pytest.mark.asyncio
    async def test_plan_backfill_batch_apply_mode(self, backfill_service, mock_db):
        """Test planning a backfill batch in apply mode."""
        # Mock the repository functions
        backfill_service._find_eligible_links = AsyncMock(return_value=[])
        backfill_service._find_conflicts = AsyncMock(return_value=[])
        backfill_service._find_duplicates = AsyncMock(return_value=[])
        backfill_service._find_already_linked = AsyncMock(return_value=[])
        backfill_service._create_backfill_batch = AsyncMock(return_value=1)
        
        plan = await backfill_service.plan_backfill_batch(
            user_id=1,
            batch_size=100,
            start_offset=0,
            dry_run=False,
            apply_mode=True,
        )
        
        assert isinstance(plan, BackfillPlan)
        assert plan.batch_id == 1
        assert plan.user_id == 1
        assert plan.start_offset == 0
        assert plan.dry_run is False
        assert plan.apply_mode is True

    @pytest.mark.asyncio
    async def test_plan_backfill_batch_invalid_mode(self, backfill_service, mock_db):
        """Test planning a backfill batch with invalid mode."""
        with pytest.raises(ValueError, match="apply_mode must be True when dry_run is False"):
            await backfill_service.plan_backfill_batch(
                user_id=1,
                batch_size=100,
                start_offset=0,
                dry_run=False,
                apply_mode=False,
            )

    @pytest.mark.asyncio
    async def test_execute_backfill_batch_dry_run(self, backfill_service, mock_db):
        """Test executing a backfill batch in dry-run mode."""
        # Create a test plan
        plan = BackfillPlan(
            batch_id=1,
            user_id=1,
            start_offset=0,
            end_offset=100,
            fingerprint="test_fingerprint",
            eligible_links=[],
            skipped_links=[],
            conflicts=[],
            duplicates=[],
        )
        
        # Mock the service methods
        backfill_service._update_backfill_batch_status = AsyncMock()
        backfill_service._create_catalog_link = AsyncMock(return_value={
            "issue_id": 1,
            "external_identity_id": 1,
            "catalog_issue_id": 1,
            "catalog_issue_created": False,
            "catalog_series_created": False,
            "link_created": True,
        })
        backfill_service._create_catalog_commit_receipt = AsyncMock(return_value=MagicMock(id=1))
        backfill_service._update_backfill_batch_status = AsyncMock()
        
        receipt = await backfill_service.execute_backfill_batch(plan)
        
        assert isinstance(receipt, BackfillReceipt)
        assert receipt.batch_id == 1
        assert receipt.user_id == 1
        assert receipt.receipt_id == 1
        assert len(receipt.actual_links) == 0  # Dry run doesn't create actual links

    @pytest.mark.asyncio
    async def test_execute_backfill_batch_apply_mode(self, backfill_service, mock_db):
        """Test executing a backfill batch in apply mode."""
        # Create a test plan with eligible links
        plan = BackfillPlan(
            batch_id=1,
            user_id=1,
            start_offset=0,
            end_offset=100,
            fingerprint="test_fingerprint",
            eligible_links=[
                {
                    "issue_id": 1,
                    "external_identity_id": 1,
                    "provider": "comicvine",
                    "entity_type": "issue",
                    "external_id": "123",
                    "metadata_json": {"name": "Test Issue"},
                    "thread_id": 1,
                    "thread_title": "Test Thread",
                    "issue_number": "1",
                }
            ],
            skipped_links=[],
            conflicts=[],
            duplicates=[],
        )
        
        # Mock the service methods
        backfill_service._update_backfill_batch_status = AsyncMock()
        backfill_service._create_catalog_link = AsyncMock(return_value={
            "issue_id": 1,
            "external_identity_id": 1,
            "catalog_issue_id": 1,
            "catalog_issue_created": True,
            "catalog_series_created": False,
            "link_created": True,
        })
        backfill_service._create_catalog_commit_receipt = AsyncMock(return_value=MagicMock(id=1))
        backfill_service._update_backfill_batch_status = AsyncMock()
        
        receipt = await backfill_service.execute_backfill_batch(plan)
        
        assert isinstance(receipt, BackfillReceipt)
        assert receipt.batch_id == 1
        assert receipt.user_id == 1
        assert receipt.receipt_id == 1
        assert len(receipt.actual_links) == 1
        assert receipt.catalog_issues_created == 1
        assert receipt.links_created == 1

    @pytest.mark.asyncio
    async def test_get_backfill_status(self, backfill_service, mock_db):
        """Test getting backfill status."""
        # Mock the repository functions
        backfill_service._get_backfill_batch = AsyncMock(return_value={
            "id": 1,
            "status": BackfillStatus.COMPLETED,
            "start_offset": 0,
            "end_offset": 100,
            "fingerprint": "test_fingerprint",
            "dry_run": True,
            "apply_mode": False,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        })
        
        status = await backfill_service.get_backfill_status(user_id=1, batch_id=1)
        
        assert status["batch_id"] == 1
        assert status["status"] == BackfillStatus.COMPLETED
        assert status["user_id"] == 1

    @pytest.mark.asyncio
    async def test_rollback_backfill_batch(self, backfill_service, mock_db):
        """Test rolling back a backfill batch."""
        # Mock a receipt
        mock_receipt = MagicMock()
        mock_receipt.id = 1
        mock_receipt.user_id = 1
        mock_receipt.response_json = {
            "actual_links": [
                {
                    "issue_id": 1,
                    "external_identity_id": 1,
                    "catalog_issue_id": 1,
                    "catalog_issue_created": True,
                    "catalog_series_created": False,
                    "link_created": True,
                }
            ]
        }
        
        backfill_service._get_catalog_commit_receipt = AsyncMock(return_value=mock_receipt)
        backfill_service._rollback_catalog_link = AsyncMock(return_value={
            "rolled_back": False,
            "reason": "Catalog issues are shared and cannot be deleted",
        })
        
        result = await backfill_service.rollback_backfill_batch(
            user_id=1,
            receipt_id=1,
        )
        
        assert result["receipt_id"] == 1
        assert result["links_rolled_back"] == 0
        assert result["links_failed"] == 1
        assert len(result["rollback_details"]) == 1

    @pytest.mark.asyncio
    async def test_rollback_backfill_batch_no_receipt(self, backfill_service, mock_db):
        """Test rolling back a backfill batch without receipt ID."""
        with pytest.raises(ValueError, match="Either batch_id or receipt_id must be provided"):
            await backfill_service.rollback_backfill_batch(user_id=1)

    @pytest.mark.asyncio
    async def test_rollback_backfill_batch_wrong_user(self, backfill_service, mock_db):
        """Test rolling back a backfill batch with wrong user ID."""
        # Mock a receipt with different user ID
        mock_receipt = MagicMock()
        mock_receipt.id = 1
        mock_receipt.user_id = 2  # Different user
        backfill_service._get_catalog_commit_receipt = AsyncMock(return_value=mock_receipt)
        
        with pytest.raises(ValueError, match="Receipt 1 does not belong to user 1"):
            await backfill_service.rollback_backfill_batch(
                user_id=1,
                receipt_id=1,
            )


class TestLinkEligibility:
    """Test link eligibility constants."""

    def test_link_eligibility_constants(self):
        """Test that all link eligibility constants are defined."""
        assert LinkEligibility.ELIGIBLE == "eligible"
        assert LinkEligibility.CONFLICTING == "conflicting"
        assert LinkEligibility.AMBIGUOUS == "ambiguous"
        assert LinkEligibility.ALREADY_LINKED == "already_linked"
        assert LinkEligibility.INCOMPATIBLE_TYPE == "incompatible_type"


class TestBackfillStatus:
    """Test backfill status constants."""

    def test_backfill_status_constants(self):
        """Test that all backfill status constants are defined."""
        assert BackfillStatus.PENDING == "pending"
        assert BackfillStatus.PLANNING == "planning"
        assert BackfillStatus.EXECUTING == "executing"
        assert BackfillStatus.COMPLETED == "completed"
        assert BackfillStatus.FAILED == "failed"
        assert BackfillStatus.ROLLED_BACK == "rolled_back"


class TestBackfillPlan:
    """Test BackfillPlan class."""

    def test_backfill_plan_creation(self):
        """Test creating a backfill plan."""
        plan = BackfillPlan(
            batch_id=1,
            user_id=1,
            start_offset=0,
            end_offset=100,
            fingerprint="test_fingerprint",
            eligible_links=[],
            skipped_links=[],
            conflicts=[],
            duplicates=[],
        )
        
        assert plan.batch_id == 1
        assert plan.user_id == 1
        assert plan.start_offset == 0
        assert plan.end_offset == 100
        assert plan.fingerprint == "test_fingerprint"
        assert len(plan.eligible_links) == 0
        assert len(plan.skipped_links) == 0
        assert len(plan.conflicts) == 0
        assert len(plan.duplicates) == 0


class TestBackfillReceipt:
    """Test BackfillReceipt class."""

    def test_backfill_receipt_creation(self):
        """Test creating a backfill receipt."""
        receipt = BackfillReceipt(
            receipt_id=1,
            batch_id=1,
            user_id=1,
            fingerprint="test_fingerprint",
            actual_links=[],
            skipped_links=[],
            conflicts=[],
            duplicates=[],
            catalog_issues_created=0,
            catalog_series_created=0,
            links_created=0,
            execution_time_ms=100,
        )
        
        assert receipt.receipt_id == 1
        assert receipt.batch_id == 1
        assert receipt.user_id == 1
        assert receipt.fingerprint == "test_fingerprint"
        assert len(receipt.actual_links) == 0
        assert len(receipt.skipped_links) == 0
        assert len(receipt.conflicts) == 0
        assert len(receipt.duplicates) == 0
        assert receipt.catalog_issues_created == 0
        assert receipt.catalog_series_created == 0
        assert receipt.links_created == 0
        assert receipt.execution_time_ms == 100