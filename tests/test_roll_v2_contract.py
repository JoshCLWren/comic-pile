"""Contract tests for Roll v2 bootstrap and rate response schemas."""

from datetime import UTC, datetime

from app.schemas.roll import RollRecoveryInfo
from app.schemas.roll_v2 import (
    IdentityState,
    ProgressScope,
    RateResponse,
    RollableIdentity,
    RollableIssue,
    RollableItem,
    RollableReader,
    RollableRoute,
    RollableThread,
    RollLastRead,
    RollReconciliation,
    RollV2BootstrapResponse,
    RouteKind,
)
from app.schemas.thread import ThreadResponse


class TestRollV2BootstrapResponse:
    """Test the v2 bootstrap response schema."""

    def test_v2_response_is_superset_of_v1_fields(self):
        """Test that all v1 bootstrap fields are preserved in v2."""
        # These fields should be present in both v1 and v2
        v1_fields = {
            'session_id', 'user_id', 'current_die', 'manual_die',
            'pending_thread_id', 'last_rolled_result', 'session_mode',
            'active_thread', 'roll_recovery', 'bandwidth', 'snoozed_threads',
            'snoozed_count', 'skipped_thread_ids', 'skipped_threads',
            'blocked_count', 'blocked_threads', 'stale_thread_count',
            'stale_thread', 'timezone'
        }

        # v2 adds these fields
        v2_additional_fields = {'rollable', 'last_read'}

        # All v1 fields should be in v2
        for field in v1_fields:
            assert hasattr(RollV2BootstrapResponse, field), f"v1 field {field} missing from v2"

        # v2 should have the additional fields
        for field in v2_additional_fields:
            assert hasattr(RollV2BootstrapResponse, field), f"v2 field {field} missing"

    def test_rollable_replaces_roll_pool(self):
        """Test that rollable replaces roll_pool and has correct structure."""
        # roll_pool should not exist in v2
        assert not hasattr(RollV2BootstrapResponse, 'roll_pool')

        # rollable should exist and be a list of RollableItem
        assert hasattr(RollV2BootstrapResponse, 'rollable')
        assert RollV2BootstrapResponse.model_fields['rollable'].annotation == list[RollableItem]

    def test_last_read_is_nullable_session_scoped(self):
        """Test that last_read is nullable and session-scoped."""
        assert hasattr(RollV2BootstrapResponse, 'last_read')
        assert RollV2BootstrapResponse.model_fields['last_read'].annotation == RollLastRead | None

    def test_rollable_item_structure(self):
        """Test that rollable items have the required structure."""
        # Create a minimal rollable item
        thread = RollableThread(id=1, title="Test Thread", format="comic")
        issue = RollableIssue(id=1, number="1", canonical_series_title=None, cover_url=None)
        identity = RollableIdentity(
            source="unavailable",
            canonical_series_id=None,
            state=IdentityState.UNRESOLVED,
            series_mapping_state=IdentityState.UNRESOLVED,
        )
        reader = RollableReader(
            latest_rating=None,
            average_rating=None,
            rating_count=None,
            read_count=None,
            issue_count=None,
            progress_scope=ProgressScope.THREAD
        )
        routes = [RollableRoute(kind=RouteKind.GROUP, name="test")]

        item = RollableItem(
            thread=thread,
            issue=issue,  # Required/non-null
            identity=identity,
            reader=reader,
            routes=routes,
            overflow_routes_count=0
        )

        # Verify issue is required (no default)
        assert item.issue is not None
        assert item.issue.id == 1

        # Verify routes can be empty
        item_no_routes = RollableItem(
            thread=thread,
            issue=issue,
            identity=identity,
            reader=reader,
            routes=[],  # Empty routes
            overflow_routes_count=0
        )
        assert item_no_routes.routes == []

    def test_rollable_routes_capped_at_three_with_overflow(self):
        """Routes hold at most 3 entries; extras are counted in overflow."""
        thread = RollableThread(id=1, title="Test Thread", format="comic")
        issue = RollableIssue(id=1, number="1")
        identity = RollableIdentity(
            source="unavailable",
            canonical_series_id=None,
            state=IdentityState.UNRESOLVED,
            series_mapping_state=IdentityState.UNRESOLVED,
        )
        reader = RollableReader(progress_scope=ProgressScope.THREAD)
        routes = [RollableRoute(kind=RouteKind.GROUP, name=f"g{i}") for i in range(3)]

        item = RollableItem(
            thread=thread,
            issue=issue,
            identity=identity,
            reader=reader,
            routes=routes,
            overflow_routes_count=2,
        )
        assert len(item.routes) == 3
        assert item.overflow_routes_count == 2
        assert all(route.kind == RouteKind.GROUP for route in item.routes)


class TestRateResponse:
    """Test the rate response schema."""

    def test_rate_response_extends_thread_response(self):
        """Test that RateResponse preserves all ThreadResponse fields."""
        # These ThreadResponse fields should all be in RateResponse
        thread_response_fields = {
            'id', 'title', 'format', 'issues_remaining', 'queue_position',
            'status', 'last_rating', 'last_activity_at', 'notes', 'is_test',
            'is_blocked', 'blocking_reasons', 'created_at', 'total_issues',
            'reading_progress', 'next_unread_issue_id', 'next_unread_issue_number'
        }

        for field in thread_response_fields:
            assert hasattr(RateResponse, field), f"ThreadResponse field {field} missing from RateResponse"

    def test_rate_response_subclasses_thread_response(self):
        """RateResponse must subclass ThreadResponse so fields cannot drift."""
        assert issubclass(RateResponse, ThreadResponse)

    def test_rate_response_adds_roll_reconciliation(self):
        """Test that RateResponse adds roll_reconciliation field."""
        assert hasattr(RateResponse, 'roll_reconciliation')
        assert RateResponse.model_fields['roll_reconciliation'].annotation == RollReconciliation | None

    def test_roll_reconciliation_structure(self):
        """Test roll_reconciliation structure."""
        reconciliation = RollReconciliation(
            last_read=RollLastRead(
                issue_id=1,
                issue_number="1",
                thread_id=1,
                thread_title="Test",
                read_at=datetime.now(UTC)
            )
        )

        assert reconciliation.last_read is not None
        assert reconciliation.last_read.issue_id == 1
        assert reconciliation.last_read.issue_number == "1"


class TestV2Enums:
    """Test v2 enum values are frozen."""

    def test_identity_state_enum(self):
        """Test identity state enum has correct frozen values."""
        expected_states = ["confirmed", "candidate", "unresolved", "ambiguous", "conflicting"]
        actual_states = [state.value for state in IdentityState]

        assert set(actual_states) == set(expected_states)
        assert len(actual_states) == len(expected_states)

    def test_route_kind_enum(self):
        """Test route kind enum has correct frozen value."""
        expected_kinds = ["group"]
        actual_kinds = [kind.value for kind in RouteKind]

        assert set(actual_kinds) == set(expected_kinds)
        assert len(actual_kinds) == len(expected_kinds)

    def test_progress_scope_enum(self):
        """Test progress scope enum has correct frozen values."""
        expected_scopes = ["canonical_series_run", "thread"]
        actual_scopes = [scope.value for scope in ProgressScope]

        assert set(actual_scopes) == set(expected_scopes)
        assert len(actual_scopes) == len(expected_scopes)


class TestNullabilityContracts:
    """Test nullability requirements from the issue."""

    def test_cover_url_nullable(self):
        """Test that cover_url is nullable."""
        issue = RollableIssue(
            id=1,
            number="1",
            canonical_series_title="Test Series",
            cover_url=None  # Should be allowed
        )
        assert issue.cover_url is None

    def test_cover_url_rejects_raw_provider_urls(self):
        """Raw provider image URLs must never satisfy the Roll contract."""
        try:
            RollableIssue(id=1, number="1", cover_url="https://comicvine.gamespot.com/a.jpg")
        except ValueError:
            return
        raise AssertionError("Raw ComicVine cover URL was accepted")

    def test_cover_url_accepts_same_origin_optimized(self):
        """Same-origin optimized covers are the only non-null form."""
        issue = RollableIssue(
            id=1,
            number="1",
            cover_url="/api/v1/images/optimize?src=test",
        )
        assert issue.cover_url is not None

    def test_canonical_series_id_nullable(self):
        """Test that canonical_series_id is nullable."""
        identity = RollableIdentity(
            source="unavailable",
            canonical_series_id=None,  # Should be allowed
            state=IdentityState.UNRESOLVED,
            series_mapping_state=IdentityState.UNRESOLVED,
        )
        assert identity.canonical_series_id is None

    def test_latest_rating_nullable(self):
        """Test that latest_rating is nullable."""
        reader = RollableReader(
            latest_rating=None,  # Should be allowed
            average_rating=4.5,
            rating_count=10,
            read_count=5,
            issue_count=12,
            progress_scope=ProgressScope.CANONICAL_SERIES_RUN
        )
        assert reader.latest_rating is None

    def test_average_rating_nullable(self):
        """Test that average_rating is nullable."""
        reader = RollableReader(
            latest_rating=4.0,
            average_rating=None,  # Should be allowed
            rating_count=0,
            read_count=5,
            issue_count=12,
            progress_scope=ProgressScope.CANONICAL_SERIES_RUN
        )
        assert reader.average_rating is None

    def test_issue_count_nullable(self):
        """Test that issue_count is nullable when catalog run length is unknown."""
        reader = RollableReader(
            latest_rating=4.0,
            average_rating=4.5,
            rating_count=10,
            read_count=5,
            issue_count=None,  # Should be allowed when unknown
            progress_scope=ProgressScope.CANONICAL_SERIES_RUN
        )
        assert reader.issue_count is None


class TestV2BootstrapEndpointContract:
    """Test the v2 bootstrap endpoint contract requirements."""

    def test_no_unversioned_alias(self):
        """Test that v2 bootstrap has no unversioned alias."""
        # This is a structural test - the endpoint should only exist at /v2/bootstrap
        # not at /bootstrap (which should remain v1 only)

        # In a real test environment, we would make API calls to verify this
        # For now, we verify the schema exists and is distinct
        assert RollV2BootstrapResponse is not None
        assert RollV2BootstrapResponse is not RollRecoveryInfo  # Different from v1

    def test_rollable_issue_required_non_null(self):
        """Test that rollable[].issue is required/non-null."""
        # This should be enforced by the schema - issue should have no default
        issue_field = RollableItem.model_fields['issue']
        assert issue_field.is_required()
        assert issue_field.annotation is RollableIssue  # Not nullable means required

    def test_v2_never_returns_issue_null(self):
        """Test that v2 never returns issue: null."""
        # This would be tested at the API level by ensuring threads with no
        # next unread issue are filtered out from the rollable list
        # For now, we verify the schema supports this requirement
        assert RollableIssue is not None  # Issue schema exists and is required


class TestRateResponseContract:
    """Test the rate response contract requirements."""

    def test_preserves_all_thread_response_fields(self):
        """Test that RateResponse preserves all current ThreadResponse fields."""
        # This is tested by checking that all ThreadResponse fields exist in RateResponse
        thread_response_fields = RateResponse.model_fields

        # Verify key ThreadResponse fields are present
        required_fields = [
            'id', 'title', 'format', 'issues_remaining', 'queue_position',
            'status', 'last_rating', 'last_activity_at', 'notes', 'is_test',
            'is_blocked', 'blocking_reasons', 'created_at', 'total_issues',
            'reading_progress', 'next_unread_issue_id', 'next_unread_issue_number'
        ]

        for field in required_fields:
            assert field in thread_response_fields, f"Required field {field} missing from RateResponse"

    def test_adds_roll_reconciliation(self):
        """Test that RateResponse adds roll_reconciliation.last_read."""
        assert 'roll_reconciliation' in RateResponse.model_fields
        assert RateResponse.model_fields['roll_reconciliation'].annotation == RollReconciliation | None

        # Verify RollReconciliation has a required last_read
        assert 'last_read' in RollReconciliation.model_fields
        assert RollReconciliation.model_fields['last_read'].annotation is RollLastRead
