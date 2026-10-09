"""Tests for performance budgets and bounded await primitives."""

import asyncio
from unittest.mock import patch

import pytest

from app.performance_budgets import (
    PerformanceBudgetManager,
    PerformanceWarning,
    REQUEST_TIMEOUT_MS,
    REQUEST_WARNING_MS,
    RequestBudgetError,
    STARTUP_TIMEOUT_MS,
    STARTUP_WARNING_MS,
    StartupBudgetError,
    budget_type_for,
    enforce_startup_budget,
    evaluate_startup_budget,
    get_performance_budget_manager,
    request_budget,
    run_bounded,
    startup_budget,
)


class TestPerformanceBudgetManager:
    """Test the performance budget manager."""

    def test_initialization(self) -> None:
        """The manager starts with empty buffers."""
        manager = PerformanceBudgetManager()
        assert manager.get_startup_warnings() == []
        assert manager.get_startup_violations() == []
        assert manager.get_request_warnings() == []
        assert manager.get_request_violations() == []

    def test_record_warning(self) -> None:
        """Recording a request warning retains it and counts it by operation."""
        manager = PerformanceBudgetManager()
        warning = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=600,
            budget_type="request",
            severity="warning",
        )

        manager.record_warning(warning)
        warnings = manager.get_request_warnings()
        assert len(warnings) == 1
        assert warnings[0] is warning
        assert manager.get_startup_warnings() == []
        assert manager.warning_counts_by_operation() == {"test_operation": 1}

    def test_record_violation(self) -> None:
        """Recording a startup violation retains it and counts it by operation."""
        manager = PerformanceBudgetManager()
        violation = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=1200,
            budget_type="startup",
            severity="violation",
        )

        manager.record_violation(violation)
        violations = manager.get_startup_violations()
        assert len(violations) == 1
        assert violations[0] is violation
        assert manager.get_request_violations() == []
        assert manager.violation_counts_by_operation() == {"test_operation": 1}

    def test_clear_all(self) -> None:
        """Clearing resets retained events and lifetime counters."""
        manager = PerformanceBudgetManager()
        manager.record_warning(
            PerformanceWarning("test", 100, "request", severity="warning")
        )
        manager.record_violation(
            PerformanceWarning("test", 200, "startup", severity="violation")
        )
        assert len(manager.get_request_warnings()) == 1
        assert len(manager.get_startup_violations()) == 1

        manager.clear_all()

        assert manager.get_startup_warnings() == []
        assert manager.get_startup_violations() == []
        assert manager.get_request_warnings() == []
        assert manager.get_request_violations() == []
        assert manager.warning_counts_by_operation() == {}
        assert manager.violation_counts_by_operation() == {}

    def test_retention_is_bounded_but_counts_stay_complete(self) -> None:
        """A slow route cannot grow process memory without bound."""
        manager = PerformanceBudgetManager(max_tracked_events=3)

        for _ in range(10):
            manager.record_violation(
                PerformanceWarning("request./slow", 1200, "request", severity="violation")
            )

        assert len(manager.get_request_violations()) == 3
        assert manager.violation_counts_by_operation() == {"request./slow": 10}

    def test_global_manager_singleton(self) -> None:
        """The global manager is a singleton."""
        manager1 = get_performance_budget_manager()
        manager2 = get_performance_budget_manager()
        assert manager1 is manager2


class TestPerformanceWarning:
    """Test the PerformanceWarning class."""

    def test_warning_creation(self) -> None:
        """A warning retains its structured fields."""
        warning = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=750,
            budget_type="request",
            context={"route": "/api/test"},
            severity="warning",
        )

        assert warning.operation == "test_operation"
        assert warning.elapsed_ms == 750
        assert warning.budget_type == "request"
        assert warning.context == {"route": "/api/test"}
        assert warning.severity == "warning"
        assert warning.timestamp is not None

    def test_warning_to_dict(self) -> None:
        """to_dict exposes the structured payload for logging."""
        warning = PerformanceWarning(
            operation="test_operation",
            elapsed_ms=750,
            budget_type="request",
            context={"route": "/api/test"},
            severity="warning",
        )

        warning_dict = warning.to_dict()

        assert warning_dict["operation"] == "test_operation"
        assert warning_dict["elapsed_ms"] == 750
        assert warning_dict["budget_type"] == "request"
        assert warning_dict["context"] == {"route": "/api/test"}
        assert warning_dict["severity"] == "warning"
        assert "timestamp" in warning_dict


class TestBudgetTypeClassification:
    """Test operation budget classification."""

    def test_startup_operations_classify_as_startup(self) -> None:
        """Readiness-critical operations use the startup budgets."""
        assert budget_type_for("startup.readiness") == "startup"
        assert budget_type_for("startup.neon_monitor") == "startup"
        assert budget_type_for("startup.database_initialization") == "startup"

    def test_other_operations_classify_as_request(self) -> None:
        """Everything else uses the request budgets."""
        assert budget_type_for("request./api/roll") == "request"
        assert budget_type_for("op1") == "request"


class TestRunBounded:
    """Test the run_bounded function."""

    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        """An operation inside its budget returns its result."""

        async def fast_coroutine() -> str:
            await asyncio.sleep(0.1)
            return "success"

        result = await run_bounded(
            operation="test_fast",
            coroutine=fast_coroutine(),
            warning_ms=500,
            timeout_ms=1000,
        )

        assert result == "success"

    @pytest.mark.asyncio
    async def test_warning_threshold(self) -> None:
        """Crossing the warning budget emits one structured warning."""
        with patch("app.performance_budgets.logger") as mock_logger:

            async def slow_coroutine() -> str:
                await asyncio.sleep(0.6)
                return "success"

            result = await run_bounded(
                operation="test_slow",
                coroutine=slow_coroutine(),
                warning_ms=500,
                timeout_ms=1000,
            )

            assert result == "success"
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_exception(self) -> None:
        """Crossing the hard deadline fails the operation."""
        with patch("app.performance_budgets.logger") as mock_logger:

            async def very_slow_coroutine() -> str:
                await asyncio.sleep(2.0)
                return "success"

            with pytest.raises(RequestBudgetError):
                await run_bounded(
                    operation="test_very_slow",
                    coroutine=very_slow_coroutine(),
                    warning_ms=500,
                    timeout_ms=1000,
                )

            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_budget_exception(self) -> None:
        """A hung startup operation fails with its operation attribution."""
        cancelled = asyncio.Event()

        async def hung_coroutine() -> str:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return "success"

        with pytest.raises(StartupBudgetError) as exc_info:
            await run_bounded(
                operation="startup.hung",
                coroutine=hung_coroutine(),
                warning_ms=2000,
                timeout_ms=2500,
            )

        assert exc_info.value.operation == "startup.hung"
        assert exc_info.value.elapsed_ms >= 2500
        assert exc_info.value.timeout_ms == 2500
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_hung_operation_leaves_no_background_task(self) -> None:
        """A cancelled bounded await does not leave the coroutine running."""
        observed_cancel = asyncio.Event()

        async def hung_coroutine() -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                observed_cancel.set()
                raise

        with pytest.raises(RequestBudgetError):
            await run_bounded(
                operation="request.hung",
                coroutine=hung_coroutine(),
                warning_ms=10,
                timeout_ms=50,
            )

        assert observed_cancel.is_set()
        await asyncio.sleep(0)
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]

    @pytest.mark.asyncio
    async def test_outer_cancellation_cancels_bounded_operation(self) -> None:
        """Cancelling the caller cancels the bounded coroutine instead of leaking it."""
        observed_cancel = asyncio.Event()

        async def slow_coroutine() -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                observed_cancel.set()
                raise

        task = asyncio.create_task(
            run_bounded(
                operation="request.cancelled",
                coroutine=slow_coroutine(),
                warning_ms=100,
                timeout_ms=5000,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert observed_cancel.is_set()

    @pytest.mark.asyncio
    async def test_request_budget_exception(self) -> None:
        """A request operation uses the request deadline and error type."""

        async def slow_coroutine() -> str:
            await asyncio.sleep(1.5)
            return "success"

        with pytest.raises(RequestBudgetError) as exc_info:
            await run_bounded(
                operation="request_test",
                coroutine=slow_coroutine(),
                warning_ms=500,
                timeout_ms=1000,
            )

        assert exc_info.value.operation == "request_test"
        assert exc_info.value.elapsed_ms >= 1000
        assert exc_info.value.timeout_ms == 1000

    @pytest.mark.asyncio
    async def test_default_budgets(self) -> None:
        """Default budgets follow the operation classification."""

        async def slow_coroutine() -> str:
            await asyncio.sleep(3.0)
            return "success"

        with pytest.raises(StartupBudgetError):
            await run_bounded(operation="startup_operation", coroutine=slow_coroutine())

        with pytest.raises(RequestBudgetError):
            await run_bounded(operation="request_operation", coroutine=slow_coroutine())

    @pytest.mark.asyncio
    async def test_non_positive_timeout_is_rejected(self) -> None:
        """A non-positive deadline must not silently become an unbounded await."""

        async def fast_coroutine() -> str:
            await asyncio.sleep(0.01)
            return "fast"

        for timeout_ms in (0, -100):
            rejected = fast_coroutine()
            try:
                with pytest.raises(ValueError, match="positive hard deadline"):
                    await run_bounded("invalid_timeout_test", rejected, timeout_ms=timeout_ms)
            finally:
                # run_bounded rejects the deadline before awaiting; close the
                # unused coroutine so the test leaves no pending awaitable.
                rejected.close()

    @pytest.mark.asyncio
    async def test_exception_propagation(self) -> None:
        """Non-budget exceptions propagate unchanged."""
        with pytest.raises(ValueError, match="Test error"):

            async def failing_coroutine() -> None:
                await asyncio.sleep(0.1)
                raise ValueError("Test error")

            await run_bounded(
                "exception_test",
                failing_coroutine(),
                timeout_ms=1000,
            )

    @pytest.mark.asyncio
    async def test_inner_timeout_error_is_not_reported_as_budget_overrun(self) -> None:
        """An operation's own timeout is not misattributed to the budget."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        async def inner_timeout() -> None:
            raise TimeoutError("database connect timeout")

        with pytest.raises(TimeoutError, match="database connect timeout"):
            await run_bounded(
                operation="startup.inner_timeout",
                coroutine=inner_timeout(),
                warning_ms=100,
                timeout_ms=5000,
            )

        assert manager.violation_counts_by_operation() == {}
        assert manager.get_startup_violations() == []

    @pytest.mark.asyncio
    async def test_deadline_violation_is_queryable_by_operation(self) -> None:
        """A deadline breach records a queryable violation with the deadline."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        async def slow_coroutine() -> str:
            await asyncio.sleep(1.0)
            return "success"

        with pytest.raises(RequestBudgetError):
            await run_bounded(
                operation="request./slow",
                coroutine=slow_coroutine(),
                warning_ms=100,
                timeout_ms=100,
                context={"route": "/slow"},
            )

        assert manager.violation_counts_by_operation() == {"request./slow": 1}
        violations = manager.get_request_violations()
        assert len(violations) == 1
        assert violations[0].context["deadline_ms"] == 100
        assert violations[0].context["route"] == "/slow"


class TestStartupBudgetEnforcement:
    """Test the total ping-ready startup budget contract."""

    def test_healthy_startup_records_nothing(self) -> None:
        """Startup inside the warning budget records no event."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        assert evaluate_startup_budget(STARTUP_WARNING_MS - 1) is None
        assert manager.get_startup_warnings() == []
        assert manager.get_startup_violations() == []

    def test_warning_band_records_warning(self) -> None:
        """Startup at or above 2000 ms records a warning and no violation."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        recorded = evaluate_startup_budget(
            STARTUP_WARNING_MS,
            context={"deployment_id": "dep-1"},
        )

        assert recorded is not None
        assert recorded.severity == "warning"
        assert recorded.elapsed_ms == STARTUP_WARNING_MS
        assert recorded.context["warning_budget_ms"] == STARTUP_WARNING_MS
        assert manager.get_startup_warnings() == [recorded]
        assert manager.get_startup_violations() == []

    def test_hard_band_records_violation_with_deadline(self) -> None:
        """Startup at or above 2500 ms records a violation naming the deadline."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        recorded = evaluate_startup_budget(
            STARTUP_TIMEOUT_MS,
            operation="startup.readiness",
            context={"deployment_id": "dep-1"},
        )

        assert recorded is not None
        assert recorded.severity == "violation"
        assert recorded.operation == "startup.readiness"
        assert recorded.context["deadline_ms"] == STARTUP_TIMEOUT_MS
        assert recorded.context["deployment_id"] == "dep-1"
        assert manager.get_startup_violations() == [recorded]

    def test_production_hard_budget_fails_initialization(self) -> None:
        """Crossing the hard budget in production fails initialization."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        with pytest.raises(StartupBudgetError) as exc_info:
            enforce_startup_budget(72420.56, environment="production")

        assert exc_info.value.operation == "startup.readiness"
        assert exc_info.value.elapsed_ms == 72420.56
        assert exc_info.value.timeout_ms == STARTUP_TIMEOUT_MS
        assert manager.violation_counts_by_operation() == {"startup.readiness": 1}

    def test_production_inside_budget_does_not_fail(self) -> None:
        """Healthy production startup inside budget does not fail initialization."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        assert enforce_startup_budget(1603.92, environment="production") is None
        assert manager.get_startup_violations() == []

    def test_non_production_records_violation_without_failing(self) -> None:
        """Non-production degrades to telemetry instead of failing startup."""
        manager = get_performance_budget_manager()
        manager.clear_all()

        recorded = enforce_startup_budget(9000.0, environment="test")

        assert recorded is not None
        assert recorded.severity == "violation"
        assert manager.get_startup_violations() == [recorded]

    @pytest.mark.asyncio
    async def test_healthy_startup_with_production_shape_stays_under_hard_budget(self) -> None:
        """Production-shaped initialization stays under the 2.5 s hard budget."""
        budget_manager = get_performance_budget_manager()
        budget_manager.clear_all()

        async def production_shaped_initialization() -> None:
            await asyncio.sleep(0.05)
            return None

        result = await run_bounded(
            operation="startup.production_shape",
            coroutine=production_shaped_initialization(),
            warning_ms=STARTUP_WARNING_MS,
            timeout_ms=STARTUP_TIMEOUT_MS,
        )

        assert result is None
        assert budget_manager.get_startup_violations() == []
        assert budget_manager.get_startup_warnings() == []
        assert enforce_startup_budget(1603.92, environment="production") is None


class TestStartupBudgetDecorator:
    """Test the startup_budget decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success(self) -> None:
        """A decorated function inside budget returns its result."""

        @startup_budget("test_startup")
        async def test_function() -> str:
            await asyncio.sleep(0.1)
            return "decorated_success"

        assert await test_function() == "decorated_success"

    @pytest.mark.asyncio
    async def test_decorator_timeout(self) -> None:
        """A decorated function past its deadline fails with its operation."""

        @startup_budget("test_startup_timeout", timeout_ms=500)
        async def slow_function() -> str:
            await asyncio.sleep(1.0)
            return "should_not_reach_here"

        with pytest.raises(StartupBudgetError):
            await slow_function()


class TestRequestBudgetDecorator:
    """Test the request_budget decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success(self) -> None:
        """A decorated function inside budget returns its result."""

        @request_budget("test_request")
        async def test_function() -> str:
            await asyncio.sleep(0.1)
            return "decorated_success"

        assert await test_function() == "decorated_success"

    @pytest.mark.asyncio
    async def test_decorator_timeout(self) -> None:
        """A decorated function past its deadline fails with its operation."""

        @request_budget("test_request_timeout", timeout_ms=500)
        async def slow_function() -> str:
            await asyncio.sleep(1.0)
            return "should_not_reach_here"

        with pytest.raises(RequestBudgetError):
            await slow_function()


class TestPerformanceBudgetIntegration:
    """Integration tests for performance budgets."""

    @pytest.mark.asyncio
    async def test_concurrent_operations(self) -> None:
        """Concurrent bounded operations all complete inside budget."""

        async def operation_1() -> str:
            await asyncio.sleep(0.2)
            return "op1"

        async def operation_2() -> str:
            await asyncio.sleep(0.3)
            return "op2"

        async def operation_3() -> str:
            await asyncio.sleep(0.1)
            return "op3"

        results = await asyncio.gather(
            run_bounded("op1", operation_1(), timeout_ms=1000),
            run_bounded("op2", operation_2(), timeout_ms=1000),
            run_bounded("op3", operation_3(), timeout_ms=1000),
        )

        assert results == ["op1", "op2", "op3"]

    @pytest.mark.asyncio
    async def test_context_propagation(self) -> None:
        """Structured warning telemetry carries the caller context."""
        with patch("app.performance_budgets.logger") as mock_logger:

            async def context_coroutine() -> str:
                await asyncio.sleep(0.6)
                return "with_context"

            context = {"route": "/api/test", "user_id": 123}

            await run_bounded(
                "context_test",
                context_coroutine(),
                warning_ms=500,
                timeout_ms=1000,
                context=context,
            )

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[1]
            assert "extra" in call_args
            assert "performance_warning" in call_args["extra"]
            warning_dict = call_args["extra"]["performance_warning"]
            assert warning_dict["context"] == context

    def test_request_warning_and_violation_thresholds_match_contract(self) -> None:
        """The frozen request thresholds are 500 ms warning and 1000 ms violation."""
        assert REQUEST_WARNING_MS == 500
        assert REQUEST_TIMEOUT_MS == 1000
        assert STARTUP_WARNING_MS == 2000
        assert STARTUP_TIMEOUT_MS == 2500