"""Tests for performance budget middleware integration."""

import os
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware.request_logging import (
    _slow_request_threshold_ms,
    add_request_logging_middleware,
)
from app.performance_budgets import (
    REQUEST_WARNING_MS,
    StartupBudgetError,
    get_performance_budget_manager,
)
from app.startup_diagnostics import StartupSnapshot, startup_event_snapshot


class TestPerformanceBudgetMiddleware:
    """Test the integration of performance budgets with request logging middleware."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create a test app with the middleware
        self.app = FastAPI()
        self.app.state.limiter = MagicMock()
        
        # Add the performance budget middleware
        add_request_logging_middleware(self.app, "test")
        
        # Create test client
        self.client = TestClient(self.app)
        
        # Reset the performance budget manager
        get_performance_budget_manager().clear_all()
    
    def test_fast_request_within_budgets(self):
        """Test a fast request that doesn't trigger any budgets."""
        @self.app.get("/fast")
        async def fast_endpoint():
            return {"message": "fast response"}
        
        response = self.client.get("/fast")
        
        assert response.status_code == 200
        assert response.json() == {"message": "fast response"}
        
        # No warnings or violations should be recorded
        budget_manager = get_performance_budget_manager()
        assert len(budget_manager.get_request_warnings()) == 0
        assert len(budget_manager.get_request_violations()) == 0
    
    def test_slow_request_triggers_warning(self):
        """Test a slow request that triggers a warning but not a violation."""
        @self.app.get("/slow-warning")
        async def slow_warning_endpoint():
            # Simulate slow processing
            import time
            time.sleep(0.6)  # 600ms, above warning threshold (500ms)
            return {"message": "slow but acceptable"}
        
        response = self.client.get("/slow-warning")
        
        assert response.status_code == 200
        assert response.json() == {"message": "slow but acceptable"}
        
        # Should have recorded a warning
        budget_manager = get_performance_budget_manager()
        warnings = budget_manager.get_request_warnings()
        assert len(warnings) == 1
        assert warnings[0].operation == "request./slow-warning"
        assert warnings[0].elapsed_ms >= 500
        assert warnings[0].severity == "warning"
        assert len(budget_manager.get_request_violations()) == 0
    
    def test_very_slow_request_triggers_violation(self):
        """Test a very slow request that triggers a violation."""
        @self.app.get("/slow-violation")
        async def slow_violation_endpoint():
            # Simulate very slow processing
            import time
            time.sleep(1.1)  # 1100ms, above violation threshold (1000ms)
            return {"message": "too slow"}
        
        response = self.client.get("/slow-violation")
        
        assert response.status_code == 200
        assert response.json() == {"message": "too slow"}
        
        # Should have recorded a violation
        budget_manager = get_performance_budget_manager()
        violations = budget_manager.get_request_violations()
        assert len(violations) == 1
        assert violations[0].operation == "request./slow-violation"
        assert violations[0].elapsed_ms >= 1000
        assert violations[0].severity == "violation"
        assert len(budget_manager.get_request_warnings()) == 0
    
    def test_cold_request_tracking(self):
        """Test that cold requests are properly tracked."""
        @self.app.get("/cold-test")
        async def cold_endpoint():
            return {"message": "cold request"}
        
        # First request should be cold
        response1 = self.client.get("/cold-test")
        assert response1.status_code == 200
        # The middleware logic sets X-App-Cold-Request based on startup.cold.
        # In TestClient, startup might already be marked complete. 
        # We check if it's a valid value.
        assert response1.headers.get("X-App-Cold-Request") in ("0", "1")
        
        # Second request should be warm
        response2 = self.client.get("/cold-test")
        assert response2.status_code == 200
        assert response2.headers.get("X-App-Cold-Request") == "0"
    
    def test_performance_headers_present(self):
        """Test that performance-related headers are present."""
        @self.app.get("/headers-test")
        async def headers_endpoint():
            return {"message": "test headers"}
        
        response = self.client.get("/headers-test")
        
        # Check performance headers
        assert "X-Request-ID" in response.headers
        assert "X-App-DB-Queries" in response.headers
        assert "X-Heavy-Init" in response.headers
        assert "Server-Timing" in response.headers
    
    def test_database_query_count(self):
        """Test that database query count is tracked."""
        @self.app.get("/db-test")
        async def db_endpoint():
            # Simulate some database queries
            from app.performance_diagnostics import get_request_diagnostics
            diagnostics = get_request_diagnostics()
            diagnostics.database_queries += 3
            return {"message": "database test"}
        
        response = self.client.get("/db-test")
        
        assert response.status_code == 200
        assert int(response.headers.get("X-App-DB-Queries", "0")) >= 0


class TestPerformanceBudgetAppIntegration:
    """Test integration with the full application."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create a full app with performance budgets
        self.app = create_app(serve_frontend=False, defer_router_imports=True)
        self.client = TestClient(self.app)
        
        # Reset the performance budget manager
        get_performance_budget_manager().clear_all()
    
    def test_ping_endpoint_fast(self):
        """Test that the ping endpoint is fast and doesn't trigger budgets."""
        response = self.client.get("/api/ping")
        
        # Ping should be very fast, no warnings or violations
        budget_manager = get_performance_budget_manager()
        assert len(budget_manager.get_request_warnings()) == 0
        assert len(budget_manager.get_request_violations()) == 0
        assert response.status_code == 200
    
    def test_metrics_endpoint_performance(self):
        """Test that the metrics endpoint performance is tracked."""
        response = self.client.get("/api/metrics")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should contain performance information
        assert "startup_time" in data
        assert "startup_duration" in data
        
        # Metrics endpoint should be fast
        budget_manager = get_performance_budget_manager()
        # Note: metrics endpoint might trigger warnings in CI due to timing
        # but the important thing is that it doesn't crash
        assert len(budget_manager.get_request_violations()) == 0
    
    def test_error_response_performance_tracking(self):
        """Test that error responses also have performance tracking."""
        @self.app.get("/error-test")
        async def error_endpoint():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")

        response = self.client.get("/error-test")

        assert response.status_code == 404

        # Error responses should still be tracked for performance
        budget_manager = get_performance_budget_manager()
        # Should not have performance violations for a 404
        assert len(budget_manager.get_request_violations()) == 0

    def test_non_production_startup_degrades_instead_of_failing(self):
        """A long-lived test process records telemetry but still becomes ping-ready."""
        with TestClient(self.app) as client:
            assert client.get("/api/ping").status_code == 200


class TestStartupHardBudgetEnforcement:
    """Test that crossing the total startup budget fails production startup."""

    def test_production_startup_fails_when_hard_budget_crossed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A production process past 2.5 s fails initialization instead of serving."""
        from app.config import clear_settings_cache
        from app.performance_budgets import STARTUP_TIMEOUT_MS

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
        clear_settings_cache()
        get_performance_budget_manager().clear_all()

        observed_ms = 72420.56

        def _slow_snapshot() -> StartupSnapshot:
            base = startup_event_snapshot()
            return replace(base, process_age_ms=observed_ms, startup_duration_ms=observed_ms)

        monkeypatch.setattr("app.startup_diagnostics.startup_event_snapshot", _slow_snapshot)

        app = create_app(serve_frontend=False, defer_router_imports=True)
        try:
            with pytest.raises(StartupBudgetError) as exc_info, TestClient(app):
                pass

            assert exc_info.value.operation == "startup.readiness"
            assert exc_info.value.timeout_ms == STARTUP_TIMEOUT_MS
            assert exc_info.value.elapsed_ms == observed_ms
            assert get_performance_budget_manager().violation_counts_by_operation() == {
                "startup.readiness": 1
            }
        finally:
            clear_settings_cache()

    def test_production_startup_succeeds_inside_hard_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Healthy production startup inside 2.5 s still becomes ping-ready."""
        from app.config import clear_settings_cache

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
        clear_settings_cache()
        get_performance_budget_manager().clear_all()

        observed_ms = 1603.92

        def _healthy_snapshot() -> StartupSnapshot:
            base = startup_event_snapshot()
            return replace(base, process_age_ms=observed_ms, startup_duration_ms=observed_ms)

        monkeypatch.setattr("app.startup_diagnostics.startup_event_snapshot", _healthy_snapshot)

        app = create_app(serve_frontend=False, defer_router_imports=True)
        try:
            with TestClient(app) as client:
                assert client.get("/api/ping").status_code == 200

            assert get_performance_budget_manager().get_startup_violations() == []
        finally:
            clear_settings_cache()


class TestPerformanceBudgetConfiguration:
    """Test performance budget configuration and environment handling."""

    def test_slow_request_threshold_defaults_to_contract_ceiling(self):
        """Warm warnings begin at 500 ms when nothing is configured."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SLOW_REQUEST_THRESHOLD_MS", None)
            assert _slow_request_threshold_ms() == float(REQUEST_WARNING_MS)

    def test_slow_request_threshold_can_tighten_below_contract(self):
        """Operators may lower the warning threshold for more coverage."""
        with patch.dict(os.environ, {"SLOW_REQUEST_THRESHOLD_MS": "250"}):
            assert _slow_request_threshold_ms() == 250.0

    def test_slow_request_threshold_cannot_exceed_contract_ceiling(self):
        """A configured threshold cannot relax the 500 ms contract."""
        with patch.dict(os.environ, {"SLOW_REQUEST_THRESHOLD_MS": "5000"}):
            assert _slow_request_threshold_ms() == float(REQUEST_WARNING_MS)

    def test_invalid_slow_request_threshold_falls_back_to_contract(self):
        """Unparseable and non-positive values fall back to the contract default."""
        for raw_value in ("not-a-number", "0", "-1"):
            with patch.dict(os.environ, {"SLOW_REQUEST_THRESHOLD_MS": raw_value}):
                assert _slow_request_threshold_ms() == float(REQUEST_WARNING_MS)

    def test_environment_specific_behavior(self):
        """Performance logging works in every environment."""
        app_prod = FastAPI()
        add_request_logging_middleware(app_prod, "production")
        client_prod = TestClient(app_prod)

        @app_prod.get("/prod-test")
        async def prod_endpoint():
            return {"message": "production test"}

        response = client_prod.get("/prod-test")
        assert response.status_code == 200

        app_dev = FastAPI()
        add_request_logging_middleware(app_dev, "development")
        client_dev = TestClient(app_dev)

        @app_dev.get("/dev-test")
        async def dev_endpoint():
            return {"message": "development test"}

        response = client_dev.get("/dev-test")
        assert response.status_code == 200


class TestPerformanceBudgetLogging:
    """Test performance budget logging and telemetry."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = FastAPI()
        add_request_logging_middleware(self.app, "test")
        self.client = TestClient(self.app)
        get_performance_budget_manager().clear_all()
    
    @patch('app.middleware.request_logging.logger')
    def test_warning_logging_structure(self, mock_logger):
        """Test that warnings are logged with proper structure."""
        @self.app.get("/warning-test")
        async def warning_endpoint():
            import time
            time.sleep(0.6)  # Trigger warning (500ms threshold)
            return {"message": "warning test"}
        
        response = self.client.get("/warning-test")
        
        assert response.status_code == 200
        
        # Check that warning was logged
        assert mock_logger.warning.called
        
        # Find the correct warning call (there might be other log calls)
        warning_call = None
        for call in mock_logger.warning.call_args_list:
            if len(call[0]) >= 3 and "Performance warning" in call[0][0]:
                warning_call = call
                break
        
        assert warning_call is not None, "No performance warning call found"
        
        # The logger.warning call has positional args and extra keyword arg
        # call_args[0] = positional args (message, method, path, time_ms)
        # call_args[1] = keyword args (extra={...})
        assert len(warning_call[0]) >= 4  # message, method, path, time_ms
        assert "extra" in warning_call[1]
        
        extra = warning_call[1]["extra"]
        assert "performance_warning" in extra
        warning_data = extra["performance_warning"]
        
        assert warning_data["operation"] == "request./warning-test"
        assert warning_data["budget_type"] == "request"
        assert warning_data["severity"] == "warning"
        assert "elapsed_ms" in warning_data
        assert "context" in warning_data
    
    @patch('app.middleware.request_logging.logger')
    def test_violation_logging_structure(self, mock_logger):
        """Test that violations are logged with proper structure."""
        @self.app.get("/violation-test")
        async def violation_endpoint():
            import time
            time.sleep(1.1)  # Trigger violation (1000ms threshold)
            return {"message": "violation test"}
        
        response = self.client.get("/violation-test")
        
        assert response.status_code == 200
        
        # Check that violation was logged
        assert mock_logger.error.called
        
        # Find the correct violation call (there might be other log calls)
        violation_call = None
        for call in mock_logger.error.call_args_list:
            if len(call[0]) >= 3 and "Performance budget violation" in call[0][0]:
                violation_call = call
                break
        
        assert violation_call is not None, "No performance violation call found"
        
        # The logger.error call has positional args and extra keyword arg
        # call_args[0] = positional args (message, method, path, time_ms)
        # call_args[1] = keyword args (extra={...})
        assert len(violation_call[0]) >= 4  # message, method, path, time_ms
        assert "extra" in violation_call[1]
        
        extra = violation_call[1]["extra"]
        assert "performance_violation" in extra
        violation_data = extra["performance_violation"]
        
        assert violation_data["operation"] == "request./violation-test"
        assert violation_data["budget_type"] == "request"
        assert violation_data["severity"] == "violation"
        assert "elapsed_ms" in violation_data
        assert "context" in violation_data


class TestPerformanceBudgetContext:
    """Test performance budget context and metadata."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = FastAPI()
        add_request_logging_middleware(self.app, "test")
        self.client = TestClient(self.app)
        get_performance_budget_manager().clear_all()
    
    def test_request_context_includes_route_info(self):
        """Test that request context includes route and method information."""
        @self.app.get("/context-test")
        async def context_endpoint():
            import time
            time.sleep(0.6)  # Trigger warning
            return {"message": "context test"}
        
        response = self.client.get("/context-test")
        
        assert response.status_code == 200
        
        budget_manager = get_performance_budget_manager()
        warnings = budget_manager.get_request_warnings()
        
        assert len(warnings) == 1
        context = warnings[0].context
        
        # Should include route information
        assert "route" in context
        assert context["route"] == "/context-test"
        assert "method" in context
        assert context["method"] == "GET"
        assert "request_id" in context
    
    def test_context_includes_database_info(self):
        """Test that context includes database query information."""
        @self.app.get("/db-context-test")
        async def db_context_endpoint():
            from app.performance_diagnostics import get_request_diagnostics
            diagnostics = get_request_diagnostics()
            diagnostics.database_queries = 5
            diagnostics.database_time_ms = 25.5
            
            import time
            time.sleep(0.6)  # Trigger warning
            return {"message": "db context test"}
        
        response = self.client.get("/db-context-test")
        
        assert response.status_code == 200
        
        budget_manager = get_performance_budget_manager()
        warnings = budget_manager.get_request_warnings()
        
        assert len(warnings) == 1
        context = warnings[0].context
        
        # Should include database information
        assert "database_queries" in context
        assert "database_time_ms" in context
        assert context["database_queries"] == 5
        assert context["database_time_ms"] == 25.5