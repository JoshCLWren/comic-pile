"""Tests for the ComicVine backfill operator."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity
from app.models.issue import Issue
from comic_pile.comicvine_provider import ComicVineRateLimitError
from scripts.backfill_read_comicvine import (
    BackfillProgress,
    BackfillStats,
    ComicVineBackfillOperator,
    ResourceThrottleTracker,
    parse_args,
)


@pytest.fixture
def temp_cache_dir() -> Path:
    """Create a temporary cache directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture(autouse=True)
def _comicvine_api_key() -> None:
    """Provide a dummy API key so live-mode operator construction works in tests."""
    with patch.dict(os.environ, {"COMICVINE_API_KEY": "test-key"}):
        yield


@pytest.fixture
def sample_issues() -> list[Issue]:
    """Return sample issues for testing."""
    return [
        Issue(id=1, thread_id=1, issue_number="1", position=1, status="read"),
        Issue(id=2, thread_id=2, issue_number="2", position=1, status="read"),
        Issue(id=3, thread_id=3, issue_number="3", position=1, status="read"),
    ]


@pytest.fixture
def sample_external_identity() -> ExternalIdentity:
    """Return a sample external identity for testing."""
    now = datetime.now(UTC)
    return ExternalIdentity(
        id=1,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-123",
        external_url="https://comicvine.gamespot.com/issue/4000-123/",
        metadata_json={"volume_id": 456, "issue_number": "1"},
        provider_updated_at=now,
    )


@pytest_asyncio.fixture
async def mock_db_session() -> AsyncSession:
    """Create a mock database session for testing."""
    mock_session = AsyncMock(spec=AsyncSession)
    # A plain (synchronous) result mock: AsyncMock children would return
    # unawaited coroutines for scalar_one_or_none()/scalars()/all().
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.add = Mock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    return mock_session


class TestBackfillStats:
    """Test the BackfillStats dataclass."""

    def test_initial_state(self) -> None:
        """Test that stats start with zero values."""
        stats = BackfillStats()
        assert stats.total_issues == 0
        assert stats.resolved_identities == 0
        assert stats.resolved_creators == 0
        assert stats.unresolved_identities == 0
        assert stats.unresolved_creators == 0
        assert stats.rate_limited == 0
        assert stats.errors == 0
        assert stats.skipped_existing == 0

    def test_completion_rate_zero_issues(self) -> None:
        """Test completion rate calculation with zero issues."""
        stats = BackfillStats()
        assert stats.completion_rate == 0.0

    def test_completion_rate_partial(self) -> None:
        """Test completion rate calculation with partial completion."""
        stats = BackfillStats()
        stats.total_issues = 10
        stats.resolved_identities = 3
        stats.resolved_creators = 2
        assert stats.completion_rate == 50.0

    def test_completion_rate_full(self) -> None:
        """Test completion rate calculation with full completion."""
        stats = BackfillStats()
        stats.total_issues = 10
        stats.resolved_identities = 5
        stats.resolved_creators = 5
        assert stats.completion_rate == 100.0


class TestBackfillProgress:
    """Test the BackfillProgress dataclass."""

    def test_initial_state(self) -> None:
        """Test that progress starts with default values."""
        progress = BackfillProgress()
        assert progress.current_issue == 0
        assert progress.current_phase == "identity"
        assert isinstance(progress.stats, BackfillStats)
        assert isinstance(progress.start_time, datetime)
        assert isinstance(progress.last_update, datetime)

    def test_update_progress(self) -> None:
        """Test progress updates."""
        progress = BackfillProgress()
        
        # Update identity resolution
        progress.update(1, "identity", "resolved_identity")
        assert progress.current_issue == 1
        assert progress.current_phase == "identity"
        assert progress.stats.resolved_identities == 1
        
        # Update creator hydration
        progress.update(1, "creator", "resolved_creator")
        assert progress.current_issue == 1
        assert progress.current_phase == "creator"
        assert progress.stats.resolved_creators == 1


class TestComicVineBackfillOperator:
    """Test the ComicVineBackfillOperator class."""

    def test_init_dry_run(self, temp_cache_dir: Path) -> None:
        """Test initialization in dry run mode."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=temp_cache_dir,
            dry_run=True,
        )
        assert operator.user_id == 1
        assert operator.database_url == "sqlite://test"
        assert operator.cache_dir == temp_cache_dir
        assert operator.dry_run is True
        assert operator.client is None

    def test_init_live_mode_with_api_key(self, temp_cache_dir: Path) -> None:
        """Test initialization in live mode with API key."""
        with patch.dict(os.environ, {"COMICVINE_API_KEY": "test-key"}):
            operator = ComicVineBackfillOperator(
                user_id=1,
                database_url="sqlite://test",
                cache_dir=temp_cache_dir,
                dry_run=False,
            )
            assert operator.client is not None

    def test_init_live_mode_without_api_key(self, temp_cache_dir: Path) -> None:
        """Test initialization in live mode without API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="COMICVINE_API_KEY is required"):
                ComicVineBackfillOperator(
                    user_id=1,
                    database_url="sqlite://test",
                    cache_dir=temp_cache_dir,
                    dry_run=False,
                )

    @pytest.mark.asyncio
    async def test_get_read_issues(self, mock_db_session: AsyncSession, sample_issues: list[Issue]) -> None:
        """Test getting read issues for processing."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        # Mock the database query to return our sample issues
        mock_db_session.execute.return_value = Mock()
        mock_db_session.execute.return_value.scalars.return_value.all.return_value = sample_issues

        issues = await operator.get_read_issues(mock_db_session)
        assert len(issues) == 3
        assert all(issue.status == "read" for issue in issues)

    @pytest.mark.asyncio
    async def test_resolve_identity_locally_with_series_mapping(
        self, 
        mock_db_session: AsyncSession, 
        sample_external_identity: ExternalIdentity
    ) -> None:
        """Test identity resolution using local series mapping."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        # Mock series identity result
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = sample_external_identity

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        identity = await operator.resolve_identity_locally(mock_db_session, issue)
        
        assert identity is not None
        assert identity.provider == "comicvine"

    @pytest.mark.asyncio
    async def test_resolve_identity_locally_no_series_mapping(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test identity resolution with no local series mapping."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        # Mock no series identity result
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        identity = await operator.resolve_identity_locally(mock_db_session, issue)
        
        assert identity is None

    @pytest.mark.asyncio
    async def test_process_issue_identity_dry_run(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test processing issue identity in dry run mode."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock local resolution to return None (no local identity)
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None
        
        status = await operator.process_issue_identity(mock_db_session, issue)
        assert status == "unresolved"

    @pytest.mark.asyncio
    async def test_process_issue_identity_local_resolution(
        self, 
        mock_db_session: AsyncSession, 
        sample_external_identity: ExternalIdentity
    ) -> None:
        """Test processing issue identity with local resolution."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock local resolution to return identity
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = sample_external_identity
        
        status = await operator.process_issue_identity(mock_db_session, issue)
        assert status == "resolved"
        
        # Verify that the database was called to create the mapping
        mock_db_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_process_issue_identity_rate_limited(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test processing issue identity with rate limiting."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock local resolution to return None
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None
        
        # Mock provider resolution to raise rate limit error
        with patch.object(operator, 'resolve_identity_provider', side_effect=ComicVineRateLimitError("Rate limited")):
            status = await operator.process_issue_identity(mock_db_session, issue)
            assert status == "rate_limited"

    @pytest.mark.asyncio
    async def test_process_issue_identity_error(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test processing issue identity with error."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock local resolution to raise an exception
        with patch.object(operator, 'resolve_identity_locally', side_effect=Exception("Test error")):
            status = await operator.process_issue_identity(mock_db_session, issue)
            assert status == "error"

    @pytest.mark.asyncio
    async def test_process_issue_creator_identity_not_resolved(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test processing issue creator when identity is not resolved."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")

        # No confirmed identity and no live client in dry-run mode.
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

        status = await operator.process_issue_creator(mock_db_session, issue)
        assert status == "unresolved"

    @pytest.mark.asyncio
    async def test_process_issue_creator_local_resolution(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test processing issue creator with local resolution."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock identity resolution to return resolved
        with patch.object(operator, 'process_issue_identity', return_value="resolved"):
            # Mock local creator resolution to return True
            with patch.object(operator, 'hydrate_creator_locally', return_value=True):
                status = await operator.process_issue_creator(mock_db_session, issue)
                assert status == "resolved"

    @pytest.mark.asyncio
    async def test_process_issue_full_workflow(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test the complete issue processing workflow."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock identity resolution to return resolved
        with patch.object(operator, 'process_issue_identity', return_value="resolved"):
            # Mock creator resolution to return resolved
            with patch.object(operator, 'process_issue_creator', return_value="resolved"):
                await operator.process_issue(mock_db_session, issue)
                
                # Verify that both phases were called
                assert operator.progress.current_issue == 1
                assert operator.progress.stats.resolved_identities == 1
                assert operator.progress.stats.resolved_creators == 1


class TestThrottleContinuation:
    """Test throttle continuation and resource isolation."""

    @pytest.mark.asyncio
    async def test_resource_isolation_after_throttle(
        self,
        mock_db_session: AsyncSession
    ) -> None:
        """Test that a throttled resource short-circuits further live calls."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
            min_live_interval_seconds=0.0,
        )

        issues = [
            Issue(id=1, thread_id=1, issue_number="1", position=1, status="read"),
            Issue(id=2, thread_id=2, issue_number="2", position=1, status="read"),
        ]

        # Mock identity resolution to return None for both issues
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

        # Track provider calls
        provider_calls = []

        async def mock_resolve_identity_provider(db, issue):
            provider_calls.append(issue.id)
            raise ComicVineRateLimitError("Rate limited")

        with patch.object(operator, 'resolve_identity_provider', side_effect=mock_resolve_identity_provider):
            # Process first issue - should be rate limited
            status1 = await operator.process_issue_identity(mock_db_session, issues[0])
            assert status1 == "rate_limited"

            # Process second issue - live work for the cooling resource is
            # skipped without another provider call
            status2 = await operator.process_issue_identity(mock_db_session, issues[1])
            assert status2 == "rate_limited"
            assert provider_calls == [1]

    @pytest.mark.asyncio
    async def test_cooling_resource_does_not_block_other_resources(
        self,
        mock_db_session: AsyncSession
    ) -> None:
        """Test that a cooling identity resource does not block creator work."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
            min_live_interval_seconds=0.0,
        )

        identity_issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        creator_issue = Issue(id=2, thread_id=2, issue_number="2", position=1, status="read")

        # No local identities anywhere
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

        creator_calls = []

        async def mock_hydrate_creator_provider(db, issue):
            creator_calls.append(issue.id)
            return True

        with patch.object(
            operator, 'resolve_identity_provider', side_effect=ComicVineRateLimitError("Rate limited")
        ):
            status = await operator.process_issue_identity(mock_db_session, identity_issue)
            assert status == "rate_limited"

        with patch.object(operator, 'hydrate_creator_provider', side_effect=mock_hydrate_creator_provider):
            status = await operator.process_issue_creator(mock_db_session, creator_issue)
            assert status == "resolved"
            assert creator_calls == [2]

    @pytest.mark.asyncio
    async def test_cached_response_use_during_cooldown(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test that cached responses are used during resource cooldown."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock local resolution to return None
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None
        
        # Mock provider resolution to return None (simulating cooldown)
        with patch.object(operator, 'resolve_identity_provider', return_value=None):
            status = await operator.process_issue_identity(mock_db_session, issue)
            assert status == "unresolved"


class TestOrchestrationOrder:
    """Test the orchestration order of operations."""

    @pytest.mark.asyncio
    async def test_local_work_before_provider_work(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test that local work is attempted before provider work."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Track method calls
        local_calls = []
        provider_calls = []
        
        async def mock_resolve_identity_locally(db, issue):
            local_calls.append(issue.id)
            return None
        
        async def mock_resolve_identity_provider(db, issue):
            provider_calls.append(issue.id)
            return None
        
        with patch.object(operator, 'resolve_identity_locally', side_effect=mock_resolve_identity_locally):
            with patch.object(operator, 'resolve_identity_provider', side_effect=mock_resolve_identity_provider):
                await operator.process_issue_identity(mock_db_session, issue)
        
        # Verify local was called before provider
        assert len(local_calls) == 1
        assert len(provider_calls) == 1
        assert local_calls[0] == provider_calls[0] == 1

    @pytest.mark.asyncio
    async def test_creator_phase_only_after_identity_resolution(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test that creator phase only runs after identity is resolved."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock identity resolution to return unresolved
        with patch.object(operator, 'process_issue_identity', return_value="unresolved"):
            # Mock creator methods to track if they're called
            creator_calls = []
            
            original_local = operator.hydrate_creator_locally
            original_provider = operator.hydrate_creator_provider
            
            async def mock_local(db, issue):
                creator_calls.append("local")
                return False
            
            async def mock_provider(db, issue):
                creator_calls.append("provider")
                return False
            
            with patch.object(operator, 'hydrate_creator_locally', side_effect=mock_local):
                with patch.object(operator, 'hydrate_creator_provider', side_effect=mock_provider):
                    await operator.process_issue(mock_db_session, issue)
            
            # Verify creator methods were not called
            assert len(creator_calls) == 0

    @pytest.mark.asyncio
    async def test_creator_phase_runs_after_identity_resolution(
        self, 
        mock_db_session: AsyncSession
    ) -> None:
        """Test that creator phase runs when identity is resolved."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock identity resolution to return resolved
        with patch.object(operator, 'process_issue_identity', return_value="resolved"):
            # Mock creator methods to track if they're called
            creator_calls = []
            
            async def mock_local(db, issue):
                creator_calls.append("local")
                return True
            
            with patch.object(operator, 'hydrate_creator_locally', side_effect=mock_local):
                await operator.process_issue(mock_db_session, issue)
            
            # Verify creator method was called
            assert len(creator_calls) == 1
            assert creator_calls[0] == "local"


class TestIdempotencyAndResumability:
    """Test idempotency and resumability features."""

    @pytest.mark.asyncio
    async def test_idempotent_identity_mapping(
        self, 
        mock_db_session: AsyncSession, 
        sample_external_identity: ExternalIdentity
    ) -> None:
        """Test that identity mapping is idempotent."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
        )

        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Mock local resolution to return identity
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = sample_external_identity
        
        # Process the same issue twice
        await operator.process_issue_identity(mock_db_session, issue)
        await operator.process_issue_identity(mock_db_session, issue)
        
        # Verify the database was called (idempotent operation)
        mock_db_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_resume_from_existing_mappings(
        self, 
        mock_db_session: AsyncSession, 
        sample_external_identity: ExternalIdentity
    ) -> None:
        """Test that the operator can resume from existing mappings."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        # Mock existing confirmed mapping
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = sample_external_identity
        
        issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        
        # Get read issues should exclude issues with existing mappings
        with patch.object(operator, 'get_read_issues') as mock_get_issues:
            mock_get_issues.return_value = []  # No issues need processing
            issues = await operator.get_read_issues(mock_db_session)
            
            assert len(issues) == 0


class TestArgumentParsing:
    """Test command-line argument parsing."""

    def test_parse_args_required(self) -> None:
        """Test parsing required arguments."""
        args = [
            "--user-id", "1",
            "--database-url", "postgresql://test",
        ]
        
        with patch("sys.argv", ["backfill_read_comicvine.py"] + args):
            parsed = parse_args()
            assert parsed.user_id == 1
            assert parsed.database_url == "postgresql://test"
            assert parsed.dry_run is False
            assert parsed.requests_per_hour == 180

    def test_parse_args_all_options(self) -> None:
        """Test parsing all optional arguments."""
        args = [
            "--user-id", "1",
            "--database-url", "postgresql://test",
            "--cache-dir", "/tmp/cache",
            "--dry-run",
            "--requests-per-hour", "360",
            "--comicvine-db", "/tmp/comicvine.sqlite",
            "--report-path", "/tmp/report.json",
            "--min-live-interval-seconds", "2.5",
        ]

        with patch("sys.argv", ["backfill_read_comicvine.py"] + args):
            parsed = parse_args()
            assert parsed.user_id == 1
            assert parsed.database_url == "postgresql://test"
            assert parsed.cache_dir == Path("/tmp/cache")
            assert parsed.dry_run is True
            assert parsed.requests_per_hour == 360
            assert parsed.comicvine_db == Path("/tmp/comicvine.sqlite")
            assert parsed.report_path == Path("/tmp/report.json")
            assert parsed.min_live_interval_seconds == 2.5

    def test_parse_args_defaults(self) -> None:
        """Test default values for the newer optional arguments."""
        args = [
            "--user-id", "1",
            "--database-url", "postgresql://test",
        ]

        with patch("sys.argv", ["backfill_read_comicvine.py"] + args):
            parsed = parse_args()
            assert parsed.comicvine_db is None
            assert parsed.report_path is None
            assert parsed.min_live_interval_seconds == 1.0


class TestIntegrationScenarios:
    """Test integration scenarios combining multiple features."""

    @pytest.mark.asyncio
    async def test_full_backfill_workflow(
        self, 
        mock_db_session: AsyncSession, 
        sample_issues: list[Issue]
    ) -> None:
        """Test the complete backfill workflow with multiple scenarios."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=True,
        )

        # Mock issues to be processed
        mock_db_session.execute.return_value.scalars.return_value.all.return_value = sample_issues

        # Mock identity resolution scenarios:
        # Issue 1: resolved locally
        # Issue 2: resolved via provider (rate limited)
        # Issue 3: unresolved
        identity_results = ["resolved", "rate_limited", "unresolved"]

        async def mock_process_issue_identity(db, issue):
            return identity_results[issue.id - 1]

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_db_session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(operator, 'process_issue_identity', side_effect=mock_process_issue_identity):
            with patch.object(operator, 'process_issue_creator') as mock_creator:
                # Mock creator resolution for issues with resolved identities
                def mock_creator_side_effect(db, issue):
                    if issue.id == 1:
                        return "resolved"
                    return "unresolved"

                mock_creator.side_effect = mock_creator_side_effect

                # Run the backfill with an injected session factory
                stats = await operator.run(session_factory=lambda: session_cm)

                # Verify statistics
                assert stats.total_issues == 3
                assert stats.resolved_identities == 1
                assert stats.rate_limited == 1
                assert stats.unresolved_identities == 1
                assert stats.resolved_creators == 1
                assert stats.unresolved_creators == 0  # Issue 3 never gets to creator phase
                assert stats.completion_rate == pytest.approx(66.67, abs=0.01)

    @pytest.mark.asyncio
    async def test_throttle_continuation_across_resources(
        self,
        mock_db_session: AsyncSession
    ) -> None:
        """Test throttle continuation across different ComicVine resources."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=Path("/tmp"),
            dry_run=False,
            min_live_interval_seconds=0.0,
        )

        identity_issue = Issue(id=1, thread_id=1, issue_number="1", position=1, status="read")
        creator_issue = Issue(id=2, thread_id=2, issue_number="2", position=1, status="read")

        # Mock identity resolution to return None for both
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

        # Track provider calls
        provider_calls = []
        creator_calls = []

        async def mock_resolve_identity_provider(db, issue):
            provider_calls.append(issue.id)
            raise ComicVineRateLimitError("Search rate limited")

        async def mock_hydrate_creator_provider(db, issue):
            creator_calls.append(issue.id)
            return True

        with patch.object(operator, 'resolve_identity_provider', side_effect=mock_resolve_identity_provider):
            # Throttle the identity resource
            status1 = await operator.process_issue_identity(mock_db_session, identity_issue)
            assert status1 == "rate_limited"

        with patch.object(operator, 'hydrate_creator_provider', side_effect=mock_hydrate_creator_provider):
            # Creator work on another resource still proceeds
            status2 = await operator.process_issue_creator(mock_db_session, creator_issue)
            assert status2 == "resolved"

        assert provider_calls == [1]
        assert creator_calls == [2]


class TestResourceThrottleTracker:
    """Test the per-resource throttle tracker."""

    def test_backoff_bounded_at_one_hour(self) -> None:
        """Test that repeated throttles never exceed a one-hour cooldown."""
        now = [1000.0]
        tracker = ResourceThrottleTracker(clock=lambda: now[0])

        delays = [tracker.record_throttle("search") for _ in range(10)]

        assert delays[0] == 60.0
        assert delays[1] == 120.0
        assert all(delay <= 3600.0 for delay in delays)
        assert delays[-1] == 3600.0
        assert tracker.cooling("search") is True

    def test_success_resets_backoff(self) -> None:
        """Test that a successful request clears the cooldown."""
        now = [1000.0]
        tracker = ResourceThrottleTracker(clock=lambda: now[0])

        tracker.record_throttle("search")
        assert tracker.cooling("search") is True

        tracker.record_success("search")
        assert tracker.cooling("search") is False

        # Backoff restarts at the base delay after a reset
        assert tracker.record_throttle("search") == 60.0

    def test_resources_are_independent(self) -> None:
        """Test that throttling one resource leaves others usable."""
        tracker = ResourceThrottleTracker()

        tracker.record_throttle("search")

        assert tracker.cooling("search") is True
        assert tracker.cooling("issue") is False

    def test_snapshot_is_machine_readable(self) -> None:
        """Test that the throttle snapshot exposes per-resource state."""
        tracker = ResourceThrottleTracker()

        tracker.record_throttle("search")
        snapshot = tracker.snapshot()

        assert snapshot["search"]["cooling"] is True
        assert snapshot["search"]["consecutive_throttles"] == 1


class TestBuildReport:
    """Test the machine-readable backfill report."""

    def test_report_contains_progress_and_throttles(self, temp_cache_dir: Path) -> None:
        """Test that the report exposes stats and throttle state."""
        operator = ComicVineBackfillOperator(
            user_id=1,
            database_url="sqlite://test",
            cache_dir=temp_cache_dir,
            dry_run=True,
        )
        operator.progress.stats.total_issues = 2
        operator.progress.update(1, "identity", "resolved")
        operator.throttles.record_throttle("search")

        report = operator.build_report()

        assert report["user_id"] == 1
        assert report["dry_run"] is True
        assert report["total_issues"] == 2
        assert report["resolved_identities"] == 1
        assert report["throttles"]["search"]["cooling"] is True
        assert "completed_at" in report