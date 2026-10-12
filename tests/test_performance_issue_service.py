"""Tests for automatic GitHub issue filing from performance violations."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import performance_issue_service as perf_issues

GitHubCall = tuple[str, dict, dict]
GitHubHandler = Callable[[str, dict, dict], object]


def _github_settings_double() -> MagicMock:
    """Build configured GitHub settings pointing at the ``o/r`` repository."""
    settings = MagicMock()
    settings.is_configured = True
    settings.github_token = "token"
    settings.github_repo_owner = "o"
    settings.github_repo_name = "r"
    return settings


def _json_response(payload: object, status_code: int = 200) -> MagicMock:
    """Build an httpx response double that decodes to ``payload``."""
    response = MagicMock()
    response.status_code = status_code
    response.text = f"status {status_code}"
    response.json.return_value = payload

    def _raise_for_status() -> None:
        """Fail GitHub error statuses like the real client, pass the rest."""
        if status_code < 400:
            return
        request = httpx.Request("POST", "https://api.github.com/repos/o/r/issues")
        raise httpx.HTTPStatusError(
            f"status {status_code}",
            request=request,
            response=httpx.Response(status_code, text=response.text, request=request),
        )

    response.raise_for_status = _raise_for_status
    return response


def _github_client_double(
    *,
    post_handler: GitHubHandler | None = None,
    get_handler: GitHubHandler | None = None,
) -> tuple[type, dict[str, list[GitHubCall]]]:
    """Build an ``httpx.AsyncClient`` double and its recorded call log.

    The GitHub client is exercised through the async HTTP transport rather
    than a stubbed SDK object so the tests cover the real request shape,
    headers, and round-trip count used by the production route.

    Args:
        post_handler: Callable answering ``POST`` requests.
        get_handler: Callable answering ``GET`` requests.

    Returns:
        A tuple of the patchable client class and a ``{"post": [...],
        "get": [...]}`` call log keyed by HTTP method.
    """
    calls: dict[str, list[GitHubCall]] = {"post": [], "get": []}

    def _handle(
        method: str,
        handler: GitHubHandler | None,
        url: str,
        headers: dict,
        payload: dict,
    ) -> object:
        """Record a call and delegate to the configured handler."""
        calls[method].append((url, headers, payload))
        if handler is None:
            raise AssertionError(f"Unexpected {method.upper()} request to {url}")
        return handler(url, headers, payload)

    class _AsyncClientDouble:
        def __init__(self, *args: object, **kwargs: object) -> None:
            """Accept and discard transport options such as ``timeout``."""

        async def __aenter__(self) -> _AsyncClientDouble:
            """Enter the async context manager."""
            return self

        async def __aexit__(self, *args: object) -> None:
            """Exit the async context manager."""
            return None

        async def post(self, url: str, headers: dict, json: dict) -> object:
            """Record and answer a ``POST`` request."""
            return _handle("post", post_handler, url, headers, json)

        async def get(self, url: str, headers: dict, params: dict | None = None) -> object:
            """Record and answer a ``GET`` request."""
            return _handle("get", get_handler, url, headers, params or {})

    return _AsyncClientDouble, calls


@pytest.fixture(autouse=True)
def _clean_tracker():
    """Isolate process-local performance issue state between tests."""
    perf_issues.reset_for_tests()
    yield
    perf_issues.reset_for_tests()


class TestImmediateViolationFiling:
    """Warm requests at or above 1000 ms file immediately."""

    def test_violation_files_immediately(self) -> None:
        """A >=1 s warm request returns a high-priority file decision."""
        decision = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1472.44,
            cold=False,
        )

        assert decision is not None
        assert decision.action == "file"
        assert decision.high_priority is True
        assert "1000" in decision.reason or "immediately" in decision.reason

    def test_sub_violation_warning_does_not_file_immediately(self) -> None:
        """A single 500-999 ms warning only accumulates."""
        decision = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=750.0,
            cold=False,
            now=1_000_000.0,
        )

        assert decision is not None
        assert decision.action == "accumulate"
        assert decision.high_priority is False

    def test_healthy_request_returns_no_decision(self) -> None:
        """A request inside budget produces no filing decision."""
        assert (
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=120.0,
                cold=False,
            )
            is None
        )


class TestWarningAccumulation:
    """Repeated 500-999 ms warnings file at the defined frequency thresholds."""

    def test_three_warnings_within_ten_minutes_file(self) -> None:
        """3 warnings on the same route within 10 minutes file an issue."""
        base = 2_000_000.0
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=600.0,
                cold=False,
                now=base + offset,
            )
            for offset in (0.0, 120.0, 240.0)
        ]

        assert [d.action if d else None for d in actions] == [
            "accumulate",
            "accumulate",
            "file",
        ]
        assert actions[2] is not None and actions[2].high_priority is False

    def test_five_warnings_within_one_hour_file(self) -> None:
        """5 warnings on the same route within 1 hour file an issue."""
        base = 3_000_000.0
        # Spaced 12 minutes apart: never 3 within 10 minutes, but 5 within 1 hour.
        actions = [
            perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/threads",
                duration_ms=600.0,
                cold=False,
                now=base + i * 720.0,
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

    def test_warnings_on_different_routes_do_not_combine(self) -> None:
        """Warnings accumulate per normalized route, not globally."""
        base = 4_000_000.0
        for i in range(2):
            decision = perf_issues.evaluate_request_event(
                method="GET",
                route_template="/api/v1/creators",
                duration_ms=600.0,
                cold=False,
                now=base + i * 60.0,
            )
            assert decision is not None and decision.action == "accumulate"
        other = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/threads",
            duration_ms=600.0,
            cold=False,
            now=base + 120.0,
        )
        assert other is not None and other.action == "accumulate"


class TestFingerprintDedupe:
    """Identical repeated events update evidence instead of duplicating issues."""

    def test_repeat_violation_for_open_fingerprint_updates(self) -> None:
        """A repeat violation for a known open issue updates instead of filing."""
        first = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1500.0,
            cold=False,
        )
        assert first is not None and first.action == "file"
        perf_issues.get_tracker().mark_open(first.fingerprint, 1234)

        repeat = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1700.0,
            cold=False,
        )

        assert repeat is not None
        assert repeat.action == "update"
        assert repeat.fingerprint == first.fingerprint

    def test_occurrence_evidence_aggregates(self) -> None:
        """Repeated events aggregate count, timings, and request ids."""
        tracker = perf_issues.get_tracker()
        now = 5_000_000.0
        fp, canonical = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
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


class TestIndependentSignatureSplitting:
    """Distinct signatures on the same route can produce separate issues."""

    def test_dominant_phase_splits_signatures(self) -> None:
        """SQL-dominated vs serialization-dominated reads get own fingerprints."""
        sql_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
            dominant_phase="sql-aggregation",
            db_time_ms=1400.0,
            duration_ms=1500.0,
            db_queries=40,
        )
        serial_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
            dominant_phase="serialization",
            db_time_ms=50.0,
            duration_ms=1500.0,
            db_queries=2,
        )

        assert sql_fp != serial_fp

    def test_workload_classification_splits_signatures(self) -> None:
        """DB-heavy and app-heavy events on one route are distinct signatures."""
        db_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
            db_time_ms=1400.0,
            duration_ms=1500.0,
            db_queries=40,
        )
        app_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
            db_time_ms=50.0,
            duration_ms=1500.0,
            db_queries=2,
        )

        assert db_fp != app_fp
        assert perf_issues.classify_workload(1500.0, 1400.0, 40) == "db-heavy"
        assert perf_issues.classify_workload(1500.0, 50.0, 2) == "app-heavy"

    def test_cold_and_warm_split_signatures(self) -> None:
        """Cold-start and warm events on one route are distinct signatures."""
        warm_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/roll/bootstrap",
            cold=False,
        )
        cold_fp, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/roll/bootstrap",
            cold=True,
        )

        assert warm_fp != cold_fp

    def test_deployment_is_not_the_dedupe_key(self) -> None:
        """The same signature across deployments shares one fingerprint."""
        first, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
        )
        second, _ = perf_issues.fingerprint_for_request(
            method="GET",
            route_template="/api/v1/creators",
            cold=False,
        )

        assert first == second


class TestClosedIssueRegression:
    """A regression after a closed issue opens a new referencing issue."""

    def test_regression_opens_new_issue_referencing_prior(self) -> None:
        """A repeat signature after close files with a regression reference."""
        decision = perf_issues.evaluate_request_event(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1500.0,
            cold=False,
        )
        assert decision is not None
        tracker = perf_issues.get_tracker()
        tracker.mark_open(decision.fingerprint, 111)
        tracker.mark_closed(decision.fingerprint, 111)

        assert tracker.open_issue_for(decision.fingerprint) is None
        assert tracker.closed_issue_for(decision.fingerprint) == 111

        body = perf_issues.build_issue_body(
            kind="request",
            fingerprint=decision.fingerprint,
            canonical=decision.canonical,
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1500.0,
            threshold_ms=1000.0,
            event_label="violation",
            prior_issue=111,
        )

        assert "#111" in body
        assert "Regression" in body

    def test_startup_hard_failure_files_immediately(self) -> None:
        """Startup at or above 2.5 s files immediately with high priority."""
        decision = perf_issues.evaluate_startup_event(
            duration_ms=72420.56, operation="startup.readiness"
        )

        assert decision is not None
        assert decision.action == "file"
        assert decision.high_priority is True

    def test_startup_warnings_file_on_second_within_hour(self) -> None:
        """Two 2.0-2.5 s startups within 1 hour file an issue."""
        first = perf_issues.evaluate_startup_event(
            duration_ms=2100.0, operation="startup.readiness", now=6_000_000.0
        )
        second = perf_issues.evaluate_startup_event(
            duration_ms=2200.0, operation="startup.readiness", now=6_001_800.0
        )

        assert first is not None and first.action == "accumulate"
        assert second is not None and second.action == "file"

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
            canonical="request|GET|/api/v1/creators|warm|unknown|mixed",
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
            canonical="request|GET|/x|warm|unknown|mixed",
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
            canonical="request|GET|/a|warm|unknown|mixed",
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
            canonical="request|GET|/a|warm|unknown|mixed",
            high_priority=True,
            reason="repeat violation",
        )
        with (
            patch(
                "app.services.github_service.add_performance_issue_comment",
                new=AsyncMock(),
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
            canonical="request|GET|/a|warm|unknown|mixed",
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
            canonical="request|GET|/a|warm|unknown|mixed",
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
        """The request entry point delegates to bounded background work."""

        async def _run() -> None:
            with patch.object(
                perf_issues, "schedule_filing", new=MagicMock()
            ) as mock_schedule:
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

        recorded: dict[str, object] = {}

        def _post(url: str, headers: dict, payload: dict) -> object:
            """Record the creation payload and return a created issue."""
            recorded.update(payload)
            return _json_response({"html_url": "https://github.com/o/r/issues/888"})

        client_double, calls = _github_client_double(post_handler=_post)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            from app.services import performance_issue_service as svc

            url = await gh.create_performance_issue(
                title="Performance: GET /a took 1500ms (budget 1000ms)",
                body="evidence",
                labels=svc.build_labels(high_priority=True),
            )

        assert url == "https://github.com/o/r/issues/888"
        assert calls["post"] == [
            (
                "https://api.github.com/repos/o/r/issues",
                {
                    "Authorization": "Bearer token",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                {
                    "title": "Performance: GET /a took 1500ms (budget 1000ms)",
                    "body": "evidence",
                    "labels": svc.build_labels(high_priority=True),
                },
            )
        ]
        assert calls["get"] == []
        created_labels = recorded["labels"]
        assert isinstance(created_labels, list)
        assert "user-reported" not in created_labels
        assert "factory" in created_labels

    @pytest.mark.asyncio
    async def test_create_performance_issue_uses_single_round_trip(self) -> None:
        """Issue creation never pre-resolves the repository before posting."""
        from app.services import github_service as gh

        client_double, calls = _github_client_double(
            post_handler=lambda url, headers, payload: _json_response(
                {"html_url": "https://github.com/o/r/issues/1"}
            )
        )

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            url = await gh.create_performance_issue(
                title="t", body="b", labels=["bug", "performance"]
            )

        assert url == "https://github.com/o/r/issues/1"
        assert len(calls["post"]) == 1
        assert calls["get"] == []

    @pytest.mark.asyncio
    async def test_create_performance_issue_requires_configured_github(self) -> None:
        """An unconfigured GitHub integration fails before any HTTP request."""
        from app.services import github_service as gh

        settings = _github_settings_double()
        settings.is_configured = False
        client_double, calls = _github_client_double()

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(gh, "get_github_settings", return_value=settings),
        ):
            with pytest.raises(RuntimeError, match="not configured"):
                await gh.create_performance_issue(title="t", body="b", labels=["bug"])

        assert calls == {"post": [], "get": []}

    @pytest.mark.asyncio
    async def test_find_open_issue_matches_fingerprint_marker(self) -> None:
        """Dedupe matches the hidden fingerprint marker, not the URL."""
        from app.services import github_service as gh

        issues = [
            {"number": 43, "body": "evidence\n\n<!-- performance-fingerprint:v1:other -->"},
            {"number": 44, "body": None, "pull_request": {"url": "https://api/pulls/44"}},
            {"number": 42, "body": "evidence\n\n<!-- performance-fingerprint:v1:deadbeef -->\n"},
        ]
        client_double, calls = _github_client_double(
            get_handler=lambda url, headers, params: _json_response(issues)
        )

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            assert await gh.find_open_issue_by_fingerprint("deadbeef") == 42
            assert await gh.find_open_issue_by_fingerprint("missing") is None

        assert calls["get"][0][0] == "https://api.github.com/repos/o/r/issues"
        assert calls["get"][0][2]["state"] == "open"
        assert calls["get"][0][2]["labels"] == "performance"
        assert calls["get"][1][2]["state"] == "open"

    @pytest.mark.asyncio
    async def test_find_closed_issue_searches_closed_state(self) -> None:
        """Closed-issue dedupe searches the closed state for regressions."""
        from app.services import github_service as gh

        issues = [{"number": 7, "body": "<!-- performance-fingerprint:v1:abc -->"}]
        client_double, calls = _github_client_double(
            get_handler=lambda url, headers, params: _json_response(issues)
        )

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            assert await gh.find_closed_issue_by_fingerprint("abc") == 7

        assert calls["get"][0][2]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_find_open_issue_matches_legacy_fingerprint(self) -> None:
        """Rollout lookup reuses an issue tagged with the pre-#3552 hash."""
        from app.services import github_service as gh

        issues = [
            {
                "number": 3560,
                "body": "evidence\n\n<!-- performance-fingerprint:v1:baa678d6d31003dd -->\n",
                "title": "Performance: GET /api/v1/roll/bootstrap took 1500ms (budget 1000ms)",
            }
        ]
        client_double, calls = _github_client_double(
            get_handler=lambda url, headers, params: _json_response(issues)
        )

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            found = await gh.find_open_issue_by_fingerprint(
                "91eb38be9dc36a6d",
                extra_fingerprints=("baa678d6d31003dd",),
            )

        assert found == 3560

    @pytest.mark.asyncio
    async def test_find_open_issue_matches_method_and_route(self) -> None:
        """Rollout lookup reuses an issue by method plus route when hashes differ."""
        from app.services import github_service as gh

        issues = [
            {
                "number": 3561,
                "body": "- Method + route: GET /api/v1/roll/bootstrap\n<!-- performance-fingerprint:v1:oldhash -->",
                "title": "Performance: GET /api/v1/roll/bootstrap took 1637ms (budget 1000ms)",
            }
        ]
        client_double, calls = _github_client_double(
            get_handler=lambda url, headers, params: _json_response(issues)
        )

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            found = await gh.find_open_issue_by_fingerprint(
                "91eb38be9dc36a6d",
                method="GET",
                route_template="/api/v1/roll/bootstrap",
            )

        assert found == 3561

    @pytest.mark.asyncio
    async def test_get_performance_issue_state(self) -> None:
        """Reading issue state works without commenting."""
        from app.services import github_service as gh

        def _get(url: str, headers: dict, params: dict) -> object:
            """Return an open issue state."""
            return _json_response({"state": "open"})

        client_double, calls = _github_client_double(get_handler=_get)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            state = await gh.get_performance_issue_state(4242)

        assert state == "open"
        assert calls["get"][0][0] == "https://api.github.com/repos/o/r/issues/4242"

    @pytest.mark.asyncio
    async def test_github_lookup_failure_raises_runtime_error(self) -> None:
        """GitHub API failures surface as RuntimeError for the caller to log."""
        from app.services import github_service as gh

        request = httpx.Request("GET", "https://api.github.com/repos/o/r/issues")
        response = httpx.Response(500, text="boom", request=request)

        def _get(url: str, headers: dict, params: dict) -> object:
            """Fail the search with a GitHub server error."""
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        client_double, _ = _github_client_double(get_handler=_get)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            with pytest.raises(RuntimeError, match="search"):
                await gh.find_open_issue_by_fingerprint("deadbeef")

    @pytest.mark.asyncio
    async def test_github_transport_failure_raises_runtime_error(self) -> None:
        """Network errors surface as RuntimeError instead of leaking httpx."""
        from app.services import github_service as gh

        request = httpx.Request("GET", "https://api.github.com/repos/o/r/issues")

        def _get(url: str, headers: dict, params: dict) -> object:
            """Fail the search with a transport error."""
            raise httpx.ConnectError("no route", request=request)

        client_double, _ = _github_client_double(get_handler=_get)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            with pytest.raises(RuntimeError, match="search"):
                await gh.find_open_issue_by_fingerprint("deadbeef")

    @pytest.mark.asyncio
    async def test_add_comment_returns_post_comment_issue_state(self) -> None:
        """Recurrence comments report the issue state so regressions re-file."""
        from app.services import github_service as gh

        def _post(url: str, headers: dict, payload: dict) -> object:
            """Accept the recurrence comment."""
            return _json_response({"id": 1}, status_code=201)

        def _get(url: str, headers: dict, payload: dict) -> object:
            """Return a closed issue state."""
            return _json_response({"state": "closed"})

        client_double, calls = _github_client_double(post_handler=_post, get_handler=_get)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            state = await gh.add_performance_issue_comment(555, "recurred")

        assert state == "closed"
        assert calls["post"][0][0] == "https://api.github.com/repos/o/r/issues/555/comments"
        assert calls["post"][0][2] == {"body": "recurred"}
        assert calls["get"][0][0] == "https://api.github.com/repos/o/r/issues/555"

    @pytest.mark.asyncio
    async def test_issue_creation_failure_raises_runtime_error(self) -> None:
        """A GitHub error response becomes RuntimeError, never a KeyError."""
        from app.services import github_service as gh

        def _post(url: str, headers: dict, payload: dict) -> object:
            """Fail the creation with a GitHub validation error."""
            return _json_response({"message": "Validation Failed"}, status_code=422)

        client_double, _ = _github_client_double(post_handler=_post)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            with pytest.raises(RuntimeError, match="issue"):
                await gh.create_performance_issue(title="t", body="b", labels=["bug"])

    @pytest.mark.asyncio
    async def test_create_performance_issue_missing_url_raises_runtime_error(self) -> None:
        """A 2xx body without an issue URL becomes RuntimeError, never a KeyError."""
        from app.services import github_service as gh

        def _post(url: str, headers: dict, payload: dict) -> object:
            """Return a success body that carries no issue URL."""
            return _json_response({"message": "Validation Failed"})

        client_double, _ = _github_client_double(post_handler=_post)

        with (
            patch("app.services.github_service.httpx.AsyncClient", client_double),
            patch.object(
                gh, "get_github_settings", return_value=_github_settings_double()
            ),
        ):
            with pytest.raises(RuntimeError, match="response contained no issue URL"):
                await gh.create_performance_issue(title="t", body="b", labels=["bug"])


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
