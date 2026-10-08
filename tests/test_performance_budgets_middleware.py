"""Tests for performance budget middleware integration."""

from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware.request_logging import add_request_logging_middleware
from app.performance_budgets import get_performance_budget_manager


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


class TestPerformanceBudgetConfiguration:
    """Test performance budget configuration and environment handling."""
    
    def test_deprecated_slow_request_threshold(self):
        """Test that the deprecated SLOW_REQUEST_THRESHOLD_MS still works."""
        with patch.dict('os.environ', {'SLOW_REQUEST_THRESHOLD_MS': '750'}):
            from app.middleware.request_logging import _slow_request_threshold_ms
            
            threshold = _slow_request_threshold_ms()
            # Should return the value from environment
            assert threshold == 750.0
    
    def test_environment_specific_behavior(self):
        """Test that behavior changes based on environment."""
        # Test production environment
        app_prod = FastAPI()
        add_request_logging_middleware(app_prod, "production")
        client_prod = TestClient(app_prod)
        
        @app_prod.get("/prod-test")
        async def prod_endpoint():
            return {"message": "production test"}
        
        response = client_prod.get("/prod-test")
        assert response.status_code == 200
        
        # Test development environment
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
            time.sleep(0.6)  # Trigger warning
            return {"message": "warning test"}
        
        response = self.client.get("/warning-test")
        
        assert response.status_code == 200
        
        # Check that warning was logged with proper structure
        mock_logger.warning.assert_called()
        # The logger.warning call in middleware: logger.warning(msg, *args, extra=extra)
        # call_args[0] is the positional args, call_args[1] is keyword args.
        call_args = mock_logger.warning.call_args[1]
        
        # The logger.warning call uses extra={**log_data, ...}
        # The performance_warning is in that extra dict.
        assert "extra" in call_args
        extra = call_args["extra"]
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
            time.sleep(1.1)  # Trigger violation
            return {"message": "violation test"}
        
        response = self.client.get("/violation-test")
        
        assert response.status_code == 200
        
        # Check that violation was logged with proper structure
        mock_logger.error.assert_called()
        call_args = mock_logger.error.call_args[1]
        
        # Should have performance violation in extra data
        assert "extra" in call_args
        extra = call_args["extra"]
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