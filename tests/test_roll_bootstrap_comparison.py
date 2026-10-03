"""Test module for roll bootstrap parity comparison.

This module provides comprehensive test scenarios and utilities for proving
parity, performance, and migration observability between v1 and v2 roll bootstrap APIs.

Issue #2718: Roll v2: prove parity, performance, and migration observability
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.config import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.models.session import ReadingSession
from app.models.thread import Thread
from app.models.issue import Issue
from app.services.roll_bootstrap_comparison import (
    RollBootstrapComparisonHarness,
    ComparisonScenario,
    ParityReport,
    PerformanceMetrics,
)
from app.schemas.roll import RollBootstrapResponse
from app.schemas.roll_v2 import RollV2BootstrapResponse

logger = logging.getLogger(__name__)


class RollBootstrapTestFixtures:
    """Test fixtures for roll bootstrap comparison scenarios."""
    
    def __init__(self, db_session):
        self.db_session = db_session
        self.test_user = None
        self.test_session = None
        self.test_threads = []
        self.test_issues = []
    
    async def setup_empty_pool_scenario(self) -> Tuple[User, ReadingSession]:
        """Set up test scenario with empty roll pool."""
        # Create test user
        self.test_user = User(
            username="test_user_empty",
            email="test@example.com",
            hashed_password="hashed_password",
            is_active=True,
        )
        self.db_session.add(self.test_user)
        await self.db_session.commit()
        await self.db_session.refresh(self.test_user)
        
        # Create test session
        self.test_session = ReadingSession(
            user_id=self.test_user.id,
            predicted_bandwidth="balanced",
            active_bandwidth="balanced",
            predicted_intent="balanced", 
            active_intent="balanced",
        )
        self.db_session.add(self.test_session)
        await self.db_session.commit()
        await self.db_session.refresh(self.test_session)
        
        return self.test_user, self.test_session
    
    async def setup_normal_pool_scenario(self) -> Tuple[User, ReadingSession, List[Thread], List[Issue]]:
        """Set up test scenario with normal roll pool."""
        # Create test user and session
        self.test_user, self.test_session = await self.setup_empty_pool_scenario()
        
        # Create test threads with issues
        self.test_threads = []
        self.test_issues = []
        
        for i in range(5):
            issue = Issue(
                number=f"#{i+1}",
                title=f"Test Issue {i+1}",
                series_id=f"series-{i}",
                series_title=f"Test Series {i}",
                cover_url=f"/api/v1/images/optimize?hash=test{i}",
                provider_volume_count=10 + i,
                provider_volume_index=i + 1,
            )
            self.db_session.add(issue)
            self.test_issues.append(issue)
        
        await self.db_session.commit()
        
        for i, issue in enumerate(self.test_issues):
            thread = Thread(
                user_id=self.test_user.id,
                title=f"Test Thread {i+1}",
                format="comic",
                next_unread_issue_id=issue.id,
                last_activity_at=datetime.now(timezone.utc) - timedelta(hours=i),
                snoozed=False,
                skipped=False,
                blocked=False,
            )
            self.db_session.add(thread)
            self.test_threads.append(thread)
        
        await self.db_session.commit()
        
        return self.test_user, self.test_session, self.test_threads, self.test_issues
    
    async def setup_d100_pool_scenario(self) -> Tuple[User, ReadingSession, List[Thread], List[Issue]]:
        """Set up test scenario with d100 roll pool (100 threads)."""
        # Create test user and session
        self.test_user, self.test_session = await self.setup_empty_pool_scenario()
        
        # Create 100 test threads with issues
        self.test_threads = []
        self.test_issues = []
        
        for i in range(100):
            issue = Issue(
                number=f"#{i+1}",
                title=f"Test Issue {i+1}",
                series_id=f"series-{i % 10}",  # 10 different series
                series_title=f"Test Series {i % 10}",
                cover_url=f"/api/v1/images/optimize?hash=test{i}",
                provider_volume_count=20 + (i % 10),
                provider_volume_index=(i % 10) + 1,
            )
            self.db_session.add(issue)
            self.test_issues.append(issue)
        
        await self.db_session.commit()
        
        for i, issue in enumerate(self.test_issues):
            thread = Thread(
                user_id=self.test_user.id,
                title=f"Test Thread {i+1}",
                format="comic",
                next_unread_issue_id=issue.id,
                last_activity_at=datetime.now(timezone.utc) - timedelta(hours=i),
                snoozed=False,
                skipped=False,
                blocked=False,
            )
            self.db_session.add(thread)
            self.test_threads.append(thread)
        
        await self.db_session.commit()
        
        return self.test_user, self.test_session, self.test_threads, self.test_issues
    
    async def setup_pending_state_scenario(self) -> Tuple[User, ReadingSession, Thread]:
        """Set up test scenario with pending roll state."""
        # Create test user and session
        self.test_user, self.test_session = await self.setup_empty_pool_scenario()
        
        # Create test thread and issue
        issue = Issue(
            number="#1",
            title="Test Issue",
            series_id="series-1",
            series_title="Test Series",
            cover_url="/api/v1/images/optimize?hash=test1",
            provider_volume_count=10,
            provider_volume_index=1,
        )
        self.db_session.add(issue)
        await self.db_session.commit()
        
        thread = Thread(
            user_id=self.test_user.id,
            title="Test Thread",
            format="comic",
            next_unread_issue_id=issue.id,
            last_activity_at=datetime.now(timezone.utc),
            snoozed=False,
            skipped=False,
            blocked=False,
        )
        self.db_session.add(thread)
        await self.db_session.commit()
        
        # Set pending thread
        self.test_session.pending_thread_id = thread.id
        await self.db_session.commit()
        
        self.test_threads = [thread]
        self.test_issues = [issue]
        
        return self.test_user, self.test_session, thread
    
    async def setup_recovery_state_scenario(self) -> Tuple[User, ReadingSession, Thread]:
        """Set up test scenario with roll recovery state."""
        # Create test user and session
        self.test_user, self.test_session = await self.setup_empty_pool_scenario()
        
        # Create test thread and issue
        issue = Issue(
            number="#1",
            title="Test Issue",
            series_id="series-1",
            series_title="Test Series",
            cover_url="/api/v1/images/optimize?hash=test1",
            provider_volume_count=10,
            provider_volume_index=1,
        )
        self.db_session.add(issue)
        await self.db_session.commit()
        
        thread = Thread(
            user_id=self.test_user.id,
            title="Test Thread",
            format="comic",
            next_unread_issue_id=issue.id,
            last_activity_at=datetime.now(timezone.utc),
            snoozed=False,
            skipped=False,
            blocked=False,
        )
        self.db_session.add(thread)
        await self.db_session.commit()
        
        # Set pending thread and recovery state
        self.test_session.pending_thread_id = thread.id
        await self.db_session.commit()
        
        self.test_threads = [thread]
        self.test_issues = [issue]
        
        return self.test_user, self.test_session, thread
    
    async def cleanup(self):
        """Clean up test fixtures."""
        if self.test_threads:
            for thread in self.test_threads:
                await self.db_session.delete(thread)
        
        if self.test_issues:
            for issue in self.test_issues:
                await self.db_session.delete(issue)
        
        if self.test_session:
            await self.db_session.delete(self.test_session)
        
        if self.test_user:
            await self.db_session.delete(self.test_user)
        
        await self.db_session.commit()


class RollBootstrapComparisonTester:
    """Main test class for roll bootstrap comparison."""
    
    def __init__(self, app, db_pool):
        self.app = app
        self.db_pool = db_pool
        self.harness = RollBootstrapComparisonHarness(app, db_pool)
        self.fixtures = None
    
    async def run_all_scenarios(self) -> Dict[str, ParityReport]:
        """Run comparison across all test scenarios."""
        
        results = {}
        
        scenarios = [
            ComparisonScenario.EMPTY_POOL,
            ComparisonScenario.NORMAL_POOL,
            ComparisonScenario.D100_POOL,
            ComparisonScenario.PENDING_STATE,
            ComparisonScenario.RECOVERY_STATE,
        ]
        
        async with self.db_pool.acquire() as conn:
            self.fixtures = RollBootstrapTestFixtures(conn)
            
            for scenario in scenarios:
                try:
                    logger.info(f"Running scenario: {scenario.value}")
                    report = await self.run_scenario(scenario)
                    results[scenario.value] = report
                    
                    # Log summary
                    logger.info(f"Scenario {scenario.value}: "
                              f"Parity={report.overall_parity}, "
                              f"V2 Valid={report.v2_validation_passed}, "
                              f"DB Trips V1={report.v1_metrics.db_round_trips_after_auth}, "
                              f"DB Trips V2={report.v2_metrics.db_round_trips_after_auth}")
                    
                except Exception as e:
                    logger.error(f"Failed scenario {scenario.value}: {e}")
                    results[scenario.value] = {
                        "error": str(e),
                        "scenario": scenario.value,
                        "timestamp": datetime.now(timezone.utc),
                    }
            
            await self.fixtures.cleanup()
        
        return results
    
    async def run_scenario(self, scenario: ComparisonScenario) -> ParityReport:
        """Run comparison for a specific scenario."""
        
        # Set up scenario
        if scenario == ComparisonScenario.EMPTY_POOL:
            user, session = await self.fixtures.setup_empty_pool_scenario()
        elif scenario == ComparisonScenario.NORMAL_POOL:
            user, session, threads, issues = await self.fixtures.setup_normal_pool_scenario()
        elif scenario == ComparisonScenario.D100_POOL:
            user, session, threads, issues = await self.fixtures.setup_d100_pool_scenario()
        elif scenario == ComparisonScenario.PENDING_STATE:
            user, session, thread = await self.fixtures.setup_pending_state_scenario()
        elif scenario == ComparisonScenario.RECOVERY_STATE:
            user, session, thread = await self.fixtures.setup_recovery_state_scenario()
        else:
            raise ValueError(f"Unknown scenario: {scenario}")
        
        # Create access token
        access_token = create_access_token(data={"sub": user.username})
        user.access_token = access_token
        
        # Run comparison
        report = await self.harness.compare_bootstrap_responses(
            user=user,
            scenario=scenario,
            timezone_str="America/Chicago"
        )
        
        return report
    
    async def validate_performance_contract(self, report: ParityReport) -> Dict[str, Any]:
        """Validate that performance contract is met."""
        
        validation = {
            "contract_met": True,
            "violations": [],
            "details": {}
        }
        
        # Check v1 performance
        v1_trips = report.v1_metrics.db_round_trips_after_auth
        v1_contract_met = 1 <= v1_trips <= 3
        validation["details"]["v1_round_trips"] = v1_trips
        validation["details"]["v1_contract_met"] = v1_contract_met
        
        if not v1_contract_met:
            validation["violations"].append(f"V1 exceeds 1-3 round trip contract: {v1_trips}")
        
        # Check v2 performance
        v2_trips = report.v2_metrics.db_round_trips_after_auth
        v2_contract_met = 1 <= v2_trips <= 3
        validation["details"]["v2_round_trips"] = v2_trips
        validation["details"]["v2_contract_met"] = v2_contract_met
        
        if not v2_contract_met:
            validation["violations"].append(f"V2 exceeds 1-3 round trip contract: {v2_trips}")
        
        # Check that v2 doesn't regress v1 performance significantly
        if v2_trips > v1_trips + 1:
            validation["violations"].append(f"V2 regresses v1 performance by {v2_trips - v1_trips} trips")
        
        validation["contract_met"] = len(validation["violations"]) == 0
        
        return validation
    
    async def generate_comparison_summary(self, results: Dict[str, ParityReport]) -> Dict[str, Any]:
        """Generate a comprehensive summary of all comparison results."""
        
        summary = {
            "timestamp": datetime.now(timezone.utc),
            "scenarios": {},
            "overall": {
                "total_scenarios": len(results),
                "passed_scenarios": 0,
                "failed_scenarios": 0,
                "performance_contract_met": True,
                "parity_contract_met": True,
            },
            "recommendations": []
        }
        
        total_performance_violations = 0
        
        for scenario_name, result in results.items():
            if isinstance(result, dict) and "error" in result:
                # Scenario failed with error
                summary["scenarios"][scenario_name] = {
                    "status": "error",
                    "error": result["error"],
                    "parity": False,
                    "performance": False,
                }
                summary["overall"]["failed_scenarios"] += 1
            else:
                # Successful scenario
                scenario_summary = {
                    "status": "completed",
                    "parity": result.overall_parity,
                    "performance": result.v2_metrics.db_round_trips_after_auth <= 3,
                    "v2_validation": result.v2_validation_passed,
                    "db_round_trips_v1": result.v1_metrics.db_round_trips_after_auth,
                    "db_round_trips_v2": result.v2_metrics.db_round_trips_after_auth,
                    "response_time_ms_v1": result.v1_metrics.response_time_ms,
                    "response_time_ms_v2": result.v2_metrics.response_time_ms,
                    "response_size_bytes_v1": result.v1_metrics.response_size_bytes,
                    "response_size_bytes_v2": result.v2_metrics.response_size_bytes,
                    "critical_failures": len(result.critical_failures),
                    "v2_enrichment_count": len(result.v2_only_enrichment),
                }
                
                summary["scenarios"][scenario_name] = scenario_summary
                
                if scenario_summary["parity"] and scenario_summary["performance"] and scenario_summary["v2_validation"]:
                    summary["overall"]["passed_scenarios"] += 1
                else:
                    summary["overall"]["failed_scenarios"] += 1
                
                total_performance_violations += max(0, result.v2_metrics.db_round_trips_after_auth - 3)
        
        # Overall assessment
        if summary["overall"]["failed_scenarios"] > 0:
            summary["overall"]["parity_contract_met"] = False
        
        if total_performance_violations > 0:
            summary["overall"]["performance_contract_met"] = False
        
        # Generate recommendations
        if summary["overall"]["failed_scenarios"] > 0:
            summary["recommendations"].append(
                f"Address {summary['overall']['failed_scenarios']} failed scenarios before production cutover"
            )
        
        if total_performance_violations > 0:
            summary["recommendations"].append(
                f"Optimize database queries to meet 1-3 round trip contract in {total_performance_violations} scenarios"
            )
        
        return summary


# Test functions for pytest
@pytest.mark.asyncio
async def test_bootstrap_parity_empty_pool(app, db_pool):
    """Test v1/v2 parity with empty roll pool."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    results = await tester.run_scenario(ComparisonScenario.EMPTY_POOL)
    
    assert isinstance(results, ParityReport)
    assert results.overall_parity
    assert results.v2_validation_passed
    assert results.v1_metrics.db_round_trips_after_auth <= 3
    assert results.v2_metrics.db_round_trips_after_auth <= 3


@pytest.mark.asyncio 
async def test_bootstrap_parity_normal_pool(app, db_pool):
    """Test v1/v2 parity with normal roll pool."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    results = await tester.run_scenario(ComparisonScenario.NORMAL_POOL)
    
    assert isinstance(results, ParityReport)
    assert results.overall_parity
    assert results.v2_validation_passed
    assert results.v1_metrics.db_round_trips_after_auth <= 3
    assert results.v2_metrics.db_round_trips_after_auth <= 3


@pytest.mark.asyncio
async def test_bootstrap_parity_d100_pool(app, db_pool):
    """Test v1/v2 parity with d100 roll pool."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    results = await tester.run_scenario(ComparisonScenario.D100_POOL)
    
    assert isinstance(results, ParityReport)
    assert results.overall_parity
    assert results.v2_validation_passed
    assert results.v1_metrics.db_round_trips_after_auth <= 3
    assert results.v2_metrics.db_round_trips_after_auth <= 3


@pytest.mark.asyncio
async def test_bootstrap_performance_contract(app, db_pool):
    """Test that both v1 and v2 meet the 1-3 DB round trip contract."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    
    # Test normal pool scenario
    user, session, threads, issues = await tester.fixtures.setup_normal_pool_scenario()
    access_token = create_access_token(data={"sub": user.username})
    user.access_token = access_token
    
    report = await tester.harness.compare_bootstrap_responses(
        user=user,
        scenario=ComparisonScenario.NORMAL_POOL,
        timezone_str="America/Chicago"
    )
    
    # Validate performance contract
    validation = await tester.validate_performance_contract(report)
    
    assert validation["contract_met"]
    assert validation["details"]["v1_contract_met"]
    assert validation["details"]["v2_contract_met"]
    assert validation["details"]["v1_round_trips"] <= 3
    assert validation["details"]["v2_round_trips"] <= 3
    
    await tester.fixtures.cleanup()


@pytest.mark.asyncio
async def test_bootstrap_v2_validation(app, db_pool):
    """Test v2-specific validation rules."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    
    # Set up scenario
    user, session, threads, issues = await tester.fixtures.setup_normal_pool_scenario()
    access_token = create_access_token(data={"sub": user.username})
    user.access_token = access_token
    
    report = await tester.harness.compare_bootstrap_responses(
        user=user,
        scenario=ComparisonScenario.NORMAL_POOL,
        timezone_str="America/Chicago"
    )
    
    # Check v2 validation passed
    assert report.v2_validation_passed
    assert len(report.v2_validation_errors) == 0
    
    # Check that v2 has enrichment
    assert len(report.v2_only_enrichment) > 0
    
    await tester.fixtures.cleanup()


@pytest.mark.asyncio
async def test_bootstrap_observability_distinction(app, db_pool):
    """Test that v1 and v2 endpoints are properly distinguished for observability."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    
    # Set up scenario
    user, session, threads, issues = await tester.fixtures.setup_normal_pool_scenario()
    access_token = create_access_token(data={"sub": user.username})
    user.access_token = access_token
    
    # Test that we can call both endpoints
    client = TestClient(app)
    
    # V1 endpoint
    v1_response = client.get(
        "/api/v1/roll/bootstrap",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"timezone": "America/Chicago"}
    )
    assert v1_response.status_code == 200
    
    # V2 endpoint  
    v2_response = client.get(
        "/api/v2/roll/bootstrap",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"timezone": "America/Chicago"}
    )
    assert v2_response.status_code == 200
    
    # Verify different response structures
    v1_data = v1_response.json()
    v2_data = v2_response.json()
    
    assert "roll_pool" in v1_data
    assert "rollable" in v2_data
    assert "last_read" in v2_data
    assert "roll_pool" not in v2_data
    
    await tester.fixtures.cleanup()


# Integration test for comprehensive validation
@pytest.mark.asyncio
async def test_bootstrap_comprehensive_validation(app, db_pool):
    """Run comprehensive validation across all scenarios."""
    tester = RollBootstrapComparisonTester(app, db_pool)
    
    # Run all scenarios
    results = await tester.run_all_scenarios()
    
    # Generate summary
    summary = await tester.generate_comparison_summary(results)
    
    # Validate results
    assert summary["overall"]["total_scenarios"] == 5
    assert len(summary["scenarios"]) == 5
    
    # Check that we have meaningful results
    for scenario_name, scenario_result in summary["scenarios"].items():
        if scenario_result["status"] == "completed":
            assert isinstance(scenario_result["db_round_trips_v1"], int)
            assert isinstance(scenario_result["db_round_trips_v2"], int)
            assert scenario_result["db_round_trips_v1"] >= 0
            assert scenario_result["db_round_trips_v2"] >= 0
    
    # Print summary for debugging
    logger.info(f"Comprehensive validation summary: {json.dumps(summary, indent=2, default=str)}")
    
    # Return results for further analysis
    return {
        "results": results,
        "summary": summary,
        "performance_contract_met": summary["overall"]["performance_contract_met"],
        "parity_contract_met": summary["overall"]["parity_contract_met"],
    }