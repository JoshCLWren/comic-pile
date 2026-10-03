"""Roll bootstrap parity comparison and validation harness.

This module provides a comprehensive comparison harness for proving parity,
performance, and migration observability between v1 and v2 roll bootstrap APIs.

Issue #2718: Roll v2: prove parity, performance, and migration observability
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, validator

from app.api.roll import roll_router, v2_router
from app.core.auth import get_current_user
from app.core.config import get_db
from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.roll import RollBootstrapResponse, RollBootstrapThread
from app.schemas.roll_v2 import (
    RollV2BootstrapResponse,
    RollableItem,
    RollableThread,
    RollableIssue,
    RollableIdentity,
    RollableReader,
    RollableRoute,
    RollLastRead,
    IdentityState,
    ProgressScope,
    RouteKind,
)


class ComparisonScenario(Enum):
    """Test scenarios for bootstrap comparison."""
    
    EMPTY_POOL = "empty_pool"
    NORMAL_POOL = "normal_pool" 
    D100_POOL = "d100_pool"
    PENDING_STATE = "pending_state"
    RECOVERY_STATE = "recovery_state"


class PerformanceMetrics(BaseModel):
    """Performance measurement results."""
    
    endpoint: str
    scenario: ComparisonScenario
    total_round_trips: int
    query_count: int
    response_time_ms: float
    response_size_bytes: int
    db_round_trips_after_auth: int


class ParityCheck(BaseModel):
    """Individual parity check result."""
    
    field_path: str
    v1_value: Any
    v2_value: Any
    is_equal: bool
    notes: str = ""


class ParityReport(BaseModel):
    """Complete parity comparison report."""
    
    session_id: int
    user_id: int
    scenario: ComparisonScenario
    timestamp: datetime
    
    # Core parity fields
    pool_membership_match: bool
    ordering_match: bool
    next_issue_match: bool
    die_state_match: bool
    session_mode_match: bool
    active_thread_match: bool
    recovery_state_match: bool
    summary_counts_match: bool
    timezone_match: bool
    
    # Detailed comparisons
    parity_checks: List[ParityCheck]
    v1_only_differences: List[str]
    v2_only_enrichment: List[str]
    
    # Performance metrics
    v1_metrics: PerformanceMetrics
    v2_metrics: PerformanceMetrics
    
    # Validation results
    v2_validation_passed: bool
    v2_validation_errors: List[str]
    
    # Summary
    overall_parity: bool
    critical_failures: List[str]


class RollBootstrapComparisonHarness:
    """Comprehensive comparison harness for v1 and v2 roll bootstrap APIs."""
    
    def __init__(self, app: FastAPI, db_pool: asyncpg.Pool):
        self.app = app
        self.db_pool = db_pool
        self.client = TestClient(app)
        
    async def compare_bootstrap_responses(
        self, 
        user: User, 
        scenario: ComparisonScenario,
        timezone_str: Optional[str] = None
    ) -> ParityReport:
        """Compare v1 and v2 bootstrap responses for a given scenario."""
        
        start_time = time.time()
        
        # Get v1 response
        v1_metrics = await self._measure_endpoint_performance(
            "/api/v1/roll/bootstrap", user, timezone_str
        )
        
        # Get v2 response  
        v2_metrics = await self._measure_endpoint_performance(
            "/api/v2/roll/bootstrap", user, timezone_str
        )
        
        # Parse responses
        v1_response = RollBootstrapResponse.model_validate(v1_metrics.response_data)
        v2_response = RollV2BootstrapResponse.model_validate(v2_metrics.response_data)
        
        # Perform parity checks
        parity_checks = await self._run_parity_checks(v1_response, v2_response)
        
        # Validate v2-specific enrichment
        v2_validation = await self._validate_v2_enrichment(v2_response)
        
        # Generate comprehensive report
        report = ParityReport(
            session_id=v1_response.session_id,
            user_id=user.id,
            scenario=scenario,
            timestamp=datetime.now(timezone.utc),
            
            # Core parity field checks
            pool_membership_match=self._check_pool_membership(v1_response, v2_response),
            ordering_match=self._check_ordering(v1_response, v2_response),
            next_issue_match=self._check_next_issue_parity(v1_response, v2_response),
            die_state_match=self._check_die_state_parity(v1_response, v2_response),
            session_mode_match=self._check_session_mode_parity(v1_response, v2_response),
            active_thread_match=self._check_active_thread_parity(v1_response, v2_response),
            recovery_state_match=self._check_recovery_state_parity(v1_response, v2_response),
            summary_counts_match=self._check_summary_counts_parity(v1_response, v2_response),
            timezone_match=self._check_timezone_parity(v1_response, v2_response),
            
            parity_checks=parity_checks,
            v1_only_differences=self._identify_v1_only_differences(v1_response, v2_response),
            v2_only_enrichment=self._identify_v2_only_enrichment(v1_response, v2_response),
            
            v1_metrics=v1_metrics,
            v2_metrics=v2_metrics,
            
            v2_validation_passed=v2_validation["passed"],
            v2_validation_errors=v2_validation["errors"],
            
            overall_parity=all(check.is_equal for check in parity_checks),
            critical_failures=self._identify_critical_failures(parity_checks, v2_validation)
        )
        
        return report
    
    async def _measure_endpoint_performance(
        self, 
        endpoint: str, 
        user: User, 
        timezone_str: Optional[str] = None
    ) -> PerformanceMetrics:
        """Measure performance characteristics of an endpoint."""
        
        headers = {"Authorization": f"Bearer {user.access_token}"}
        params = {}
        if timezone_str:
            params["timezone"] = timezone_str
            
        start_time = time.time()
        
        # Track database queries (this is a simplified approach)
        # In production, you'd want to use database query logging
        initial_query_count = await self._get_current_query_count()
        
        response = self.client.get(endpoint, headers=headers, params=params)
        response.raise_for_status()
        
        end_time = time.time()
        response_data = response.json()
        
        final_query_count = await self._get_current_query_count()
        
        return PerformanceMetrics(
            endpoint=endpoint,
            scenario=ComparisonScenario.NORMAL_POOL,  # Default, will be overridden
            total_round_trips=1,  # HTTP round trips
            query_count=final_query_count - initial_query_count,
            response_time_ms=(end_time - start_time) * 1000,
            response_size_bytes=len(response.content),
            db_round_trips_after_auth=final_query_count - initial_query_count
        )
    
    async def _get_current_query_count(self) -> int:
        """Get current database query count (simplified implementation)."""
        # This is a placeholder - in production you'd track actual query counts
        # through database monitoring or connection pool statistics
        return 0
    
    async def _run_parity_checks(
        self, 
        v1_response: RollBootstrapResponse, 
        v2_response: RollV2BootstrapResponse
    ) -> List[ParityCheck]:
        """Run detailed parity checks between v1 and v2 responses."""
        
        checks = []
        
        # Session state parity
        checks.extend(self._check_session_state_parity(v1_response, v2_response))
        
        # Pool/rollable content parity
        checks.extend(self._check_pool_content_parity(v1_response, v2_response))
        
        # Summary counts parity
        checks.extend(self._check_summary_parity(v1_response, v2_response))
        
        # Active thread parity
        checks.extend(self._check_active_thread_parity_detailed(v1_response, v2_response))
        
        return checks
    
    def _check_session_state_parity(
        self, 
        v1_response: RollBootstrapResponse, 
        v2_response: RollV2BootstrapResponse
    ) -> List[ParityCheck]:
        """Check session state fields for parity."""
        
        checks = []
        
        # Core session fields
        session_fields = [
            ("session_id", v1_response.session_id, v2_response.session_id),
            ("user_id", v1_response.user_id, v2_response.user_id),
            ("current_die", v1_response.current_die, v2_response.current_die),
            ("manual_die", v1_response.manual_die, v2_response.manual_die),
            ("pending_thread_id", v1_response.pending_thread_id, v2_response.pending_thread_id),
            ("last_rolled_result", v1_response.last_rolled_result, v2_response.last_rolled_result),
        ]
        
        for field_name, v1_val, v2_val in session_fields:
            checks.append(ParityCheck(
                field_path=f"session.{field_name}",
                v1_value=v1_val,
                v2_value=v2_val,
                is_equal=v1_val == v2_val,
                notes=f"Session {field_name} comparison"
            ))
        
        # Session mode comparison
        v1_mode = v1_response.session_mode
        v2_mode = v2_response.session_mode
        
        mode_fields = [
            ("active_bandwidth", v1_mode.active_bandwidth, v2_mode.active_bandwidth),
            ("predicted_bandwidth", v1_mode.predicted_bandwidth, v2_mode.predicted_bandwidth),
            ("active_intent", v1_mode.active_intent, v2_mode.active_intent),
            ("predicted_intent", v1_mode.predicted_intent, v2_mode.predicted_intent),
        ]
        
        for field_name, v1_val, v2_val in mode_fields:
            checks.append(ParityCheck(
                field_path=f"session_mode.{field_name}",
                v1_value=v1_val,
                v2_value=v2_val,
                is_equal=v1_val == v2_val,
                notes=f"Session mode {field_name} comparison"
            ))
        
        return checks
    
    def _check_pool_content_parity(
        self, 
        v1_response: RollBootstrapResponse, 
        v2_response: RollV2BootstrapResponse
    ) -> List[ParityCheck]:
        """Check pool/rollable content for parity."""
        
        checks = []
        
        # Extract thread IDs for comparison
        v1_thread_ids = {thread.id for thread in v1_response.roll_pool}
        v2_thread_ids = {item.thread.id for item in v2_response.rollable}
        
        # Pool membership check
        checks.append(ParityCheck(
            field_path="pool_membership",
            v1_value=sorted(v1_thread_ids),
            v2_value=sorted(v2_thread_ids),
            is_equal=v1_thread_ids == v2_thread_ids,
            notes="Roll pool membership comparison - should match exactly"
        ))
        
        # Ordering check (by thread ID)
        v1_ordered_ids = [thread.id for thread in v1_response.roll_pool]
        v2_ordered_ids = [item.thread.id for item in v2_response.rollable]
        
        checks.append(ParityCheck(
            field_path="pool_ordering",
            v1_value=v1_ordered_ids,
            v2_value=v2_ordered_ids,
            is_equal=v1_ordered_ids == v2_ordered_ids,
            notes="Pool ordering comparison - should match exactly"
        ))
        
        # Next issue parity check
        v1_next_issues = [
            (thread.id, thread.issue_id, thread.issue_number) 
            for thread in v1_response.roll_pool 
            if thread.issue_id is not None
        ]
        
        v2_next_issues = [
            (item.thread.id, item.issue.id, item.issue.number) 
            for item in v2_response.rollable 
            if item.issue.id is not None
        ]
        
        checks.append(ParityCheck(
            field_path="next_issues",
            v1_value=v1_next_issues,
            v2_value=v2_next_issues,
            is_equal=v1_next_issues == v2_next_issues,
            notes="Next issue ID/number comparison - should match exactly"
        ))
        
        return checks
    
    def _check_summary_parity(
        self, 
        v1_response: RollBootstrapResponse, 
        v2_response: RollV2BootstrapResponse
    ) -> List[ParityCheck]:
        """Check summary counts and collections for parity."""
        
        checks = []
        
        summary_fields = [
            ("snoozed_count", v1_response.snoozed_count, v2_response.snoozed_count),
            ("blocked_count", v1_response.blocked_count, v2_response.blocked_count),
            ("stale_thread_count", v1_response.stale_thread_count, v2_response.stale_thread_count),
        ]
        
        for field_name, v1_val, v2_val in summary_fields:
            checks.append(ParityCheck(
                field_path=f"summary.{field_name}",
                v1_value=v1_val,
                v2_value=v2_val,
                is_equal=v1_val == v2_val,
                notes=f"Summary count {field_name} comparison"
            ))
        
        # Skipped thread IDs comparison
        checks.append(ParityCheck(
            field_path="skipped_thread_ids",
            v1_value=sorted(v1_response.skipped_thread_ids),
            v2_value=sorted(v2_response.skipped_thread_ids),
            is_equal=sorted(v1_response.skipped_thread_ids) == sorted(v2_response.skipped_thread_ids),
            notes="Skipped thread IDs comparison"
        ))
        
        return checks
    
    async def _validate_v2_enrichment(self, v2_response: RollV2BootstrapResponse) -> Dict[str, Any]:
        """Validate v2-specific enrichment fields against source data."""
        
        errors = []
        
        # Validate cover URLs are same-origin
        for item in v2_response.rollable:
            if item.issue.cover_url:
                if not item.issue.cover_url.startswith("/api/v1/images/optimize"):
                    errors.append(f"Invalid cover URL for thread {item.thread.id}: {item.issue.cover_url}")
        
        # Validate route kinds are bounded to "group"
        for item in v2_response.rollable:
            for route in item.routes:
                if route.kind != RouteKind.GROUP:
                    errors.append(f"Invalid route kind {route.kind} for thread {item.thread.id}")
        
        # Validate identity states are valid
        valid_states = {IdentityState.CONFIRMED, IdentityState.CANDIDATE, 
                       IdentityState.UNRESOLVED, IdentityState.AMBIGUOUS, IdentityState.CONFLICTING}
        
        for item in v2_response.rollable:
            if item.identity.state not in valid_states:
                errors.append(f"Invalid identity state {item.identity.state} for thread {item.thread.id}")
        
        # Validate progress scope values
        valid_scopes = {ProgressScope.CANONICAL_SERIES_RUN, ProgressScope.THREAD}
        
        for item in v2_response.rollable:
            if item.reader.progress_scope not in valid_scopes:
                errors.append(f"Invalid progress scope {item.reader.progress_scope} for thread {item.thread.id}")
        
        return {
            "passed": len(errors) == 0,
            "errors": errors
        }
    
    def _identify_v1_only_differences(
        self, 
        v1_response: RollBootstrapResponse, 
        v2_response: RollV2BootstrapResponse
    ) -> List[str]:
        """Identify fields that exist only in v1."""
        
        differences = []
        
        # v1 has roll_pool, v2 has rollable
        if v1_response.roll_pool and not v2_response.rollable:
            differences.append("v1 has roll_pool but v2 has empty rollable")
        
        return differences
    
    def _identify_v2_only_enrichment(
        self, 
        v1_response: RollBootstrapResponse, 
        v2_response: RollV2BootstrapResponse
    ) -> List[str]:
        """Identify v2-specific enrichment fields."""
        
        enrichment = []
        
        # v2 adds last_read field
        if v2_response.last_read is not None:
            enrichment.append("last_read session-scoped reading context")
        
        # v2 adds rich identity information
        for item in v2_response.rollable:
            if item.identity.state != IdentityState.UNRESOLVED:
                enrichment.append(f"Identity resolution for thread {item.thread.id}")
            
            if item.reader.latest_rating is not None:
                enrichment.append(f"Reader context (ratings) for thread {item.thread.id}")
            
            if item.routes:
                enrichment.append(f"Route information for thread {item.thread.id}")
        
        return enrichment
    
    def _identify_critical_failures(
        self, 
        parity_checks: List[ParityCheck], 
        v2_validation: Dict[str, Any]
    ) -> List[str]:
        """Identify critical failures that block parity."""
        
        failures = []
        
        # Check for critical parity failures
        critical_fields = [
            "session_id", "user_id", "current_die", "pending_thread_id", 
            "pool_membership", "next_issues"
        ]
        
        for check in parity_checks:
            if check.field_path.split(".")[0] in critical_fields and not check.is_equal:
                failures.append(f"Critical parity failure: {check.field_path}")
        
        # Add v2 validation errors
        failures.extend(v2_validation["errors"])
        
        return failures
    
    # Helper methods for individual parity checks
    def _check_pool_membership(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check if pool membership matches between v1 and v2."""
        v1_ids = {thread.id for thread in v1.roll_pool}
        v2_ids = {item.thread.id for item in v2.rollable}
        return v1_ids == v2_ids
    
    def _check_ordering(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check if ordering matches between v1 and v2."""
        v1_order = [thread.id for thread in v1.roll_pool]
        v2_order = [item.thread.id for item in v2.rollable]
        return v1_order == v2_order
    
    def _check_next_issue_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check next issue parity."""
        v1_issues = [(t.id, t.issue_id, t.issue_number) for t in v1.roll_pool if t.issue_id]
        v2_issues = [(i.thread.id, i.issue.id, i.issue.number) for i in v2.rollable if i.issue.id]
        return v1_issues == v2_issues
    
    def _check_die_state_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check die state parity."""
        return (v1.current_die == v2.current_die and 
                v1.manual_die == v2.manual_die)
    
    def _check_session_mode_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check session mode parity."""
        return (v1.session_mode.active_bandwidth == v2.session_mode.active_bandwidth and
                v1.session_mode.predicted_bandwidth == v2.session_mode.predicted_bandwidth and
                v1.session_mode.active_intent == v2.session_mode.active_intent and
                v1.session_mode.predicted_intent == v2.session_mode.predicted_intent)
    
    def _check_active_thread_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check active thread parity."""
        v1_active = v1.active_thread.thread_id if v1.active_thread else None
        v2_active = v2.active_thread.thread_id if v2.active_thread else None
        return v1_active == v2_active
    
    def _check_recovery_state_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check recovery state parity."""
        v1_recovery = v1.roll_recovery is not None
        v2_recovery = v2.roll_recovery is not None
        return v1_recovery == v2_recovery
    
    def _check_summary_counts_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check summary counts parity."""
        return (v1.snoozed_count == v2.snoozed_count and
                v1.blocked_count == v2.blocked_count and
                v1.stale_thread_count == v2.stale_thread_count and
                sorted(v1.skipped_thread_ids) == sorted(v2.skipped_thread_ids))
    
    def _check_timezone_parity(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> bool:
        """Check timezone parity."""
        return v1.timezone == v2.timezone
    
    def _check_active_thread_parity_detailed(self, v1: RollBootstrapResponse, v2: RollV2BootstrapResponse) -> List[ParityCheck]:
        """Detailed active thread parity checks."""
        checks = []
        
        if v1.active_thread and v2.active_thread:
            checks.append(ParityCheck(
                field_path="active_thread.thread_id",
                v1_value=v1.active_thread.thread_id,
                v2_value=v2.active_thread.thread_id,
                is_equal=v1.active_thread.thread_id == v2.active_thread.thread_id,
                notes="Active thread ID comparison"
            ))
            
            checks.append(ParityCheck(
                field_path="active_thread.title",
                v1_value=v1.active_thread.title,
                v2_value=v2.active_thread.title,
                is_equal=v1.active_thread.title == v2.active_thread.title,
                notes="Active thread title comparison"
            ))
        elif v1.active_thread is None and v2.active_thread is None:
            # Both None - this is fine
            pass
        else:
            # One is None, the other is not - this is a parity issue
            checks.append(ParityCheck(
                field_path="active_thread.existence",
                v1_value=v1.active_thread is not None,
                v2_value=v2.active_thread is not None,
                is_equal=False,
                notes="Active thread existence mismatch"
            ))
        
        return checks