"""Tests for automatic GitHub issue filing from performance violations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import performance_issue_service as perf_issues


@pytest.fixture(autouse=True)
def _clean_tracker():
    """Isolate process-local performance issue state between tests."""
    from app.config import clear_settings_cache

    perf_issues.reset_for_tests()
    clear_settings_cache()
    yield
    perf_issues.reset_for_tests()
    clear_settings_cache()


class TestNeverFileUnderBudget:
    """Measurements at or under the route budget never open an issue."""

    def test_healthy_request_returns_no_decision(self) -> None:
        """A request inside the warning band produces no filing decision."""
        assert (
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=120.0,
                cold=False,
            )
            is None
        )

    def test_warning_under_budget_never_files(self) -> None:
        """500-999 ms warnings accumulate only, even after many repeats."""
        base = 1_000_000.0
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=575.0,
                cold=False,
                now=base + i,
            )
            for i in range(10)
        ]

        assert all(d is not None and d.action == "accumulate" for d in actions)

    def test_at_budget_never_files(self) -> None:
        """A timing exactly at the 1000 ms budget never opens an issue."""
        base = 1_100_000.0
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/identity-inbox",
                duration_ms=1000.0,
                cold=False,
                now=base + i,
            )
            for i in range(5)
        ]

        assert all(d is not None and d.action == "accumulate" for d in actions)

    def test_title_never_shows_duration_below_budget(self) -> None:
        """Issue titles clamp displayed duration to at least the route budget."""
        title = perf_issues.build_issue_title(
            kind="request",
            method="GET",
            route_template="/api/v1/roll/bootstrap",
            duration_ms=575.0,
        )

        assert "575" not in title
        assert "budget 1000ms" in title
        assert "took 1000ms" in title


class TestColdStartsIgnored:
    """Cold-start and startup readiness samples never count toward filing."""

    def test_cold_over_budget_is_ignored(self) -> None:
        """Cold over-budget hits do not file even after N repeats."""
        base = 2_000_000.0
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/roll/bootstrap",
                duration_ms=3500.0,
                cold=True,
                now=base + i,
            )
            for i in range(5)
        ]

        assert all(d is not None and d.action == "ignore" for d in actions)

    def test_cold_hits_do_not_count_toward_warm_threshold(self) -> None:
        """Cold samples do not advance the warm daily breach counter."""
        base = 2_100_000.0
        for i in range(5):
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/roll/bootstrap",
                duration_ms=2500.0,
                cold=True,
                now=base + i,
            )
        first_warm = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/roll/bootstrap",
            duration_ms=1500.0,
            cold=False,
            now=base + 10,
        )

        assert first_warm is not None
        assert first_warm.action == "accumulate"

    def test_startup_readiness_is_ignored(self) -> None:
        """startup.* readiness samples never file, however slow."""
        slow = perf_issues.evaluate_startup_event(
            duration_ms=72420.56, operation="startup.readiness"
        )
        warning = perf_issues.evaluate_startup_event(
            duration_ms=2100.0, operation="startup.readiness", now=6_000_000.0
        )

        assert slow is not None and slow.action == "ignore"
        assert warning is not None and warning.action == "ignore"

    def test_handle_startup_telemetry_does_not_schedule(self) -> None:
        """Startup telemetry logs and never schedules a GitHub issue."""
        with patch.object(perf_issues, "schedule_filing", new=MagicMock()) as mock_schedule:
            perf_issues.handle_startup_telemetry(
                duration_ms=72420.56,
                operation="startup.readiness",
                deployment_id="dpl_1",
            )

        mock_schedule.assert_not_called()


class TestDailyBreachThreshold:
    """A route files only after N warm over-budget hits in a UTC day."""

    def test_n_minus_one_breaches_do_not_file(self) -> None:
        """Default N=3: the first two over-budget hits only accumulate."""
        base = 3_000_000.0
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1472.44,
                cold=False,
                now=base + i,
            )
            for i in range(2)
        ]

        assert [d.action if d else None for d in actions] == [
            "accumulate",
            "accumulate",
        ]

    def test_nth_breach_files(self) -> None:
        """Default N=3: the third warm over-budget hit files."""
        base = 3_100_000.0
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1500.0,
                cold=False,
                now=base + i,
            )
            for i in range(3)
        ]

        assert [d.action if d else None for d in actions] == [
            "accumulate",
            "accumulate",
            "file",
        ]
        assert actions[2] is not None and actions[2].high_priority is True

    def test_new_utc_day_resets_threshold(self) -> None:
        """Hits from yesterday do not count toward today's N."""
        from datetime import UTC, datetime

        day1 = datetime(2026, 10, 12, tzinfo=UTC).timestamp()
        day2 = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
        for i in range(2):
            decision = perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1500.0,
                cold=False,
                now=day1 + i,
            )
            assert decision is not None and decision.action == "accumulate"
        first_new_day = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1500.0,
            cold=False,
            now=day2,
        )
        assert first_new_day is not None and first_new_day.action == "accumulate"
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1500.0,
                cold=False,
                now=day2 + i,
            )
            for i in range(1, 3)
        ]
        assert [d.action if d else None for d in actions] == ["accumulate", "file"]

    def test_different_routes_do_not_combine(self) -> None:
        """Daily hits accumulate per method+route fingerprint, not globally."""
        base = 3_200_000.0
        for i in range(2):
            decision = perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1500.0,
                cold=False,
                now=base + i,
            )
            assert decision is not None and decision.action == "accumulate"
        other = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/threads",
            duration_ms=1500.0,
            cold=False,
            now=base + 2,
        )
        assert other is not None and other.action == "accumulate"

    def test_closed_issue_regression_uses_same_threshold(self) -> None:
        """After a close, a route must hit N warm over-budget samples again."""
        base = 3_300_000.0
        filed = None
        for i in range(3):
            filed = perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1600.0,
                cold=False,
                now=base + i,
            )
        assert filed is not None and filed.action == "file"
        tracker = perf_issues.get_tracker()
        tracker.mark_open(filed.fingerprint, 111)
        tracker.mark_closed(filed.fingerprint, 111)

        first_after_close = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1700.0,
            cold=False,
            now=base + 10,
        )
        assert first_after_close is not None
        assert first_after_close.action == "accumulate"

        body = perf_issues.build_issue_body(
            kind="request",
            fingerprint=filed.fingerprint,
            canonical=filed.canonical,
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1700.0,
            threshold_ms=1000.0,
            event_label="violation",
            prior_issue=111,
        )
        assert "#111" in body
        assert "Regression" in body


class TestConfigOverride:
    """PERF_ALARM_DAILY_BREACH_THRESHOLD changes the filing threshold."""

    def test_default_threshold_is_three(self) -> None:
        """Documented default N is 3."""
        assert perf_issues.daily_breach_threshold() == 3
        assert perf_issues.DEFAULT_DAILY_BREACH_THRESHOLD == 3

    def test_env_override_requires_five_hits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N=5 via env: four over-budget hits do not file, the fifth does."""
        monkeypatch.setenv("PERF_ALARM_DAILY_BREACH_THRESHOLD", "5")
        from app.config import clear_settings_cache

        clear_settings_cache()
        try:
            assert perf_issues.daily_breach_threshold() == 5
            base = 4_000_000.0
            actions = [
                perf_issues.evaluate_request_event(
                    method="GET",
                    route_template="/api/v1/creators",
                    duration_ms=1500.0,
                    cold=False,
                    now=base + i,
                )
                for i in range(5)
            ]
            assert [d.action if d else None for d in actions] == [
                "accumulate",
                "accumulate",
                "accumulate",
                "accumulate",
                "file",
            ]
        finally:
            clear_settings_cache()


class TestFingerprintDedupe:
    """Dedupe key is kind plus method+route, not warm/cold or subsystem."""

    def test_repeat_over_budget_for_open_issue_updates(self) -> None:
        """A repeat over-budget hit comments on the existing open issue."""
        first = None
        base = 5_000_000.0
        for i in range(3):
            first = perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=1500.0,
                cold=False,
                now=base + i,
            )
        assert first is not None and first.action == "file"
        perf_issues.get_tracker().mark_open(first.fingerprint, 1234)

        repeat = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1700.0,
            cold=False,
            now=base + 10,
        )

        assert repeat is not None
        assert repeat.action == "update"
        assert repeat.fingerprint == first.fingerprint

    def test_occurrence_comment_includes_sample_evidence(self) -> None:
        """Update comments carry duration, warm/cold, DB, request, deployment."""
        comment = perf_issues.build_occurrence_comment(
            duration_ms=1637.97,
            cold=False,
            db_queries=12,
            db_time_ms=900.0,
            request_id="req-9",
            deployment_id="dpl_1",
            occurrence_count=4,
            reason="repeat over-budget hit for known open fingerprint",
        )

        assert "1637.97" in comment
        assert "warm" in comment
        assert "DB queries: 12" in comment
        assert "DB time: 900.00 ms" in comment
        assert "req-9" in comment
        assert "dpl_1" in comment
        assert "Occurrence count: 4" in comment

    def test_occurrence_evidence_aggregates(self) -> None:
        """Repeated events aggregate count, timings, and request ids."""
        tracker = perf_issues.get_tracker()
        now = 5_000_000.0
        fp, canonical = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
        )
        for i in range(3):
            tracker.record_occurrence(
                fingerprint=fp,
                canonical=canonical,
                duration_ms=1500.0 + i,
                request_id=f"req-{i}",
                deployment_id="dpl_1",
                now=now + i,
            )

        evidence = tracker.occurrence_for(fp)

        assert evidence is not None
        assert evidence.count == 3
        assert evidence.first_seen == now
        assert evidence.last_seen == now + 2
        assert evidence.recent_request_ids == ["req-0", "req-1", "req-2"]
        assert evidence.latest_deployment_id == "dpl_1"

    def test_phase_and_workload_share_one_fingerprint(self) -> None:
        """SQL-heavy and app-heavy samples on one route share an issue."""
        fp, canonical = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
        )
        again, again_canonical = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
        )

        assert fp == again
        assert canonical == "request|GET|/api/v1/creators"
        assert again_canonical == canonical
        assert perf_issues.classify_workload(1500.0, 1400.0, 40) == "db-heavy"
        assert perf_issues.classify_workload(1500.0, 50.0, 2) == "app-heavy"

    def test_method_and_route_distinguish_fingerprints(self) -> None:
        """Different methods or routes remain independent issues."""
        get_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
        )
        post_fp, _ = perf_issues.fingerprint_for_request(
            method="POST",
            route_template="/api/v1/creators",
        )
        other_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/threads",
        )

        assert get_fp != post_fp
        assert get_fp != other_fp

    def test_deployment_is_not_the_dedupe_key(self) -> None:
        """The same route across deployments shares one fingerprint."""
        first, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
        )
        second, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
        )

        assert first == second


class TestCoroutineTimeout:
    """Readiness-critical coroutine timeouts still file immediately."""

    def test_coroutine_timeout_files_immediately(self) -> None:
        """A readiness-critical coroutine timeout files immediately."""
        decision = perf_issues.evaluate_coroutine_timeout(
            operation="startup.neon_monitor"
        )

        assert decision.action == "file"
        assert decision.high_priority is True

    def test_coroutine_timeout_dedupes_by_operation(self) -> None:
        """The same named timeout updates its open issue; others file separately."""
        tracker = perf_issues.get_tracker()
        first = perf_issues.evaluate_coroutine_timeout(operation="startup.neon_monitor")
        tracker.mark_open(first.fingerprint, 222)

        repeat = perf_issues.evaluate_coroutine_timeout(
            operation="startup.neon_monitor"
        )
        other = perf_issues.evaluate_coroutine_timeout(
            operation="startup.database_initialization"
        )

        assert repeat.action == "update"
        assert other.action == "file"


class TestIssueContentAndLabels:
    """Generated issues carry evidence, executable labels, and no secrets."""

    def test_labels_are_executable_and_never_user_reported(self) -> None:
        """Machine issues enter the factory queue without user-reported."""
        labels = perf_issues.build_labels(high_priority=True, subsystem="backend")

        assert "bug" in labels
        assert "performance" in labels
        assert "ralph-task" in labels
        assert "ralph-status:pending" in labels
        assert "factory" in labels
        assert "factory:unowned" in labels
        assert "backend" in labels
        assert "ralph-priority:high" in labels
        assert "user-reported" not in labels

    def test_warning_labels_skip_high_priority(self) -> None:
        """Warning-threshold issues stay at normal priority."""
        labels = perf_issues.build_labels(high_priority=False, subsystem="api")

        assert "ralph-priority:high" not in labels
        assert "api" in labels

    def test_body_includes_required_evidence(self) -> None:
        """Issue bodies include timings, DB diagnostics, and thresholds."""
        body = perf_issues.build_issue_body(
            kind="request",
            fingerprint="abc123",
            canonical="request|GET|/api/v1/creators",
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1637.97,
            threshold_ms=1000.0,
            event_label="violation",
            cold=False,
            db_queries=12,
            db_time_ms=900.0,
            app_time_ms=737.97,
            request_ids=["req-1"],
            deployment_id="dpl_2NbKM8NeQoC4B4GX3xEj6ddYDYca",
            server_timing="app;dur=1637.97, db;dur=900.00",
            likely_subsystem="database",
        )

        assert "GET /api/v1/creators" in body
        assert "1637.97" in body
        assert "1000 ms" in body
        assert "warm" in body
        assert "DB queries: 12" in body
        assert "DB time: 900.00 ms" in body
        assert "Application time: 737.97 ms" in body
        assert "req-1" in body
        assert "dpl_2NbKM8NeQoC4B4GX3xEj6ddYDYca" in body
        assert "Server-Timing" in body
        assert "performance-fingerprint:v1:abc123" in body
        # Subsystem is a hint, never a claimed root cause.
        assert "not a proven root cause" in body

    def test_secret_redaction(self) -> None:
        """Credential-shaped evidence is redacted from issue bodies."""
        body = perf_issues.build_issue_body(
            kind="request",
            fingerprint="abc123",
            canonical="request|GET|/x",
            method="GET",
            route_template="/x",
            duration_ms=1500.0,
            threshold_ms=1000.0,
            event_label="violation",
            server_timing="app;dur=1500.00",
            deployment_id="dpl_1",
            request_ids=["authorization: Bearer super-secret-token"],
        )

        assert "super-secret-token" not in body
        assert "[REDACTED]" in body

    def test_sanitize_evidence_text_redacts_credentials(self) -> None:
        """Known credential patterns are redacted, safe text is preserved."""
        assert (
            perf_issues.sanitize_evidence_text("authorization: Bearer abc123")
            == "authorization: [REDACTED]"
        )
        assert (
            perf_issues.sanitize_evidence_text("cookie: session=xyz")
            == "cookie: [REDACTED]"
        )
        assert (
            perf_issues.sanitize_evidence_text("GET /api/v1/creators")
            == "GET /api/v1/creators"
        )


class TestBackgroundFiling:
    """GitHub latency/failure never delays or fails the production request."""

    @pytest.mark.asyncio
    async def test_file_decision_creates_issue(self) -> None:
        """A file decision creates one issue and records it as open."""
        decision = perf_issues.FilingDecision(
            action="file",
            fingerprint="fp1",
            canonical="request|GET|/a",
            high_priority=True,
            reason="test",
        )
        with (
            patch(
                "app.services.github_service.find_open_issue_by_fingerprint",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.github_service.find_closed_issue_by_fingerprint",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.github_service.create_performance_issue",
                new=AsyncMock(
                    return_value="https://github.com/o/r/issues/777"
                ),
            ) as mock_create,
        ):
            await perf_issues._file_decision_background(
                decision=decision,
                title="Performance: GET /a took 1500ms (budget 1000ms)",
                body="evidence\n\n<!-- performance-fingerprint:v1:fp1 -->",
                labels=perf_issues.build_labels(high_priority=True),
            )

        mock_create.assert_awaited_once()
        assert perf_issues.get_tracker().open_issue_for("fp1") == 777

    @pytest.mark.asyncio
    async def test_update_decision_comments_without_new_issue(self) -> None:
        """An update decision comments on the open issue instead of filing."""
        tracker = perf_issues.get_tracker()
        tracker.mark_open("fp2", 555)
        decision = perf_issues.FilingDecision(
            action="update",
            fingerprint="fp2",
            canonical="request|GET|/a",
            high_priority=True,
            reason="repeat violation",
        )
        with (
            patch(
                "app.services.github_service.add_performance_issue_comment",
                new=AsyncMock(return_value="open"),
            ) as mock_comment,
            patch(
                "app.services.github_service.create_performance_issue",
                new=AsyncMock(),
            ) as mock_create,
        ):
            await perf_issues._file_decision_background(
                decision=decision,
                title="t",
                body="b",
                labels=perf_issues.build_labels(high_priority=True),
            )

        mock_comment.assert_awaited_once()
        mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_on_externally_closed_issue_files_regression(self) -> None:
        """A recurrence against an externally closed issue files a new regression issue."""
        tracker = perf_issues.get_tracker()
        tracker.mark_open("fp-closed", 4242)
        decision = perf_issues.FilingDecision(
            action="update",
            fingerprint="fp-closed",
            canonical="request|GET|/a",
            high_priority=True,
            reason="repeat violation",
        )
        with (
            patch(
                "app.services.github_service.add_performance_issue_comment",
                new=AsyncMock(return_value="closed"),
            ) as mock_comment,
            patch(
                "app.services.github_service.find_open_issue_by_fingerprint",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.github_service.find_closed_issue_by_fingerprint",
                new=AsyncMock(return_value=4242),
            ),
            patch(
                "app.services.github_service.create_performance_issue",
                new=AsyncMock(
                    return_value="https://github.com/o/r/issues/9001"
                ),
            ) as mock_create,
        ):
            await perf_issues._file_decision_background(
                decision=decision,
                title="t",
                body="evidence\n\n<!-- performance-fingerprint:v1:fp-closed -->",
                labels=perf_issues.build_labels(high_priority=True),
            )

        mock_comment.assert_awaited_once()
        mock_create.assert_awaited_once()
        assert mock_create.await_args is not None
        created_body = mock_create.await_args.kwargs["body"]
        assert "#4242" in created_body
        assert "Regression" in created_body
        assert tracker.open_issue_for("fp-closed") == 9001

    @pytest.mark.asyncio
    async def test_github_failure_is_logged_not_raised(self) -> None:
        """GitHub failure is observable but never raises to the request path."""
        decision = perf_issues.FilingDecision(
            action="file",
            fingerprint="fp3",
            canonical="request|GET|/a",
            high_priority=True,
            reason="test",
        )
        with (
            patch(
                "app.services.github_service.find_open_issue_by_fingerprint",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.github_service.find_closed_issue_by_fingerprint",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.github_service.create_performance_issue",
                new=AsyncMock(side_effect=RuntimeError("GitHub is down")),
            ),
        ):
            # Must not raise.
            await perf_issues._file_decision_background(
                decision=decision, title="t", body="b", labels=["bug"]
            )

        assert perf_issues.get_tracker().open_issue_for("fp3") is None

    def test_handle_request_telemetry_schedules_without_blocking(self) -> None:
        """The Nth over-budget hit delegates to bounded background work."""

        async def _run() -> None:
            with patch.object(
                perf_issues, "schedule_filing", new=MagicMock()
            ) as mock_schedule:
                for _ in range(3):
                    perf_issues.handle_request_telemetry(
                        method="GET",
                        route_template="/api/v1/creators",
                        duration_ms=1637.97,
                        cold=False,
                        db_queries=12,
                        db_time_ms=900.0,
                        request_id="req-9",
                        deployment_id="dpl_1",
                        server_timing="app;dur=1637.97",
                    )
                await asyncio.sleep(0)
                mock_schedule.assert_called_once()
                comment = mock_schedule.call_args.kwargs["comment"]
                assert comment is not None
                assert "1637.97" in comment
                assert "req-9" in comment
                assert "dpl_1" in comment

        asyncio.run(_run())

    def test_handle_request_telemetry_ignores_cold_starts(self) -> None:
        """Cold over-budget requests never schedule filing."""

        async def _run() -> None:
            with patch.object(
                perf_issues, "schedule_filing", new=MagicMock()
            ) as mock_schedule:
                for _ in range(5):
                    perf_issues.handle_request_telemetry(
                        method="GET",
                        route_template="/api/v1/roll/bootstrap",
                        duration_ms=3500.0,
                        cold=True,
                    )
                await asyncio.sleep(0)
                mock_schedule.assert_not_called()

        asyncio.run(_run())

    def test_handle_request_telemetry_ignores_under_budget_warnings(self) -> None:
        """Under-budget warnings never schedule filing."""

        async def _run() -> None:
            with patch.object(
                perf_issues, "schedule_filing", new=MagicMock()
            ) as mock_schedule:
                for _ in range(5):
                    perf_issues.handle_request_telemetry(
                        method="GET",
                        route_template="/api/v1/creators",
                        duration_ms=575.0,
                        cold=False,
                    )
                await asyncio.sleep(0)
                mock_schedule.assert_not_called()

        asyncio.run(_run())

    def test_handle_request_telemetry_ignores_healthy_requests(self) -> None:
        """Healthy requests schedule nothing."""

        async def _run() -> None:
            with patch.object(
                perf_issues, "schedule_filing", new=MagicMock()
            ) as mock_schedule:
                perf_issues.handle_request_telemetry(
                    method="GET",
                    route_template="/api/v1/creators",
                    duration_ms=120.0,
                    cold=False,
                )
                await asyncio.sleep(0)
                mock_schedule.assert_not_called()

        asyncio.run(_run())


class TestPerformanceGithubClient:
    """The isolated performance GitHub client keeps user-report semantics apart."""

    @pytest.mark.asyncio
    async def test_create_performance_issue_rejects_user_reported(self) -> None:
        """Machine issues must never carry the user-reported label."""
        from app.services import github_service as gh

        with pytest.raises(RuntimeError, match="user-reported"):
            await gh.create_performance_issue(
                title="t", body="b", labels=["bug", "user-reported"]
            )

    @pytest.mark.asyncio
    async def test_create_performance_issue_uses_factory_labels(self) -> None:
        """Creation passes the executable label set to the GitHub API."""
        from app.services import github_service as gh

        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.html_url = "https://github.com/o/r/issues/888"
        mock_repo.create_issue.return_value = mock_issue
        mock_github = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo
        mock_settings = MagicMock()
        mock_settings.is_configured = True
        mock_settings.github_token = "token"
        mock_settings.github_repo_owner = "o"
        mock_settings.github_repo_name = "r"

        with (
            patch.object(gh, "Github", mock_github),
            patch.object(gh, "get_github_settings", return_value=mock_settings),
        ):
            from app.services import performance_issue_service as svc

            url = await gh.create_performance_issue(
                title="Performance: GET /a took 1500ms (budget 1000ms)",
                body="evidence",
                labels=svc.build_labels(high_priority=True),
            )

        assert url == "https://github.com/o/r/issues/888"
        created_labels = mock_repo.create_issue.call_args.kwargs["labels"]
        assert "user-reported" not in created_labels
        assert "factory" in created_labels

    @pytest.mark.asyncio
    async def test_find_open_issue_matches_fingerprint_marker(self) -> None:
        """Dedupe matches the hidden fingerprint marker, not the URL."""
        from app.services import github_service as gh

        match = MagicMock()
        match.number = 42
        match.body = "evidence\n\n<!-- performance-fingerprint:v1:deadbeef -->\n"
        match.pull_request = None
        other = MagicMock()
        other.number = 43
        other.body = "evidence\n\n<!-- performance-fingerprint:v1:other -->\n"
        other.pull_request = None
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = [other, match]
        mock_github = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo
        mock_settings = MagicMock()
        mock_settings.is_configured = True
        mock_settings.github_token = "token"
        mock_settings.github_repo_owner = "o"
        mock_settings.github_repo_name = "r"

        with (
            patch.object(gh, "Github", mock_github),
            patch.object(gh, "get_github_settings", return_value=mock_settings),
        ):
            assert await gh.find_open_issue_by_fingerprint("deadbeef") == 42
            assert await gh.find_open_issue_by_fingerprint("missing") is None

    @pytest.mark.asyncio
    async def test_github_lookup_failure_raises_runtime_error(self) -> None:
        """GitHub API failures surface as RuntimeError for the caller to log."""
        from github import GithubException

        from app.services import github_service as gh

        mock_repo = MagicMock()
        mock_repo.get_issues.side_effect = GithubException(500, "boom", {})
        mock_github = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo
        mock_settings = MagicMock()
        mock_settings.is_configured = True
        mock_settings.github_token = "token"
        mock_settings.github_repo_owner = "o"
        mock_settings.github_repo_name = "r"

        with (
            patch.object(gh, "Github", mock_github),
            patch.object(gh, "get_github_settings", return_value=mock_settings),
        ):
            with pytest.raises(RuntimeError, match="search"):
                await gh.find_open_issue_by_fingerprint("deadbeef")


class TestMiddlewareIntegration:
    """Slow requests trigger evaluation without changing the response."""

    def test_slow_request_evaluates_performance_issue_path(self) -> None:
        """A slow response still succeeds while evaluation runs exactly once."""
        import time as time_module

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.middleware.request_logging import add_request_logging_middleware

        app = FastAPI()
        add_request_logging_middleware(app, "test")

        @app.get("/slow-issue-path")
        async def slow_endpoint() -> dict[str, str]:
            time_module.sleep(0.6)
            return {"message": "slow but complete"}

        client = TestClient(app)
        with patch.object(
            perf_issues, "handle_request_telemetry", new=MagicMock()
        ) as mock_handle:
            response = client.get("/slow-issue-path")

        assert response.status_code == 200
        assert response.json() == {"message": "slow but complete"}
        mock_handle.assert_called_once()
        assert mock_handle.call_args.kwargs["duration_ms"] >= 500
