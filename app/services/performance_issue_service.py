"""Optional GitHub issue filing for production performance violations.

Implements issue #3245 filing, #3552 noise controls and the default-off #3726 policy.

Policy:

- GitHub filing is disabled by default; telemetry and runtime budgets stay on.
- Explicitly opt in with ``PERF_ALARM_GITHUB_ISSUES_ENABLED=true``.
- Dedupe fingerprint is kind plus route identity: for requests that is
  ``method + route template``. Warm/cold, workload class, and dominant
  phase are evidence on the sample, never separate issues.
- Measurements at or under the route budget never open an issue. Warning
  samples (500-999 ms) are recorded or aggregated only. An issue title
  never shows a duration below its budget.
- Cold-start requests and ``startup.*`` readiness samples do not count
  toward filing. They are logged separately for cold-start work. Hard
  startup failures (2.5s or more) log at WARNING; issues #3479 and #3480
  do not consume ``performance_alarm_ignored_startup``.
- A route files only after N warm over-budget hits in the same UTC day.
  N defaults to 3 and is configurable via
  ``PERF_ALARM_DAILY_BREACH_THRESHOLD``. Closed-issue regressions use
  the same daily threshold.
- Daily counts and open-issue identity live in shared durable storage
  (Postgres ``perf_alarm_counters`` / ``perf_alarm_incidents``) so
  Vercel serverless instances share one counter. Process memory is not
  the production store.
- If an open issue already exists for the fingerprint, a new over-budget
  sample comments at most once per fingerprint per hour, and never
  comments on a closed issue.
- When enabled, readiness-critical coroutine hard timeouts file immediately
  unless the same coroutine signature already has an open issue.

Issue creation never blocks the user request: callers use the ``handle_*``
entry points, which dispatch bounded background work. GitHub API calls
run in a worker thread. GitHub API failure is logged and observable but
never fails the original request.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.performance_budgets import (
    REQUEST_TIMEOUT_MS,
    REQUEST_WARNING_MS,
    STARTUP_TIMEOUT_MS,
)
from app.services.perf_alarm_store import (
    InMemoryPerfAlarmStore,
    PerfAlarmStore,
    PostgresPerfAlarmStore,
)

logger = logging.getLogger(__name__)

# Daily over-budget threshold (issue #3552). Overridable via AppSettings.
DEFAULT_DAILY_BREACH_THRESHOLD = 3

# Retention ceilings so one slow route cannot grow process memory without bound.
MAX_RECENT_DURATIONS = 5
MAX_RECENT_REQUEST_IDS = 5
MAX_FINGERPRINTS_TRACKED = 1000

FINGERPRINT_MARKER_PREFIX = "performance-fingerprint:v1:"

VALID_SUBSYSTEM_LABELS = frozenset({"backend", "api", "frontend", "infrastructure"})
HIGH_PRIORITY_LABEL = "ralph-priority:high"

_LEGACY_WARMTH = ("warm", "cold")
_LEGACY_PHASES = ("unknown",)
_LEGACY_WORKLOADS = ("db-heavy", "app-heavy", "mixed")

_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*:\s*)(.+)"),
    re.compile(r"(?i)(bearer\s+)(\S+)"),
    re.compile(r"(?i)(cookie\s*:\s*)(.+)"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)(.+)"),
    re.compile(r"(?i)(access[_-]?token\s*[:=]\s*)(.+)"),
    re.compile(r"(?i)(refresh[_-]?token\s*[:=]\s*)(.+)"),
    re.compile(r"(?i)(password\s*[:=]\s*)(.+)"),
    re.compile(r"(?i)(secret\s*[:=]\s*)(.+)"),
)


def sanitize_evidence_text(value: str) -> str:
    """Redact credential-shaped content from issue evidence text.

    Args:
        value: Candidate evidence text for a GitHub issue body.

    Returns:
        Text with credential patterns replaced by ``[REDACTED]``.
    """
    redacted = value
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def fingerprint_marker(fingerprint: str) -> str:
    """Return the hidden HTML marker that binds an issue to a fingerprint.

    Args:
        fingerprint: Deterministic performance signature hash.

    Returns:
        HTML comment marker embedded in the issue body.
    """
    return f"<!-- {FINGERPRINT_MARKER_PREFIX}{fingerprint} -->"


def _hash_canonical(canonical: str) -> str:
    """Hash a canonical fingerprint string to a short stable identifier.

    Args:
        canonical: Human-readable canonical signature dimensions.

    Returns:
        16-character hex digest identifying the signature.
    """
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def classify_workload(duration_ms: float, db_time_ms: float, db_queries: int) -> str:
    """Classify a request as DB-heavy, application-heavy, or mixed.

    Args:
        duration_ms: Total observed request duration in milliseconds.
        db_time_ms: Total database execution time in milliseconds.
        db_queries: Number of SQL queries executed.

    Returns:
        One of ``"db-heavy"``, ``"app-heavy"``, or ``"mixed"``.
    """
    if duration_ms <= 0 or db_queries <= 0 or db_time_ms <= 0:
        return "app-heavy" if db_queries == 0 else "mixed"
    db_share = db_time_ms / duration_ms
    if db_share >= 0.5:
        return "db-heavy"
    if db_share <= 0.2:
        return "app-heavy"
    return "mixed"


def normalize_route_template(route: str) -> str:
    """Normalize a route template for fingerprint stability.

    Args:
        route: Route template such as ``/api/v1/threads/{thread_id}``.

    Returns:
        Normalized template with a leading slash and no trailing slash
        (except the root path).
    """
    normalized = (route or "__unmatched__").strip() or "__unmatched__"
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def fingerprint_for_request(
    *,
    method: str,
    route_template: str,
) -> tuple[str, str]:
    """Build the actionable fingerprint for a request performance event.

    The #3552 dedupe key is kind plus route identity (HTTP method and
    normalized route template). Warm/cold and subsystem/workload are
    sample evidence, not fingerprint dimensions.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template (not concrete IDs).

    Returns:
        Tuple of (fingerprint hash, canonical signature string).
    """
    route = normalize_route_template(route_template)
    canonical = f"request|{method.upper()}|{route}"
    return _hash_canonical(canonical), canonical


def legacy_request_fingerprints(*, method: str, route_template: str) -> tuple[str, ...]:
    """Return pre-#3552 fingerprint hashes for the same method and route.

    Production issues opened before this change used
    ``request|METHOD|route|warmth|phase|workload``. Middleware never passed
    ``dominant_phase``, so live markers used ``unknown``. Matching those
    hashes (and method-plus-route text) reuses today's open issues.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template.

    Returns:
        Unique legacy fingerprint hashes for this method and route.
    """
    route = normalize_route_template(route_template)
    hashes: list[str] = []
    seen: set[str] = set()
    for warmth in _LEGACY_WARMTH:
        for phase in _LEGACY_PHASES:
            for workload in _LEGACY_WORKLOADS:
                canonical = (
                    f"request|{method.upper()}|{route}|{warmth}|{phase}|{workload}"
                )
                digest = _hash_canonical(canonical)
                if digest not in seen:
                    seen.add(digest)
                    hashes.append(digest)
    return tuple(hashes)


def fingerprint_for_startup(*, operation: str) -> tuple[str, str]:
    """Build the actionable fingerprint for a startup performance event.

    Args:
        operation: Named startup phase/operation attribution
            (e.g. ``"startup.readiness"`` or ``"startup.neon_monitor"``).

    Returns:
        Tuple of (fingerprint hash, canonical signature string).
    """
    operation_name = (operation or "startup.readiness").strip() or "startup.readiness"
    canonical = f"startup|{operation_name}"
    return _hash_canonical(canonical), canonical


def fingerprint_for_coroutine(
    *,
    operation: str,
    exception_type: str | None = None,
) -> tuple[str, str]:
    """Build the actionable fingerprint for a coroutine hard timeout.

    Args:
        operation: Named readiness-critical operation that timed out.
        exception_type: Timeout/exception type name when known.

    Returns:
        Tuple of (fingerprint hash, canonical signature string).
    """
    operation_name = (operation or "unknown").strip() or "unknown"
    exc = (exception_type or "TimeoutError").strip() or "TimeoutError"
    canonical = f"coroutine|{operation_name}|{exc}"
    return _hash_canonical(canonical), canonical


@dataclass
class OccurrenceEvidence:
    """Aggregated occurrence evidence for one fingerprint."""

    fingerprint: str
    canonical: str
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    recent_durations_ms: list[float] = field(default_factory=list)
    recent_request_ids: list[str] = field(default_factory=list)
    latest_deployment_id: str | None = None
    max_duration_ms: float = 0.0


@dataclass
class FilingDecision:
    """Synchronous evaluation outcome for one telemetry event."""

    action: str
    fingerprint: str
    canonical: str
    high_priority: bool
    reason: str
    method: str | None = None
    route_template: str | None = None
    open_issue_number: int | None = None
    legacy_fingerprints: tuple[str, ...] = ()


class PerformanceIssueTracker:
    """Process-local occurrence evidence for the next GitHub comment.

    Daily breach counts and open-issue identity are not stored here.
    Production uses :class:`PostgresPerfAlarmStore`; tests share an
    :class:`InMemoryPerfAlarmStore`.
    """

    def __init__(self) -> None:
        """Initialize empty bounded tracking state."""
        self._lock = threading.Lock()
        self._occurrences: dict[str, OccurrenceEvidence] = {}

    def reset_for_tests(self) -> None:
        """Clear occurrence evidence. Intended for test isolation only."""
        with self._lock:
            self._occurrences.clear()

    def record_occurrence(
        self,
        *,
        fingerprint: str,
        canonical: str,
        duration_ms: float,
        request_id: str | None,
        deployment_id: str | None,
        now: float,
    ) -> OccurrenceEvidence:
        """Append occurrence evidence for a fingerprint.

        Args:
            fingerprint: Deterministic performance signature hash.
            canonical: Human-readable canonical signature.
            duration_ms: Observed duration in milliseconds.
            request_id: Request/invocation correlation id, when available.
            deployment_id: Deployment/commit identifier, when available.
            now: Current epoch timestamp in seconds.

        Returns:
            The updated occurrence evidence.
        """
        with self._lock:
            evidence = self._occurrences.get(fingerprint)
            if evidence is None:
                if len(self._occurrences) >= MAX_FINGERPRINTS_TRACKED:
                    oldest = min(
                        self._occurrences.values(), key=lambda e: e.first_seen
                    )
                    del self._occurrences[oldest.fingerprint]
                evidence = OccurrenceEvidence(
                    fingerprint=fingerprint,
                    canonical=canonical,
                    first_seen=now,
                )
                self._occurrences[fingerprint] = evidence
            evidence.count += 1
            evidence.last_seen = now
            evidence.recent_durations_ms.append(round(duration_ms, 2))
            del evidence.recent_durations_ms[:-MAX_RECENT_DURATIONS]
            if request_id:
                evidence.recent_request_ids.append(request_id)
                del evidence.recent_request_ids[:-MAX_RECENT_REQUEST_IDS]
            if deployment_id:
                evidence.latest_deployment_id = deployment_id
            evidence.max_duration_ms = max(evidence.max_duration_ms, duration_ms)
            return evidence

    def occurrence_for(self, fingerprint: str) -> OccurrenceEvidence | None:
        """Return aggregated occurrence evidence for a fingerprint, if any.

        Args:
            fingerprint: Deterministic performance signature hash.

        Returns:
            The occurrence evidence, or None when nothing was recorded.
        """
        with self._lock:
            return self._occurrences.get(fingerprint)


_tracker = PerformanceIssueTracker()
_test_store: InMemoryPerfAlarmStore | None = None
_background_tasks: set[asyncio.Task[None]] = set()


def _utc_day(now: float) -> date:
    """Return the UTC calendar day containing ``now``.

    Args:
        now: Epoch timestamp in seconds.

    Returns:
        UTC date of that timestamp.
    """
    return datetime.fromtimestamp(now, UTC).date()


def daily_breach_threshold() -> int:
    """Return the configured daily over-budget hit count required to file.

    Reads ``PERF_ALARM_DAILY_BREACH_THRESHOLD`` via AppSettings. The
    settings validator already rejects values outside 1-100.

    Returns:
        Positive integer threshold (default 3).
    """
    from app.config import get_app_settings

    return get_app_settings().perf_alarm_daily_breach_threshold


def github_issue_filing_enabled() -> bool:
    """Return whether production telemetry may automatically contact GitHub."""
    from app.config import get_app_settings

    return get_app_settings().perf_alarm_github_issues_enabled


def get_tracker() -> PerformanceIssueTracker:
    """Return the process-wide occurrence-evidence tracker.

    Returns:
        The shared tracker instance.
    """
    return _tracker


def get_test_store() -> InMemoryPerfAlarmStore:
    """Return the in-memory store installed by :func:`reset_for_tests`.

    Returns:
        The shared in-memory alarm store for the current test.

    Raises:
        RuntimeError: If called before :func:`reset_for_tests`.
    """
    if _test_store is None:
        raise RuntimeError("performance alarm test store is not initialized")
    return _test_store


def reset_for_tests(store: InMemoryPerfAlarmStore | None = None) -> None:
    """Install an in-memory alarm store and clear occurrence evidence.

    Args:
        store: Shared store for multi-evaluator tests. When omitted, a
            fresh in-memory store is created.
    """
    global _test_store
    _test_store = store if store is not None else InMemoryPerfAlarmStore()
    _tracker.reset_for_tests()


def _resolve_store(store: PerfAlarmStore | None) -> PerfAlarmStore:
    """Return the explicit store, else the test store.

    Args:
        store: Caller-provided durable store.

    Returns:
        The store to use for this evaluation.

    Raises:
        RuntimeError: If neither a store nor the test store is available.
    """
    if store is not None:
        return store
    if _test_store is not None:
        return _test_store
    raise RuntimeError("performance alarm store is required")


async def evaluate_request_event(
    *,
    method: str,
    route_template: str,
    duration_ms: float,
    cold: bool,
    now: float | None = None,
    store: PerfAlarmStore | None = None,
) -> FilingDecision | None:
    """Decide whether a request timing event should file or update an issue.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template.
        duration_ms: Observed duration in milliseconds.
        cold: Whether this was a cold-start request.
        now: Epoch timestamp override for tests.
        store: Durable counter/incident store. Tests omit this to use the
            in-memory store installed by :func:`reset_for_tests`.

    Returns:
        A filing decision when the event is actionable (file, update,
        accumulate, or ignore), otherwise None for healthy in-budget
        requests.
    """
    current = now if now is not None else time.time()
    fingerprint, canonical = fingerprint_for_request(
        method=method,
        route_template=route_template,
    )
    legacy = legacy_request_fingerprints(method=method, route_template=route_template)
    route = normalize_route_template(route_template)
    if cold:
        return FilingDecision(
            action="ignore",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=False,
            reason="cold-start samples do not count toward filing",
            method=method.upper(),
            route_template=route,
            legacy_fingerprints=legacy,
        )
    if duration_ms <= REQUEST_TIMEOUT_MS:
        if duration_ms >= REQUEST_WARNING_MS:
            return FilingDecision(
                action="accumulate",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=False,
                reason="warning recorded at or under route budget; never files",
                method=method.upper(),
                route_template=route,
                legacy_fingerprints=legacy,
            )
        return None
    alarm_store = _resolve_store(store)
    open_issue = await alarm_store.get_open_issue(fingerprint)
    if open_issue is not None:
        return FilingDecision(
            action="update",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=True,
            reason="repeat over-budget hit for known open fingerprint",
            method=method.upper(),
            route_template=route,
            open_issue_number=open_issue,
            legacy_fingerprints=legacy,
        )
    threshold = daily_breach_threshold()
    hit_count = await alarm_store.increment_daily_hit(fingerprint, _utc_day(current))
    if hit_count >= threshold:
        return FilingDecision(
            action="file",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=True,
            reason=(
                f"warm over-budget hits reached daily threshold ({threshold})"
            ),
            method=method.upper(),
            route_template=route,
            legacy_fingerprints=legacy,
        )
    return FilingDecision(
        action="accumulate",
        fingerprint=fingerprint,
        canonical=canonical,
        high_priority=False,
        reason="over-budget hit recorded below daily threshold",
        method=method.upper(),
        route_template=route,
        legacy_fingerprints=legacy,
    )


def evaluate_startup_event(
    *,
    duration_ms: float,
    operation: str = "startup.readiness",
    now: float | None = None,
) -> FilingDecision | None:
    """Decide whether a startup timing event should file or update an issue.

    Args:
        duration_ms: Measured ping-ready startup duration in milliseconds.
        operation: Named startup phase/operation attribution.
        now: Unused clock override retained for call-site compatibility.

    Returns:
        An ignore decision: startup readiness samples never file.
    """
    del now
    fingerprint, canonical = fingerprint_for_startup(operation=operation)
    return FilingDecision(
        action="ignore",
        fingerprint=fingerprint,
        canonical=canonical,
        high_priority=False,
        reason=(
            "startup readiness samples do not count toward filing "
            f"({duration_ms:.0f}ms)"
        ),
    )


async def evaluate_coroutine_timeout(
    *,
    operation: str,
    exception_type: str | None = None,
    store: PerfAlarmStore | None = None,
) -> FilingDecision:
    """Decide whether a readiness-critical coroutine timeout files an issue.

    Any readiness-critical coroutine hard timeout creates an issue
    immediately unless the exact same failure signature already has an
    open issue.

    Args:
        operation: Named operation that timed out.
        exception_type: Timeout/exception type name when known.
        store: Durable incident store. Tests omit this to use the
            in-memory store installed by :func:`reset_for_tests`.

    Returns:
        A filing decision (file or update).
    """
    fingerprint, canonical = fingerprint_for_coroutine(
        operation=operation, exception_type=exception_type
    )
    alarm_store = _resolve_store(store)
    open_issue = await alarm_store.get_open_issue(fingerprint)
    if open_issue is not None:
        return FilingDecision(
            action="update",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=True,
            reason="repeat coroutine timeout for known open fingerprint",
            open_issue_number=open_issue,
        )
    return FilingDecision(
        action="file",
        fingerprint=fingerprint,
        canonical=canonical,
        high_priority=True,
        reason="readiness-critical coroutine timeout files immediately",
    )


def build_labels(*, high_priority: bool, subsystem: str | None = None) -> list[str]:
    """Build executable factory intake labels for a performance issue.

    Args:
        high_priority: Whether the issue warrants high priority.
        subsystem: Optional subsystem classification (``backend``, ``api``,
            ``frontend``, or ``infrastructure``).

    Returns:
        Label list. Machine-generated issues never receive
        ``user-reported``.
    """
    labels = [
        "bug",
        "performance",
        "ralph-task",
        "ralph-status:pending",
        "factory",
        "factory:unowned",
    ]
    if subsystem in VALID_SUBSYSTEM_LABELS:
        labels.append(subsystem)
    if high_priority:
        labels.append(HIGH_PRIORITY_LABEL)
    return labels


def build_issue_title(
    *,
    kind: str,
    method: str | None = None,
    route_template: str | None = None,
    operation: str | None = None,
    duration_ms: float = 0.0,
) -> str:
    """Build a focused human-readable title for a performance issue.

    Args:
        kind: One of ``"request"``, ``"startup"``, or ``"coroutine"``.
        method: HTTP method for request incidents.
        route_template: Normalized route for request incidents.
        operation: Operation attribution for startup/coroutine incidents.
        duration_ms: Observed duration in milliseconds.

    Returns:
        Issue title string.
    """
    if kind == "startup":
        operation_name = operation or "startup.readiness"
        display_ms = max(duration_ms, float(STARTUP_TIMEOUT_MS))
        return (
            f"Performance: startup {operation_name} "
            f"took {display_ms:.0f}ms (budget {STARTUP_TIMEOUT_MS}ms)"
        )
    if kind == "coroutine":
        operation_name = operation or "unknown"
        return f"Performance: coroutine timeout in {operation_name}"
    route = normalize_route_template(route_template or "__unmatched__")
    display_ms = (
        duration_ms if duration_ms > REQUEST_TIMEOUT_MS else float(REQUEST_TIMEOUT_MS)
    )
    return (
        f"Performance: {(method or 'GET').upper()} {route} "
        f"took {display_ms:.0f}ms (budget {REQUEST_TIMEOUT_MS}ms)"
    )


def build_issue_body(
    *,
    kind: str,
    fingerprint: str,
    canonical: str,
    method: str | None = None,
    route_template: str | None = None,
    duration_ms: float = 0.0,
    threshold_ms: float = 0.0,
    event_label: str,
    cold: bool = False,
    db_queries: int = 0,
    db_time_ms: float = 0.0,
    app_time_ms: float | None = None,
    phases: str | None = None,
    request_ids: list[str] | None = None,
    deployment_id: str | None = None,
    first_seen: str | None = None,
    last_seen: str | None = None,
    occurrence_count: int = 1,
    server_timing: str | None = None,
    operation: str | None = None,
    likely_subsystem: str | None = None,
    prior_issue: int | None = None,
) -> str:
    """Build the evidence-rich body for an auto-filed performance issue.

    The body contains timings, DB diagnostics, deployment/request evidence,
    and thresholds without leaking secrets. The likely subsystem is a
    telemetry-based hint, never a claimed root cause.

    Args:
        kind: One of ``"request"``, ``"startup"``, or ``"coroutine"``.
        fingerprint: Deterministic performance signature hash.
        canonical: Human-readable canonical signature.
        method: HTTP method for request incidents.
        route_template: Normalized route for request incidents.
        duration_ms: Observed duration in milliseconds.
        threshold_ms: Violated threshold in milliseconds.
        event_label: One of ``warning``, ``violation``, ``startup failure``,
            or ``coroutine timeout``.
        cold: Warm/cold classification for request incidents.
        db_queries: SQL query count.
        db_time_ms: Database execution time in milliseconds.
        app_time_ms: Application-side time in milliseconds, when known.
        phases: Known timing phases, when available.
        request_ids: Representative request/invocation ids.
        deployment_id: Deployment/commit identifier, when available.
        first_seen: First-seen timestamp ISO string, when aggregated.
        last_seen: Last-seen timestamp ISO string, when aggregated.
        occurrence_count: Aggregated occurrence count.
        server_timing: Representative Server-Timing header value.
        operation: Phase/operation attribution for startup/coroutine events.
        likely_subsystem: Telemetry-based subsystem hint, when classifiable.
        prior_issue: Prior closed issue number for regression incidents.

    Returns:
        Markdown issue body with a hidden fingerprint marker.
    """
    lines = [
        "## Production performance incident (auto-filed)",
        "",
        f"- Event: {sanitize_evidence_text(event_label)}",
        f"- Fingerprint: `{sanitize_evidence_text(fingerprint)}`",
        f"- Signature: `{sanitize_evidence_text(canonical)}`",
        f"- Observed duration: {duration_ms:.2f} ms",
        f"- Threshold violated: {threshold_ms:.0f} ms",
    ]
    if kind == "request":
        route = normalize_route_template(route_template or "__unmatched__")
        lines.append(f"- Method + route: {(method or 'GET').upper()} {route}")
        lines.append(f"- Warm/cold: {'cold' if cold else 'warm'}")
        lines.append(f"- DB queries: {db_queries}")
        lines.append(f"- DB time: {db_time_ms:.2f} ms")
        if app_time_ms is not None:
            lines.append(f"- Application time: {app_time_ms:.2f} ms")
    if operation:
        lines.append(f"- Operation: {sanitize_evidence_text(operation)}")
    if phases:
        lines.append(f"- Timing phases: {sanitize_evidence_text(phases)}")
    if server_timing:
        lines.append(f"- Server-Timing: {sanitize_evidence_text(server_timing)}")
    if request_ids:
        safe_ids = [sanitize_evidence_text(r) for r in request_ids[:MAX_RECENT_REQUEST_IDS]]
        lines.append(f"- Request ids: {', '.join(safe_ids)}")
    if deployment_id:
        lines.append(f"- Deployment/commit: {sanitize_evidence_text(deployment_id)}")
    if first_seen or last_seen or occurrence_count > 1:
        lines.append(f"- Occurrences: {occurrence_count}")
        if first_seen:
            lines.append(f"- First seen: {sanitize_evidence_text(first_seen)}")
        if last_seen:
            lines.append(f"- Last seen: {sanitize_evidence_text(last_seen)}")
    if likely_subsystem:
        lines.append(
            "- Likely subsystem (telemetry hint, not a proven root cause): "
            f"{sanitize_evidence_text(likely_subsystem)}"
        )
    if prior_issue is not None:
        lines.append(
            f"- Regression: this signature previously closed in #{prior_issue}; "
            f"opened as a new regression issue referencing #{prior_issue}."
        )
    lines += [
        "",
        "Factory note: investigate with request diagnostics and Server-Timing "
        "instrumentation; do not raise global thresholds to accommodate the route.",
        "",
        fingerprint_marker(fingerprint),
    ]
    return "\n".join(lines)


def build_occurrence_comment(
    *,
    duration_ms: float,
    cold: bool,
    db_queries: int = 0,
    db_time_ms: float = 0.0,
    request_id: str | None = None,
    deployment_id: str | None = None,
    occurrence_count: int = 1,
    reason: str | None = None,
) -> str:
    """Build a recurrence comment with the new sample's evidence.

    Args:
        duration_ms: Observed duration in milliseconds.
        cold: Warm/cold classification for the sample.
        db_queries: SQL query count.
        db_time_ms: Database execution time in milliseconds.
        request_id: Request correlation id, when available.
        deployment_id: Deployment/commit identifier, when available.
        occurrence_count: Aggregated occurrence count after this sample.
        reason: Policy reason for the update.

    Returns:
        Markdown comment body with redacted evidence.
    """
    lines = [
        "Performance incident recurred.",
        f"- Duration: {duration_ms:.2f} ms",
        f"- Warm/cold: {'cold' if cold else 'warm'}",
        f"- DB queries: {db_queries}",
        f"- DB time: {db_time_ms:.2f} ms",
        f"- Occurrence count: {occurrence_count}",
    ]
    if request_id:
        lines.append(f"- Request id: {sanitize_evidence_text(request_id)}")
    if deployment_id:
        lines.append(f"- Deployment/commit: {sanitize_evidence_text(deployment_id)}")
    if reason:
        lines.append(f"- Reason: {sanitize_evidence_text(reason)}")
    return "\n".join(lines)


async def _comment_if_throttled(
    *,
    store: PerfAlarmStore,
    fingerprint: str,
    issue_number: int,
    comment: str,
) -> str | None:
    """Comment on an open issue at most once per fingerprint per hour.

    Args:
        store: Durable incident store.
        fingerprint: Deterministic performance signature hash.
        issue_number: GitHub issue number to comment on.
        comment: Recurrence comment body.

    Returns:
        GitHub issue state after the attempt, or None when throttled or
        GitHub is unavailable.
    """
    if not github_issue_filing_enabled():
        return None

    from app.services import github_service as gh

    if not await store.try_claim_comment(fingerprint):
        await store.commit()
        return "open"
    await store.commit()
    try:
        return await gh.add_performance_issue_comment(issue_number, comment)
    except RuntimeError as exc:
        logger.warning(
            "Performance occurrence update failed for #%s: %s", issue_number, exc
        )
        return None


async def _file_new_issue(
    *,
    store: PerfAlarmStore,
    decision: FilingDecision,
    title: str,
    body: str,
    labels: list[str],
) -> None:
    """Create a GitHub issue after winning the durable filing claim.

    Args:
        store: Durable incident store.
        decision: Filing decision for the event.
        title: Issue title for the new issue.
        body: Issue body with evidence and fingerprint marker.
        labels: Factory intake labels.
    """
    if not github_issue_filing_enabled():
        return

    from app.services import github_service as gh

    if not await store.try_claim_filing(decision.fingerprint):
        await store.commit()
        existing = await store.get_open_issue(decision.fingerprint)
        if existing is not None:
            return
        try:
            opened = await gh.find_open_issue_by_fingerprint(
                decision.fingerprint,
                extra_fingerprints=decision.legacy_fingerprints,
                method=decision.method,
                route_template=decision.route_template,
            )
        except RuntimeError as exc:
            logger.warning("Performance issue lookup failed: %s", exc)
            return
        if opened is not None:
            await store.mark_open(decision.fingerprint, opened)
            await store.commit()
        return
    await store.commit()
    prior = await store.get_closed_issue(decision.fingerprint)
    if prior is None:
        try:
            prior = await gh.find_closed_issue_by_fingerprint(
                decision.fingerprint,
                extra_fingerprints=decision.legacy_fingerprints,
                method=decision.method,
                route_template=decision.route_template,
            )
        except RuntimeError as exc:
            logger.warning("Performance regression lookup failed: %s", exc)
            prior = None
    filing_body = body
    if prior is not None and f"#{prior}" not in filing_body:
        filing_body = (
            f"{filing_body}\n- Regression: this signature previously "
            f"closed in #{prior}; opened as a new regression issue "
            f"referencing #{prior}."
        )
    try:
        url = await gh.create_performance_issue(
            title=title, body=filing_body, labels=labels
        )
    except RuntimeError as exc:
        logger.warning("Performance issue filing failed: %s", exc)
        await store.clear_filing_claim(decision.fingerprint)
        await store.commit()
        return
    issue_number = _issue_number_from_url(url)
    if issue_number is not None:
        await store.mark_open(decision.fingerprint, issue_number)
        await store.commit()


async def _file_decision_background(
    *,
    decision: FilingDecision,
    title: str,
    body: str,
    labels: list[str],
    comment: str | None = None,
    store: PerfAlarmStore | None = None,
) -> None:
    """File or update a GitHub issue in bounded background work.

    Failure is logged and observable but never propagates to the caller:
    a GitHub outage must not turn a successful user request into a 5xx.

    Args:
        decision: Filing decision for the event.
        title: Issue title for new issues.
        body: Issue body with evidence and fingerprint marker.
        labels: Factory intake labels.
        comment: Occurrence comment used when updating an open issue.
        store: Durable store. Tests omit this to use the in-memory store.
    """
    if not github_issue_filing_enabled():
        return

    try:
        from app.services import github_service as gh
    except ImportError as exc:
        logger.warning("Performance issue filing skipped: GitHub client unavailable: %s", exc)
        return
    try:
        alarm_store = _resolve_store(store)
        recurrence = comment or f"Performance incident recurred ({decision.reason})."
        if decision.action == "update":
            known = decision.open_issue_number
            if known is None:
                known = await alarm_store.get_open_issue(decision.fingerprint)
            if known is not None:
                try:
                    state = await gh.get_performance_issue_state(known)
                except RuntimeError as exc:
                    logger.warning(
                        "Performance issue state lookup failed for #%s: %s",
                        known,
                        exc,
                    )
                    state = None
                if state == "open":
                    await _comment_if_throttled(
                        store=alarm_store,
                        fingerprint=decision.fingerprint,
                        issue_number=known,
                        comment=recurrence,
                    )
                    return
                if state == "closed":
                    await alarm_store.mark_closed(decision.fingerprint, known)
                    await alarm_store.commit()
                    hit_count = await alarm_store.increment_daily_hit(
                        decision.fingerprint,
                        _utc_day(time.time()),
                    )
                    await alarm_store.commit()
                    if hit_count < daily_breach_threshold():
                        return
                    decision = FilingDecision(
                        action="file",
                        fingerprint=decision.fingerprint,
                        canonical=decision.canonical,
                        high_priority=True,
                        reason=(
                            "warm over-budget hits reached daily threshold "
                            f"({daily_breach_threshold()}) after close"
                        ),
                        method=decision.method,
                        route_template=decision.route_template,
                        legacy_fingerprints=decision.legacy_fingerprints,
                    )
                else:
                    return
        existing = None
        try:
            existing = await gh.find_open_issue_by_fingerprint(
                decision.fingerprint,
                extra_fingerprints=decision.legacy_fingerprints,
                method=decision.method,
                route_template=decision.route_template,
            )
        except RuntimeError as exc:
            logger.warning("Performance issue lookup failed: %s", exc)
        if existing is not None:
            await alarm_store.mark_open(decision.fingerprint, existing)
            await alarm_store.commit()
            await _comment_if_throttled(
                store=alarm_store,
                fingerprint=decision.fingerprint,
                issue_number=existing,
                comment=recurrence,
            )
            return
        await _file_new_issue(
            store=alarm_store,
            decision=decision,
            title=title,
            body=body,
            labels=labels,
        )
    except Exception as exc:
        logger.warning("Performance issue background filing failed: %s", exc)


def _issue_number_from_url(url: str) -> int | None:
    """Extract a GitHub issue number from an issue URL.

    Args:
        url: HTML URL of the created issue.

    Returns:
        The trailing issue number, or None when unparseable.
    """
    try:
        return int(url.rstrip("/").rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return None


def _spawn_background(coro: Coroutine[object, object, None]) -> None:
    """Keep a background task referenced until it finishes.

    Args:
        coro: Background coroutine to schedule on the running loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Performance issue filing skipped: no running event loop")
        coro.close()
        return
    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def drain_background_tasks() -> None:
    """Await in-flight alarm tasks. Intended for tests."""
    while _background_tasks:
        pending = list(_background_tasks)
        await asyncio.gather(*pending, return_exceptions=True)


def schedule_filing(
    *,
    decision: FilingDecision,
    title: str,
    body: str,
    labels: list[str],
    comment: str | None = None,
    store: PerfAlarmStore | None = None,
) -> None:
    """Schedule non-blocking background filing for a filing decision.

    Must never delay or fail the production request that triggered the
    telemetry. When no running event loop is available, the filing is
    logged and dropped rather than raising.

    Args:
        decision: Filing decision for the event.
        title: Issue title for new issues.
        body: Issue body with evidence and fingerprint marker.
        labels: Factory intake labels.
        comment: Occurrence comment used when updating an open issue.
        store: Durable store captured by the background task.
    """
    if not github_issue_filing_enabled() or decision.action in {"accumulate", "ignore"}:
        return
    _spawn_background(
        _file_decision_background(
            decision=decision,
            title=title,
            body=body,
            labels=labels,
            comment=comment,
            store=store,
        )
    )


async def _open_production_store() -> tuple[PerfAlarmStore, AsyncSession | None]:
    """Bind a durable store for a background alarm evaluation.

    Returns:
        Tuple of (store, session-to-close). The session is None when the
        in-memory test store is installed.
    """
    if _test_store is not None:
        return _test_store, None
    from app.database import AsyncSessionLocal

    db = AsyncSessionLocal()
    return PostgresPerfAlarmStore(db), db


async def _handle_request_background(
    *,
    method: str,
    route_template: str,
    duration_ms: float,
    cold: bool,
    dominant_phase: str | None,
    db_queries: int,
    db_time_ms: float,
    request_id: str | None,
    deployment_id: str | None,
    server_timing: str | None,
) -> None:
    """Evaluate one over-budget request against durable state, then file.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template.
        duration_ms: Observed duration in milliseconds.
        cold: Whether this was a cold-start request.
        dominant_phase: Dominant timing phase when known.
        db_queries: SQL query count.
        db_time_ms: Database execution time in milliseconds.
        request_id: Request correlation id.
        deployment_id: Deployment/commit identifier.
        server_timing: Representative Server-Timing header value.
    """
    if not github_issue_filing_enabled():
        return

    db: AsyncSession | None = None
    try:
        store, db = await _open_production_store()
        decision = await evaluate_request_event(
            method=method,
            route_template=route_template,
            duration_ms=duration_ms,
            cold=cold,
            store=store,
        )
        await store.commit()
        if decision is None or decision.action in {"accumulate", "ignore"}:
            return
        _tracker.record_occurrence(
            fingerprint=decision.fingerprint,
            canonical=decision.canonical,
            duration_ms=duration_ms,
            request_id=request_id,
            deployment_id=deployment_id,
            now=time.time(),
        )
        occurrence = _tracker.occurrence_for(decision.fingerprint)
        first_seen = (
            datetime.fromtimestamp(occurrence.first_seen, UTC).isoformat()
            if occurrence is not None
            else None
        )
        last_seen = (
            datetime.fromtimestamp(occurrence.last_seen, UTC).isoformat()
            if occurrence is not None
            else None
        )
        occurrence_count = occurrence.count if occurrence is not None else 1
        title_duration = (
            occurrence.max_duration_ms if occurrence is not None else duration_ms
        )
        app_time = max(duration_ms - db_time_ms, 0.0)
        workload = classify_workload(duration_ms, db_time_ms, db_queries)
        likely = "database" if workload == "db-heavy" else None
        prior = await store.get_closed_issue(decision.fingerprint)
        comment = build_occurrence_comment(
            duration_ms=duration_ms,
            cold=cold,
            db_queries=db_queries,
            db_time_ms=db_time_ms,
            request_id=request_id,
            deployment_id=deployment_id,
            occurrence_count=occurrence_count,
            reason=decision.reason,
        )
        title = build_issue_title(
            kind="request",
            method=method,
            route_template=route_template,
            duration_ms=title_duration,
        )
        body = build_issue_body(
            kind="request",
            fingerprint=decision.fingerprint,
            canonical=decision.canonical,
            method=method,
            route_template=route_template,
            duration_ms=title_duration,
            threshold_ms=float(REQUEST_TIMEOUT_MS),
            event_label="violation",
            cold=cold,
            db_queries=db_queries,
            db_time_ms=db_time_ms,
            app_time_ms=app_time,
            phases=dominant_phase,
            request_ids=[request_id] if request_id else None,
            deployment_id=deployment_id,
            first_seen=first_seen,
            last_seen=last_seen,
            occurrence_count=occurrence_count,
            server_timing=server_timing,
            likely_subsystem=likely,
            prior_issue=prior,
        )
        await _file_decision_background(
            decision=decision,
            title=title,
            body=body,
            labels=build_labels(
                high_priority=decision.high_priority, subsystem="backend"
            ),
            comment=comment,
            store=store,
        )
    except Exception as exc:
        logger.warning("Performance issue background evaluation failed: %s", exc)
    finally:
        if db is not None:
            await db.close()


def handle_request_telemetry(
    *,
    method: str,
    route_template: str,
    duration_ms: float,
    cold: bool,
    dominant_phase: str | None = None,
    db_queries: int = 0,
    db_time_ms: float = 0.0,
    request_id: str | None = None,
    deployment_id: str | None = None,
    server_timing: str | None = None,
) -> None:
    """Evaluate request telemetry and schedule filing without blocking.

    Cold-start and under-budget samples return immediately without
    touching durable storage. Over-budget warm samples are evaluated in
    a background task against the shared Postgres counter.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template.
        duration_ms: Observed duration in milliseconds.
        cold: Whether this was a cold-start request.
        dominant_phase: Dominant timing phase when known.
        db_queries: SQL query count.
        db_time_ms: Database execution time in milliseconds.
        request_id: Request correlation id.
        deployment_id: Deployment/commit identifier.
        server_timing: Representative Server-Timing header value.
    """
    if cold:
        logger.info(
            "Performance alarm ignored cold-start sample: %s %s took %.2f ms",
            method.upper(),
            normalize_route_template(route_template),
            duration_ms,
            extra={
                "event": "performance_alarm_ignored_cold_start",
                "method": method.upper(),
                "route_template": normalize_route_template(route_template),
                "duration_ms": duration_ms,
                "request_id": request_id,
                "deployment_id": deployment_id,
            },
        )
        return
    if not github_issue_filing_enabled() or duration_ms <= REQUEST_TIMEOUT_MS:
        return
    _spawn_background(
        _handle_request_background(
            method=method,
            route_template=route_template,
            duration_ms=duration_ms,
            cold=cold,
            dominant_phase=dominant_phase,
            db_queries=db_queries,
            db_time_ms=db_time_ms,
            request_id=request_id,
            deployment_id=deployment_id,
            server_timing=server_timing,
        )
    )


def handle_startup_telemetry(
    *,
    duration_ms: float,
    operation: str = "startup.readiness",
    deployment_id: str | None = None,
) -> None:
    """Evaluate startup telemetry without filing a GitHub issue.

    Startup readiness samples never file. Hard failures at or above
    ``STARTUP_TIMEOUT_MS`` (2.5s) log at WARNING because issues #3479
    and #3480 do not consume ``performance_alarm_ignored_startup``.

    Args:
        duration_ms: Measured ping-ready startup duration in milliseconds.
        operation: Named startup phase/operation attribution.
        deployment_id: Deployment/commit identifier.
    """
    evaluate_startup_event(duration_ms=duration_ms, operation=operation)
    hard_failure = duration_ms >= STARTUP_TIMEOUT_MS
    log = logger.warning if hard_failure else logger.info
    log(
        "Performance alarm ignored startup sample: %s took %.2f ms",
        operation,
        duration_ms,
        extra={
            "event": "performance_alarm_ignored_startup",
            "operation": operation,
            "duration_ms": duration_ms,
            "deployment_id": deployment_id,
            "startup_performance_violation": hard_failure,
        },
    )


async def _handle_coroutine_background(
    *,
    operation: str,
    elapsed_ms: float,
    deadline_ms: float,
    exception_type: str | None,
    deployment_id: str | None,
) -> None:
    """Evaluate a coroutine timeout against durable state, then file.

    Args:
        operation: Named operation that timed out.
        elapsed_ms: Measured elapsed time in milliseconds.
        deadline_ms: Configured hard deadline in milliseconds.
        exception_type: Timeout/exception type name when known.
        deployment_id: Deployment/commit identifier.
    """
    if not github_issue_filing_enabled():
        return

    db: AsyncSession | None = None
    try:
        store, db = await _open_production_store()
        decision = await evaluate_coroutine_timeout(
            operation=operation,
            exception_type=exception_type,
            store=store,
        )
        await store.commit()
        if decision.action in {"accumulate", "ignore"}:
            return
        prior = await store.get_closed_issue(decision.fingerprint)
        title = build_issue_title(kind="coroutine", operation=operation)
        body = build_issue_body(
            kind="coroutine",
            fingerprint=decision.fingerprint,
            canonical=decision.canonical,
            duration_ms=elapsed_ms,
            threshold_ms=deadline_ms,
            event_label="coroutine timeout",
            deployment_id=deployment_id,
            occurrence_count=1,
            operation=operation,
            likely_subsystem="infrastructure",
            prior_issue=prior,
        )
        await _file_decision_background(
            decision=decision,
            title=title,
            body=body,
            labels=build_labels(high_priority=True, subsystem="infrastructure"),
            store=store,
        )
    except Exception as exc:
        logger.warning("Coroutine timeout background evaluation failed: %s", exc)
    finally:
        if db is not None:
            await db.close()


def handle_coroutine_timeout(
    *,
    operation: str,
    elapsed_ms: float,
    deadline_ms: float,
    exception_type: str | None = None,
    deployment_id: str | None = None,
) -> None:
    """Evaluate a readiness-critical coroutine timeout and schedule filing.

    Args:
        operation: Named operation that timed out.
        elapsed_ms: Measured elapsed time in milliseconds.
        deadline_ms: Configured hard deadline in milliseconds.
        exception_type: Timeout/exception type name when known.
        deployment_id: Deployment/commit identifier.
    """
    if not github_issue_filing_enabled():
        return

    _spawn_background(
        _handle_coroutine_background(
            operation=operation,
            elapsed_ms=elapsed_ms,
            deadline_ms=deadline_ms,
            exception_type=exception_type,
            deployment_id=deployment_id,
        )
    )
