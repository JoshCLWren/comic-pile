"""Tests for series mapping commit functionality."""

import pytest
import time
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.catalog import commit_series_mapping
from app.schemas.catalog import SeriesMappingCommitRequest
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from sqlalchemy import select


class TestSeriesMappingCommit:
    """Test cases for the series mapping commit endpoint."""

    @pytest.mark.asyncio
    async def test_commit_series_mapping_success(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test successful commit of series mappings."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create a preview token first (mock this for simplicity)
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        # Make commit request
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-123",
            "approved_row_ids": ["issue:1"]
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["idempotency_key"] == "test-key-123"
        assert len(data["confirmed_issue_ids"]) == 1
        assert 1 in data["confirmed_issue_ids"]
        assert len(data["already_confirmed_issue_ids"]) == 0
        assert len(data["needs_review_issue_ids"]) == 0
        assert len(data["hydration_queued_issue_ids"]) == 1
        assert data["series_mapping"]["provider"] == "comicvine"
        assert data["series_mapping"]["external_id"] == "123"
        assert data["series_mapping"]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_commit_already_confirmed_mapping(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test committing an already confirmed mapping."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create a preview token for already confirmed scenario
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:1,safe_exact_match:0,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        # Make commit request
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-456",
            "approved_row_ids": ["issue:1"]
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["confirmed_issue_ids"]) == 0
        assert len(data["already_confirmed_issue_ids"]) == 1
        assert 1 in data["already_confirmed_issue_ids"]

    @pytest.mark.asyncio
    async def test_commit_expired_token(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test commit with expired token."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create an expired preview token
        expired_time = time.time() - 1  # 1 second ago
        preview_token = (
            f'{{"payload": {{"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            f'"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            f'"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:0,'
            f'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": {expired_time}, '
            f'"expires_at": {expired_time}}}, "signature": "fake_signature"}}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-expired",
            "approved_row_ids": ["issue:1"]
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 409
        assert response.json()["detail"] == "preview_expired"

    @pytest.mark.asyncio
    async def test_commit_invalid_approved_row_format(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test commit with invalid approved row ID format."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-invalid",
            "approved_row_ids": ["invalid:123"]  # Should be "issue:123"
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 422
        assert response.json()["detail"] == "invalid_approved_row"

    @pytest.mark.asyncio
    async def test_commit_confirmed_mapping_conflict(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test commit with conflicting confirmed mappings."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create a conflicting external identity mapping first
        external_identity = ExternalIdentity(
            provider="different_provider",
            entity_type="series", 
            external_id="123",
            metadata_json={}
        )
        async_db.add(external_identity)
        await async_db.flush()
        
        mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=external_identity.id,
            status="confirmed",
            evidence_source="existing_source",
            confidence=1.0
        )
        async_db.add(mapping)
        await async_db.commit()
        
        # Create a preview token
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-conflict",
            "approved_row_ids": ["issue:1"]
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 409
        assert response.json()["detail"] == "confirmed_mapping_conflict"

    @pytest.mark.asyncio
    async def test_commit_invalid_approved_row_not_safe(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test commit with approved row that is not safe_exact_match."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create a preview token for needs_review scenario
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:0,needs_review_ambiguous:1,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-needs-review",
            "approved_row_ids": ["issue:1"]  # This should fail as it's not safe_exact_match
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 422
        assert response.json()["detail"] == "invalid_approved_row"

    @pytest.mark.asyncio
    async def test_commit_multiple_issues(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test commit with multiple approved issues."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create a second issue for testing
        issue2 = await _create_issue(async_db, user.id, thread.id, "2")
        
        # Create a preview token for multiple issues
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1", "2"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:2,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-multiple",
            "approved_row_ids": ["issue:1", "issue:2"]
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["confirmed_issue_ids"]) == 2
        assert 1 in data["confirmed_issue_ids"]
        assert 2 in data["confirmed_issue_ids"]
        assert len(data["hydration_queued_issue_ids"]) == 2

    @pytest.mark.asyncio
    async def test_commit_needs_review_issues_included(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test that needs review issues are properly identified in response."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        # Create a second issue that needs review
        issue2 = await _create_issue(async_db, user.id, thread.id, "2")
        
        # Create a preview token with mixed classifications
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1", "2"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:1,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-needs-review",
            "approved_row_ids": ["issue:1"]  # Only approve the safe one
        }
        
        response = await auth_client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 200
        data = response.json()
        
        # Issue 1 should be confirmed
        assert 1 in data["confirmed_issue_ids"]
        # Issue 2 should be in needs_review
        assert 2 in data["needs_review_issue_ids"]

    @pytest.mark.asyncio
    async def test_commit_unauthorized_request(self, client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test commit without authentication."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        commit_request = {
            "preview_token": preview_token,
            "idempotency_key": "test-key-unauthorized",
            "approved_row_ids": ["issue:1"]
        }
        
        response = await client.post("/api/v1/catalog/series-mappings/commit", json=commit_request)
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_commit_service_layer_direct(self, async_db: AsyncSession, sample_data):
        """Test the service layer function directly."""
        user, thread, issue = sample_data["user"], sample_data["thread"], sample_data["issue"]
        
        preview_token = (
            '{"payload": {"user_id": 1, "provider": "comicvine", "provider_series_external_id": "123", '
            '"origin_issue_id": 1, "scope_key": "exact:1:1", "issue_numbers": ["1"], '
            '"classification_digest": "already_confirmed:0,safe_exact_match:1,needs_review_ambiguous:0,'
            'needs_review_conflict:0,unresolved:0,excluded_special:0", "issued_at": 1700000000, '
            '"expires_at": 1700000600}, "signature": "fake_signature"}'
        )
        
        result = await commit_series_mapping(
            db=async_db,
            user_id=user.id,
            preview_token=preview_token,
            idempotency_key="test-service-key",
            approved_row_ids=["issue:1"]
        )
        
        assert result["idempotency_key"] == "test-service-key"
        assert len(result["confirmed_issue_ids"]) == 1
        assert 1 in result["confirmed_issue_ids"]
        
        # Verify database records were created
        mapping_result = await async_db.execute(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.issue_id == 1
            )
        )
        mapping = mapping_result.scalar_one_or_none()
        assert mapping is not None
        assert mapping.status == "confirmed"
        assert mapping.evidence_source == "user_series_confirmation"


async def _create_issue(db: AsyncSession, user_id: int, thread_id: int, issue_number: str):
    """Helper function to create an issue for testing."""
    from app.models import Issue
    
    issue = Issue(
        user_id=user_id,
        thread_id=thread_id,
        issue_number=issue_number,
        title=f"Test Issue {issue_number}",
        notes=None,
    )
    db.add(issue)
    await db.flush()
    return issue