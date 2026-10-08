"""Tests for performance budgets and bounded await primitives."""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, patch

from app.performance_budgets import (
    PerformanceBudgetManager,
    PerformanceWarning,
    RequestBudgetExceeded,
    StartupBudgetExceeded,
    get_performance_budget_manager,
    run_bounded,
    startup_budget,
    request_budget,
)


class TestPerformanceBudgetManager:
    """Test the performance budget manager."""
    
    def test_initialization(self):
        """Test that the manager initializes with empty lists."""
        manager = PerformanceBudgetManager()
        assert manager.get_startup_warnings() == []
        assert manager.get_startup_violations() == []
        assert manager.get_request_warnings() == []
        assert manager.get_request_violations() == []
    
    def test_record_warning(self):
        """Test recording a performance warning."""
        manager = PerformanceBudgetManager()
        warning = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=600,
            budget_type="request",
            severity="warning"
        )
        
        manager.record_warning(warning)
        warnings = manager.get_request_warnings()
        assert len(warnings) == 1
        assert warnings[0] == warning
        assert manager.get_startup_warnings() == []
    
    def test_record_violation(self):
        """Test recording a performance violation."""
        manager = PerformanceBudgetManager()
        violation = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=1200,
            budget_type="startup",
            severity="violation"
        )
        
        manager.record_violation(violation)
        violations = manager.get_startup_violations()
        assert len(violations) == 1
        assert violations[0] == violation
        assert manager.get_request_violations() == []
    
    def test_clear_all(self):
        """Test clearing all warnings and violations."""
        manager = PerformanceBudgetManager()
        
        # Add some data
        warning = PerformanceWarning("test", 100, "request", severity="warning")
        violation = PerformanceWarning("test", 200, "startup", severity="violation")
        
        manager.record_warning(warning)
        manager.record_violation(violation)
        
        assert len(manager.get_request_warnings()) == 1
        assert len(manager.get_startup_violations()) == 1
        
        manager.clear_all()
        
        assert manager.get_startup_warnings() == []
        assert manager.get_startup_violations() == []
        assert manager.get_request_warnings() == []
        assert manager.get_request_violations() == []
    
    def test_global_manager_singleton(self):
        """Test that the global manager is a singleton."""
        manager1 = get_performance_budget_manager()
        manager2 = get_performance_budget_manager()
        
        assert manager1 is manager2


class TestPerformanceWarning:
    """Test the PerformanceWarning class."""
    
    def test_warning_creation(self):
        """Test creating a performance warning."""
        warning = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=750,
            budget_type="request",
            context={"route": "/api/test"},
            severity="warning"
        )
        
        assert warning.operation == "test_operation"
        assert warning.elapsed_ms == 750
        assert warning.budget_type == "request"
        assert warning.context == {"route": "/api/test"}
        assert warning.severity == "warning"
        assert warning.timestamp is not None
    
    def test_warning_to_dict(self):
        """Test converting a warning to dictionary."""
        warning = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=750,
            budget_type="request",
            context={"route": "/api/test"},
            severity="warning"
        )
        
        warning_dict = warning.to_dict()
        
        assert warning_dict["operation"] == "test_operation"
        assert warning_dict["elapsed_ms"] == 750
        assert warning_dict["budget_type"] == "request"
        assert warning_dict["context"] == {"route": "/api/test"}
        assert warning_dict["severity"] == "warning"
        assert "timestamp" in warning_dict


class TestRunBounded:
    """Test the run_bounded function."""
    
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Test successful execution within budget."""
        async def fast_coroutine():
            await asyncio.sleep(0.1)  # 100ms
            return "success"
        
        result = await run_bounded(
            operation="test_fast",
            coroutine=fast_coroutine(),
            warning_ms=500,
            timeout_ms=1000
        )
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_warning_threshold(self):
        """Test execution that triggers warning but not timeout."""
        with patch('app.performance_budgets.logger') as mock_logger:
            async def slow_coroutine():
                await asyncio.sleep(0.6)  # 600ms
                return "success"
            
            result = await run_bounded(
                operation="test_slow",
                coroutine=slow_coroutine(),
                warning_ms=500,
                timeout_ms=1000
            )
            
            assert result == "success"
            # Should have logged a warning
            mock_logger.warning.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_timeout_exception(self):
        """Test execution that exceeds timeout."""
        with patch('app.performance_budgets.logger') as mock_logger:
            async def very_slow_coroutine():
                await asyncio.sleep(2.0)  # 2000ms
                return "success"
            
            with pytest.raises(asyncio.TimeoutError):
                await run_bounded(
                    operation="test_very_slow",
                    coroutine=very_slow_coroutine(),
                    warning_ms=500,
                    timeout_ms=1000
                )
            
            # Should have logged an error
            mock_logger.error.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_startup_budget_exception(self):
        """Test startup budget exception."""
        async def slow_coroutine():
            await asyncio.sleep(3.0)  # 3000ms
            return "success"
        
        with pytest.raises(StartupBudgetExceeded) as exc_info:
            await run_bounded(
                operation="startup_test",
                coroutine=slow_coroutine(),
                warning_ms=2000,
                timeout_ms=2500
            )
        
        assert exc_info.value.operation == "startup_test"
        assert exc_info.value.elapsed_ms >= 2500
        assert exc_info.value.timeout_ms == 2500
    
    @pytest.mark.asyncio
    async def test_request_budget_exception(self):
        """Test request budget exception."""
        async def slow_coroutine():
            await asyncio.sleep(1.5)  # 1500ms
            return "success"
        
        with pytest.raises(RequestBudgetExceeded) as exc_info:
            await run_bounded(
                operation="request_test",
                coroutine=slow_coroutine(),
                warning_ms=500,
                timeout_ms=1000
            )
        
        assert exc_info.value.operation == "request_test"
        assert exc_info.value.elapsed_ms >= 1000
        assert exc_info.value.timeout_ms == 1000
    
    @pytest.mark.asyncio
    async def test_default_budgets(self):
        """Test default budget selection based on operation name."""
        async def slow_coroutine():
            await asyncio.sleep(1.5)  # 1500ms
            return "success"
        
        # Test startup operation defaults
        with pytest.raises(StartupBudgetExceeded):
            await run_bounded(
                operation="startup_operation",
                coroutine=slow_coroutine()
                # No warning_ms or timeout_ms specified, should use startup defaults
            )
        
        # Test request operation defaults
        with pytest.raises(RequestBudgetExceeded):
            await run_bounded(
                operation="request_operation",
                coroutine=slow_coroutine()
                # No warning_ms or timeout_ms specified, should use request defaults
            )


class TestStartupBudgetDecorator:
    """Test the startup_budget decorator."""
    
    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """Test successful decorated function."""
        @startup_budget("test_startup")
        async def test_function():
            await asyncio.sleep(0.1)
            return "decorated_success"
        
        result = await test_function()
        assert result == "decorated_success"
    
    @pytest.mark.asyncio
    async def test_decorator_timeout(self):
        """Test decorated function that times out."""
        @startup_budget("test_startup_timeout", timeout_ms=500)
        async def slow_function():
            await asyncio.sleep(1.0)
            return "should_not_reach_here"
        
        with pytest.raises(StartupBudgetExceeded):
            await slow_function()


class TestRequestBudgetDecorator:
    """Test the request_budget decorator."""
    
    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """Test successful decorated function."""
        @request_budget("test_request")
        async def test_function():
            await asyncio.sleep(0.1)
            return "decorated_success"
        
        result = await test_function()
        assert result == "decorated_success"
    
    @pytest.mark.asyncio
    async def test_decorator_timeout(self):
        """Test decorated function that times out."""
        @request_budget("test_request_timeout", timeout_ms=500)
        async def slow_function():
            await asyncio.sleep(1.0)
            return "should_not_reach_here"
        
        with pytest.raises(RequestBudgetExceeded):
            await slow_function()


class TestPerformanceBudgetIntegration:
    """Integration tests for performance budgets."""
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test multiple concurrent operations with budgets."""
        async def operation_1():
            await asyncio.sleep(0.2)
            return "op1"
        
        async def operation_2():
            await asyncio.sleep(0.3)
            return "op2"
        
        async def operation_3():
            await asyncio.sleep(0.1)
            return "op3"
        
        # All should complete successfully with reasonable budgets
        results = await asyncio.gather(
            run_bounded("op1", operation_1(), timeout_ms=1000),
            run_bounded("op2", operation_2(), timeout_ms=1000),
            run_bounded("op3", operation_3(), timeout_ms=1000)
        )
        
        assert results == ["op1", "op2", "op3"]
    
    @pytest.mark.asyncio
    async def test_mixed_budget_types(self):
        """Test mixing startup and request budget operations."""
        async def fast_startup():
            await asyncio.sleep(0.1)
            return "startup"
        
        async def fast_request():
            await asyncio.sleep(0.1)
            return "request"
        
        # Both should complete successfully
        startup_result = await run_bounded("startup_op", fast_startup(), timeout_ms=5000)
        request_result = await run_bounded("request_op", fast_request(), timeout_ms=1000)
        
        assert startup_result == "startup"
        assert request_result == "request"
    
    @pytest.mark.asyncio
    async def test_context_propagation(self):
        """Test that context is properly propagated."""
        with patch('app.performance_budgets.logger') as mock_logger:
            async def context_coroutine():
                await asyncio.sleep(0.6)
                return "with_context"
            
            context = {"route": "/api/test", "user_id": 123}
            
            await run_bounded(
                "context_test",
                context_coroutine(),
                warning_ms=500,
                timeout_ms=1000,
                context=context
            )
            
            # Check that context was included in the logged warning
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[1]
            assert "performance_warning" in call_args
            warning_dict = call_args["performance_warning"]
            assert warning_dict["context"] == context


class TestPerformanceBudgetEdgeCases:
    """Test edge cases and error conditions."""
    
    @pytest.mark.asyncio
    async def test_zero_timeout(self):
        """Test with zero timeout (should still work)."""
        async def fast_coroutine():
            await asyncio.sleep(0.01)
            return "fast"
        
        result = await run_bounded(
            "zero_timeout_test",
            fast_coroutine(),
            timeout_ms=0
        )
        
        assert result == "fast"
    
    @pytest.mark.asyncio
    async def test_negative_timeout(self):
        """Test with negative timeout (should be clamped to positive)."""
        async def fast_coroutine():
            await asyncio.sleep(0.01)
            return "fast"
        
        result = await run_bounded(
            "negative_timeout_test",
            fast_coroutine(),
            timeout_ms=-100
        )
        
        assert result == "fast"
    
    @pytest.mark.asyncio
    async def test_exception_propagation(self):
        """Test that exceptions are properly propagated."""
        async def failing_coroutine():
            await asyncio.sleep(0.1)
            raise ValueError("Test error")
        
        with pytest.raises(ValueError, match="Test error"):
            await run_bounded(
                "exception_test",
                failing_coroutine(),
                timeout_ms=1000
            )
    
    @pytest.mark.asyncio
    async def test_task_cancellation(self):
        """Test that tasks are properly cancelled on timeout."""
        with patch('asyncio.Task') as mock_task:
            async def slow_coroutine():
                await asyncio.sleep(2.0)
                return "should_not_reach"
            
            with pytest.raises(asyncio.TimeoutError):
                await run_bounded(
                    "cancellation_test",
                    slow_coroutine(),
                    timeout_ms=500
                )
            
            # Verify that the task was cancelled
            mock_task.return_value.cancel.assert_called_once()