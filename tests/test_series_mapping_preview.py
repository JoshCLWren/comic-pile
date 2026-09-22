"""Tests for the series mapping preview endpoint."""

import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping


class TestSeriesMappingPreview:
    """Test cases for the series mapping preview endpoint."""

    @pytest.mark.asyncio
    async def test_preview_series_mapping_available_scope(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test preview with available scope (exact match found)."""
        # Create test data
        issue = sample_data["issue"]
        
        # Create a confirmed external identity for the origin issue
        external_identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id="12345",
            external_url="https://comicvine.gamespot.com/issue/4000-12345/",
            metadata_json={"name": "Amazing Spider-Man #1", "issue_number": "1"},
        )
        async_db.add(external_identity)
        await async_db.flush()

        # Create a confirmed mapping
        mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=external_identity.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
        async_db.add(mapping)
        await async_db.commit()
        
        # Mock the ComicVine client to return series data
        with patch('app.services.catalog._get_comicvine_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Mock series data
            mock_client.fetch_volume.return_value = AsyncMock(payload={
                "results": {
                    "id": 20764,
                    "name": "Amazing Spider-Man (1963)",
                    "publisher": {"name": "Marvel Comics"},
                    "start_year": 1963,
                    "count_of_issues": 500,
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
                    "image": {"medium_url": "http://example.com/image.jpg"},
                }
            })
            
            # Mock volume issues
            mock_client.fetch_volume_issues.return_value = [
                {
                    "id": 400012345,
                    "issue_number": "1",
                    "name": "Amazing Spider-Man #1",
                    "cover_date": "1963-03-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue1.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1/4000-12345/",
                    "volume": {"id": 20764},
                },
                {
                    "id": 400012346,
                    "issue_number": "2",
                    "name": "Amazing Spider-Man #2",
                    "cover_date": "1963-04-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue2.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-2/4000-12346/",
                    "volume": {"id": 20764},
                }
            ]
            
            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify response structure
            assert "preview_token" in data
            assert "scope" in data
            assert "provider_series" in data
            assert "counts" in data
            assert "rows" in data
            assert "issued_at" in data
            assert "expires_at" in data
            
            # Verify scope is available
            assert data["scope"]["status"] == "available"
            assert data["scope"]["scope_key"] is not None
            assert data["scope"]["origin_issue_id"] == issue.id
            assert data["scope"]["series_label"] == "Amazing Spider-Man (1963)"
            
            # Verify provider series data
            assert data["provider_series"]["id"] == "20764"
            assert data["provider_series"]["name"] == "Amazing Spider-Man (1963)"
            assert data["provider_series"]["publisher"] == "Marvel Comics"
            
            # Verify counts
            assert data["counts"]["already_confirmed"] >= 0
            assert data["counts"]["safe_exact_match"] >= 0
            assert data["counts"]["needs_review_ambiguous"] >= 0
            assert data["counts"]["needs_review_conflict"] >= 0
            assert data["counts"]["unresolved"] >= 0
            assert data["counts"]["excluded_special"] >= 0
            
            # Verify rows exist
            assert len(data["rows"]) > 0
            
            # Verify token exists and is signed
            assert data["preview_token"] is not None
            assert "signature" in data["preview_token"]

    @pytest.mark.asyncio
    async def test_preview_series_mapping_unavailable_scope(self, auth_client: AsyncClient, sample_data):
        """Test preview with unavailable scope (no exact match)."""
        issue = sample_data["issue"]
        
        # Mock the ComicVine client to return series data
        with patch('app.services.catalog._get_comicvine_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Mock series data
            mock_client.fetch_volume.return_value = AsyncMock(payload={
                "results": {
                    "id": 20764,
                    "name": "Amazing Spider-Man (1963)",
                    "publisher": {"name": "Marvel Comics"},
                    "start_year": 1963,
                    "count_of_issues": 500,
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
                    "image": {"medium_url": "http://example.com/image.jpg"},
                }
            })
            
            # Mock volume issues with no exact match
            mock_client.fetch_volume_issues.return_value = [
                {
                    "id": 400012345,
                    "issue_number": "2",  # Different from origin issue #1
                    "name": "Amazing Spider-Man #2",
                    "cover_date": "1963-04-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue2.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-2/4000-12346/",
                    "volume": {"id": 20764},
                }
            ]
            
            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify scope is unavailable
            assert data["scope"]["status"] == "unavailable"
            assert data["scope"]["scope_key"] is None
            assert data["scope"]["basis"] == "insufficient_non_thread_evidence"
            assert data["preview_token"] is None
            assert data["expires_at"] is None
            
            # Verify counts are all zero for unavailable scope
            assert data["counts"]["already_confirmed"] == 0
            assert data["counts"]["safe_exact_match"] == 0
            assert data["counts"]["needs_review_ambiguous"] == 0
            assert data["counts"]["needs_review_conflict"] == 0
            assert data["counts"]["unresolved"] == 0
            assert data["counts"]["excluded_special"] == 0

    @pytest.mark.asyncio
    async def test_preview_series_mapping_provider_failure(self, auth_client: AsyncClient, sample_data):
        """Test preview with provider failure (ComicVine unavailable)."""
        issue = sample_data["issue"]

        # Mock ComicVine client failure
        with patch("app.services.catalog._get_comicvine_client") as mock_get_client:
            mock_get_client.return_value = None

            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764",
                },
            )

            assert response.status_code == 503
            data = response.json()
            assert data["detail"] == "provider_unavailable"

    @pytest.mark.asyncio
    async def test_preview_series_mapping_special_issues(self, auth_client: AsyncClient, sample_data):
        """Test preview with special/annual issues correctly excluded."""
        issue = sample_data["issue"]
        
        # Mock the ComicVine client to return series with special issues
        with patch('app.services.catalog._get_comicvine_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Mock series data
            mock_client.fetch_volume.return_value = AsyncMock(payload={
                "results": {
                    "id": 20764,
                    "name": "Amazing Spider-Man (1963)",
                    "publisher": {"name": "Marvel Comics"},
                    "start_year": 1963,
                    "count_of_issues": 500,
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
                    "image": {"medium_url": "http://example.com/image.jpg"},
                }
            })
            
            # Mock volume issues with special issues
            mock_client.fetch_volume_issues.return_value = [
                {
                    "id": 400012345,
                    "issue_number": "1",
                    "name": "Amazing Spider-Man #1",
                    "cover_date": "1963-03-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue1.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1/4000-12345/",
                    "volume": {"id": 20764},
                },
                {
                    "id": 400012346,
                    "issue_number": "Annual",  # Special issue
                    "name": "Amazing Spider-Man Annual #1",
                    "cover_date": "1964-01-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/annual1.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-annual-1/4000-12346/",
                    "volume": {"id": 20764},
                },
                {
                    "id": 400012347,
                    "issue_number": "2",
                    "name": "Amazing Spider-Man #2",
                    "cover_date": "1963-04-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue2.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-2/4000-12347/",
                    "volume": {"id": 20764},
                }
            ]
            
            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify special issues are classified as excluded
            special_rows = [row for row in data["rows"] if row["classification"] == "excluded_special"]
            assert len(special_rows) > 0
            
            # Verify "Annual" is specifically classified as excluded_special
            annual_rows = [row for row in data["rows"] if row["issue_number"] == "Annual"]
            assert len(annual_rows) == 1
            assert annual_rows[0]["classification"] == "excluded_special"
            
            # Verify non-special issues are not excluded
            normal_rows = [row for row in data["rows"] if row["classification"] != "excluded_special"]
            assert len(normal_rows) > 0

    @pytest.mark.asyncio
    async def test_preview_series_mapping_conflict_detection(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test preview with cross-provider conflict detection."""
        issue = sample_data["issue"]
        
        # Create conflicting external identity with a DIFFERENT provider
        conflicting_identity = ExternalIdentity(
            provider="cbl",  # Different provider = cross-provider conflict
            entity_type="issue",
            external_id="99999",
            external_url="https://comicbookdb.com/issue/99999",
            metadata_json={"name": "Different Issue", "issue_number": "999"},
        )
        async_db.add(conflicting_identity)
        await async_db.flush()

        # Create a conflicting mapping
        conflicting_mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=conflicting_identity.id,
            status="confirmed",
            evidence_source="test",
            confidence=0.8,
        )
        async_db.add(conflicting_mapping)
        await async_db.commit()
        
        # Mock the ComicVine client
        with patch('app.services.catalog._get_comicvine_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Mock series data
            mock_client.fetch_volume.return_value = AsyncMock(payload={
                "results": {
                    "id": 20764,
                    "name": "Amazing Spider-Man (1963)",
                    "publisher": {"name": "Marvel Comics"},
                    "start_year": 1963,
                    "count_of_issues": 500,
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
                    "image": {"medium_url": "http://example.com/image.jpg"},
                }
            })
            
            # Mock volume issues
            mock_client.fetch_volume_issues.return_value = [
                {
                    "id": 400012345,
                    "issue_number": "1",
                    "name": "Amazing Spider-Man #1",
                    "cover_date": "1963-03-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue1.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1/4000-12345/",
                    "volume": {"id": 20764},
                }
            ]
            
            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify cross-provider conflict detection
            conflict_rows = [row for row in data["rows"] if row["classification"] == "needs_review_conflict"]
            assert len(conflict_rows) > 0

    @pytest.mark.asyncio
    async def test_preview_series_mapping_ambiguous_numbers(self, auth_client: AsyncClient, sample_data):
        """Test preview with ambiguous issue numbers."""
        issue = sample_data["issue"]
        
        # Mock the ComicVine client to return series with ambiguous issues
        with patch('app.services.catalog._get_comicvine_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Mock series data
            mock_client.fetch_volume.return_value = AsyncMock(payload={
                "results": {
                    "id": 20764,
                    "name": "Amazing Spider-Man (1963)",
                    "publisher": {"name": "Marvel Comics"},
                    "start_year": 1963,
                    "count_of_issues": 500,
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
                    "image": {"medium_url": "http://example.com/image.jpg"},
                }
            })
            
            # Mock volume issues with ambiguous numbers
            mock_client.fetch_volume_issues.return_value = [
                {
                    "id": 400012345,
                    "issue_number": "1",
                    "name": "Amazing Spider-Man #1",
                    "cover_date": "1963-03-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue1.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1/4000-12345/",
                    "volume": {"id": 20764},
                },
                {
                    "id": 400012346,
                    "issue_number": "1.5",  # Ambiguous fractional
                    "name": "Amazing Spider-Man #1.5",
                    "cover_date": "1963-04-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issue1.5.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-1.5/4000-12346/",
                    "volume": {"id": 20764},
                },
                {
                    "id": 400012347,
                    "issue_number": "II",  # Ambiguous Roman numeral
                    "name": "Amazing Spider-Man #II",
                    "cover_date": "1963-05-01",
                    "store_date": None,
                    "image": {"small_url": "http://example.com/issueII.jpg"},
                    "site_detail_url": "https://comicvine.gamespot.com/amazing-spider-man-ii/4000-12347/",
                    "volume": {"id": 20764},
                }
            ]
            
            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify ambiguous issues are classified correctly
            ambiguous_rows = [row for row in data["rows"] if row["classification"] == "needs_review_ambiguous"]
            assert len(ambiguous_rows) > 0
            
            # Verify Roman numerals are classified as ambiguous, not special
            roman_rows = [row for row in data["rows"] if row["issue_number"] == "II"]
            assert len(roman_rows) == 1
            assert roman_rows[0]["classification"] == "needs_review_ambiguous"
            
            # Verify fractional numbers are classified as ambiguous
            fractional_rows = [row for row in data["rows"] if row["issue_number"] == "1.5"]
            assert len(fractional_rows) == 1
            assert fractional_rows[0]["classification"] == "needs_review_ambiguous"
            
            # Verify special issues are still excluded
            special_rows = [row for row in data["rows"] if row["classification"] == "excluded_special"]
            assert len(special_rows) == 0  # No special issues in this test

    @pytest.mark.asyncio
    async def test_preview_series_mapping_invalid_request(self, auth_client: AsyncClient):
        """Test preview with invalid request data."""
        # Test missing required fields
        response = await auth_client.post(
            "/api/v1/catalog/series-mappings/preview",
            json={
                "origin_issue_id": 789,
                # Missing provider and provider_series_external_id
            }
        )
        assert response.status_code == 422  # Validation error
        
        # Test invalid provider
        response = await auth_client.post(
            "/api/v1/catalog/series-mappings/preview",
            json={
                "origin_issue_id": 789,
                "provider": "invalid_provider",
                "provider_series_external_id": "20764"
            }
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_preview_series_mapping_not_authenticated(self, client: AsyncClient):
        """Test preview endpoint without authentication."""
        response = await client.post(
            "/api/v1/catalog/series-mappings/preview",
            json={
                "origin_issue_id": 789,
                "provider": "comicvine",
                "provider_series_external_id": "20764"
            }
        )
        assert response.status_code == 401  # Unauthorized

    @pytest.mark.asyncio
    async def test_preview_series_mapping_origin_issue_not_found(self, auth_client: AsyncClient):
        """Test preview with non-existent origin issue."""
        response = await auth_client.post(
            "/api/v1/catalog/series-mappings/preview",
            json={
                "origin_issue_id": 999999,
                "provider": "comicvine",
                "provider_series_external_id": "20764"
            }
        )
        assert response.status_code == 200  # Should return unavailable scope
        data = response.json()
        assert data["scope"]["status"] == "unavailable"
        assert data["scope"]["basis"] == "origin_issue_not_found"

    @pytest.mark.asyncio
    async def test_preview_series_mapping_local_catalog_path(self, auth_client: AsyncClient, async_db: AsyncSession, sample_data):
        """Test preview using local catalog when series exists locally."""
        issue = sample_data["issue"]

        # Create a series in the local catalog
        series_identity = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id="20764",
            external_url="https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
            metadata_json={"name": "Amazing Spider-Man (1963)", "publisher": {"name": "Marvel Comics"}},
        )
        async_db.add(series_identity)
        await async_db.flush()

        # Create an external identity for the issue in the local catalog
        issue_ext_identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id="12345",
            external_url="https://comicvine.gamespot.com/issue/4000-12345/",
            metadata_json={"name": "Amazing Spider-Man #1", "issue_number": "1"},
        )
        async_db.add(issue_ext_identity)
        await async_db.flush()

        # Create issue-external identity mapping
        issue_mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=issue_ext_identity.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
        async_db.add(issue_mapping)
        await async_db.flush()

        # Create a thread-series mapping for the origin issue's thread
        series_mapping = ThreadExternalSeriesMapping(
            thread_id=issue.thread_id,
            external_identity_id=series_identity.id,
            status="confirmed",
            evidence_source="test",
        )
        async_db.add(series_mapping)
        await async_db.commit()

        # Mock ComicVine client to return None (local catalog path)
        with patch("app.services.catalog._get_comicvine_client") as mock_get_client:
            mock_get_client.return_value = None

            # Make the request
            response = await auth_client.post(
                "/api/v1/catalog/series-mappings/preview",
                json={
                    "origin_issue_id": issue.id,
                    "provider": "comicvine",
                    "provider_series_external_id": "20764"
                }
            )

            assert response.status_code == 200
            data = response.json()

            # Verify scope is available since series has issues in local catalog with thread mapping
            assert data["scope"]["status"] == "available"
            assert data["scope"]["series_label"] == "Amazing Spider-Man (1963)"
            assert data["provider_series"]["id"] == "20764"
            assert len(data["rows"]) > 0
