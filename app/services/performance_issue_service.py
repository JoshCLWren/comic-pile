"""Automatic GitHub issue filing for production performance violations.

Implements issue #3245: production performance telemetry becomes factory work
automatically. The unit of issue creation is a distinct actionable performance
signature (fingerprint), not a raw request event.

Policy implemented here (thresholds frozen by the issue contract):

- Warm request 500-999 ms: file when the same normalized route records 3
  warnings within 10 minutes or 5 warnings within 1 hour.
- Warm request >= 1000 ms: file immediately unless the same fingerprint
  already has an open issue.
- Startup >= 2.0 s but < 2.5 s: file when it happens twice within 1 hour.
- Startup >= 2.5 s: file immediately with phase/operation attribution.
- Readiness-critical coroutine hard timeout: file immediately unless the same
  signature already has an open issue.

Deduplication is by deterministic fingerprint built from the dimensions that
describe the likely independent defect (normalized route template, warm vs
cold, performance class, dominant phase/operation, DB-heavy vs app-heavy,
timeout/exception type). Deployment/commit is evidence only, never the
primary dedupe key.

Issue creation never blocks the user request: callers use the ``handle_*``
entry points, which evaluate synchronously and dispatch bounded background
work. GitHub API failure is logged and observable but never fails the
original request.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.performance_budgets import (
    REQUEST_TIMEOUT_MS,
    REQUEST_WARNING_MS,
    STARTUP_TIMEOUT_MS,
    STARTUP_WARNING_MS,
)

logger = logging.getLogger(__name__)

# Warning accumulation windows (issue #3245 contract).
WARNING_BURST_COUNT = 3
WARNING_BURST_WINDOW_S = 10 * 60
WARNING_SUSTAINED_COUNT = 5
WARNING_SUSTAINED_WINDOW_S = 60 * 60

# Startup warning aggregation: twice within 1 hour files an issue.
STARTUP_WARNING_COUNT = 2
STARTUP_WARNING_WINDOW_S = 60 * 60

# Retention ceilings so one slow route cannot grow process memory without bound.
MAX_WARNING_ROUTES = 500
MAX_RECENT_DURATIONS = 5
MAX_RECENT_REQUEST_IDS = 5
MAX_FINGERPRINTS_TRACKED = 1000

FINGERPRINT_MARKER_PREFIX = "performance-fingerprint:v1:"

VALID_SUBSYSTEM_LABELS = frozenset({"backend", "api", "frontend", "infrastructure"})
HIGH_PRIORITY_LABEL = "ralph-priority:high"

_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*:\s*)(.+)"),
    re.compile(r"(?i)(bearer\s+)(.+?)\b"),
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
    cold: bool,
    dominant_phase: str | None = None,
    db_time_ms: float = 0.0,
    duration_ms: float = 0.0,
    db_queries: int = 0,
) -> tuple[str, str]:
    """Build the actionable fingerprint for a warm/cold request violation.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template (not concrete IDs).
        cold: Whether this was a cold-start request.
        dominant_phase: Dominant timing phase/operation when known
            (e.g. ``"sql-aggregation"`` vs ``"serialization"``). Distinct
            phases on the same route produce distinct fingerprints because
            they plausibly require independent fixes.
        db_time_ms: Database execution time in milliseconds.
        duration_ms: Total request duration in milliseconds.
        db_queries: SQL query count for workload classification.

    Returns:
        Tuple of (fingerprint hash, canonical signature string).
    """
    route = normalize_route_template(route_template)
    warmth = "cold" if cold else "warm"
    phase = (dominant_phase or "unknown").strip().lower() or "unknown"
    workload = classify_workload(duration_ms, db_time_ms, db_queries)
    canonical = (
        f"request|{method.upper()}|{route}|{warmth}|{phase}|{workload}"
    )
    return _hash_canonical(canonical), canonical


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


class PerformanceIssueTracker:
    """Process-local accumulator for performance-to-issue policy decisions.

    Tracks warning timestamps per normalized route, startup warning
    timestamps, known open fingerprints (dedupe), known closed fingerprints
    (regression detection), and per-fingerprint occurrence evidence.
    """

    def __init__(self) -> None:
        """Initialize empty bounded tracking state."""
        self._lock = threading.Lock()
        self._warning_hits: dict[str, deque[float]] = {}
        self._startup_warnings: deque[float] = deque()
        self._open_fingerprints: dict[str, int] = {}
        self._closed_fingerprints: dict[str, int] = {}
        self._occurrences: dict[str, OccurrenceEvidence] = {}

    def reset_for_tests(self) -> None:
        """Clear all tracking state. Intended for test isolation only."""
        with self._lock:
            self._warning_hits.clear()
            self._startup_warnings.clear()
            self._open_fingerprints.clear()
            self._closed_fingerprints.clear()
            self._occurrences.clear()

    def mark_open(self, fingerprint: str, issue_number: int) -> None:
        """Record that a fingerprint already has an open issue.

        Args:
            fingerprint: Deterministic performance signature hash.
            issue_number: GitHub issue number holding the open incident.
        """
        with self._lock:
            self._open_fingerprints[fingerprint] = issue_number
            self._closed_fingerprints.pop(fingerprint, None)

    def mark_closed(self, fingerprint: str, issue_number: int) -> None:
        """Record that a fingerprint's issue was closed (fix deployed).

        Args:
            fingerprint: Deterministic performance signature hash.
            issue_number: GitHub issue number that was closed.
        """
        with self._lock:
            self._closed_fingerprints[fingerprint] = issue_number
            self._open_fingerprints.pop(fingerprint, None)

    def record_filed(self, fingerprint: str, issue_number: int) -> None:
        """Record a newly filed issue as the open incident for a fingerprint.

        Args:
            fingerprint: Deterministic performance signature hash.
            issue_number: GitHub issue number of the newly filed incident.
        """
        with self._lock:
            self._open_fingerprints[fingerprint] = issue_number
            self._closed_fingerprints.pop(fingerprint, None)

    def open_issue_for(self, fingerprint: str) -> int | None:
        """Return the known open issue number for a fingerprint, if any.

        Args:
            fingerprint: Deterministic performance signature hash.

        Returns:
            The open issue number, or None when no open issue is known.
        """
        with self._lock:
            return self._open_fingerprints.get(fingerprint)

    def closed_issue_for(self, fingerprint: str) -> int | None:
        """Return the prior closed issue number for a fingerprint, if any.

        Args:
            fingerprint: Deterministic performance signature hash.

        Returns:
            The prior closed issue number, or None.
        """
        with self._lock:
            return self._closed_fingerprints.get(fingerprint)

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

    def evaluate_warning_hit(self, *, route_key: str, now: float) -> bool:
        """Record a 500-999 ms warning and decide whether it files an issue.

        Files when the same normalized route records 3 warnings within
        10 minutes or 5 warnings within 1 hour.

        Args:
            route_key: Normalized ``METHOD route-template`` key.
            now: Current epoch timestamp in seconds.

        Returns:
            True when the accumulation threshold is crossed.
        """
        with self._lock:
            hits = self._warning_hits.get(route_key)
            if hits is None:
                if len(self._warning_hits) >= MAX_WARNING_ROUTES:
                    oldest_key = min(
                        self._warning_hits,
                        key=lambda k: self._warning_hits[k][-1]
                        if self._warning_hits[k]
                        else 0.0,
                    )
                    del self._warning_hits[oldest_key]
                hits = deque()
                self._warning_hits[route_key] = hits
            hits.append(now)
            while hits and hits[0] < now - WARNING_SUSTAINED_WINDOW_S:
                hits.popleft()
            burst = sum(1 for ts in hits if ts >= now - WARNING_BURST_WINDOW_S)
            sustained = len(hits)
            return burst >= WARNING_BURST_COUNT or sustained >= WARNING_SUSTAINED_COUNT

    def evaluate_startup_warning(self, *, now: float) -> bool:
        """Record a 2.0-2.5 s startup warning and decide whether to file.

        Files when startup warnings happen twice within 1 hour.

        Args:
            now: Current epoch timestamp in seconds.

        Returns:
            True when the aggregation threshold is crossed.
        """
        with self._lock:
            self._startup_warnings.append(now)
            while (
                self._startup_warnings
                and self._startup_warnings[0] < now - STARTUP_WARNING_WINDOW_S
            ):
                self._startup_warnings.popleft()
            return len(self._startup_warnings) >= STARTUP_WARNING_COUNT


_tracker = PerformanceIssueTracker()


def get_tracker() -> PerformanceIssueTracker:
    """Return the process-wide performance issue tracker.

    Returns:
        The shared tracker instance.
    """
    return _tracker


def reset_for_tests() -> None:
    """Clear process-local performance issue state for test isolation."""
    _tracker.reset_for_tests()


def evaluate_request_event(
    *,
    method: str,
    route_template: str,
    duration_ms: float,
    cold: bool,
    dominant_phase: str | None = None,
    db_time_ms: float = 0.0,
    db_queries: int = 0,
    now: float | None = None,
) -> FilingDecision | None:
    """Decide whether a request timing event should file or update an issue.

    Args:
        method: HTTP method of the request.
        route_template: Normalized route template.
        duration_ms: Observed duration in milliseconds.
        cold: Whether this was a cold-start request.
        dominant_phase: Dominant timing phase when known.
        db_time_ms: Database execution time in milliseconds.
        db_queries: SQL query count.
        now: Epoch timestamp override for tests.

    Returns:
        A filing decision when the event crosses the policy threshold
        (immediate violation, accumulated warnings, or occurrence update
        for a known open fingerprint), otherwise None.
    """
    current = now if now is not None else time.time()
    fingerprint, canonical = fingerprint_for_request(
        method=method,
        route_template=route_template,
        cold=cold,
        dominant_phase=dominant_phase,
        db_time_ms=db_time_ms,
        duration_ms=duration_ms,
        db_queries=db_queries,
    )
    if duration_ms >= REQUEST_TIMEOUT_MS:
        if _tracker.open_issue_for(fingerprint) is not None:
            return FilingDecision(
                action="update",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=True,
                reason="repeat violation for known open fingerprint",
            )
        return FilingDecision(
            action="file",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=True,
            reason="warm violation >=1000ms files immediately",
        )
    if duration_ms >= REQUEST_WARNING_MS:
        route_key = f"{method.upper()} {normalize_route_template(route_template)}"
        if _tracker.open_issue_for(fingerprint) is not None:
            return FilingDecision(
                action="update",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=False,
                reason="repeat warning for known open fingerprint",
            )
        if _tracker.evaluate_warning_hit(route_key=route_key, now=current):
            return FilingDecision(
                action="file",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=False,
                reason="warning accumulation threshold crossed",
            )
        return FilingDecision(
            action="accumulate",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=False,
            reason="warning recorded below filing threshold",
        )
    return None


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
        now: Epoch timestamp override for tests.

    Returns:
        A filing decision when the policy threshold is crossed,
        otherwise None.
    """
    current = now if now is not None else time.time()
    fingerprint, canonical = fingerprint_for_startup(operation=operation)
    if duration_ms >= STARTUP_TIMEOUT_MS:
        if _tracker.open_issue_for(fingerprint) is not None:
            return FilingDecision(
                action="update",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=True,
                reason="repeat hard startup failure for known open fingerprint",
            )
        return FilingDecision(
            action="file",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=True,
            reason="hard startup failure >=2.5s files immediately",
        )
    if duration_ms >= STARTUP_WARNING_MS:
        if _tracker.open_issue_for(fingerprint) is not None:
            return FilingDecision(
                action="update",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=False,
                reason="repeat startup warning for known open fingerprint",
            )
        if _tracker.evaluate_startup_warning(now=current):
            return FilingDecision(
                action="file",
                fingerprint=fingerprint,
                canonical=canonical,
                high_priority=False,
                reason="startup warnings twice within 1 hour",
            )
        return FilingDecision(
            action="accumulate",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=False,
            reason="startup warning recorded below filing threshold",
        )
    return None


def evaluate_coroutine_timeout(
    *,
    operation: str,
    exception_type: str | None = None,
) -> FilingDecision:
    """Decide whether a readiness-critical coroutine timeout files an issue.

    Any readiness-critical coroutine hard timeout creates an issue
    immediately unless the exact same failure signature already has an
    open issue.

    Args:
        operation: Named operation that timed out.
        exception_type: Timeout/exception type name when known.

    Returns:
        A filing decision (file or update).
    """
    fingerprint, canonical = fingerprint_for_coroutine(
        operation=operation, exception_type=exception_type
    )
    if _tracker.open_issue_for(fingerprint) is not None:
        return FilingDecision(
            action="update",
            fingerprint=fingerprint,
            canonical=canonical,
            high_priority=True,
            reason="repeat coroutine timeout for known open fingerprint",
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
        return (
            f"Performance: startup {operation_name} "
            f"took {duration_ms:.0f}ms (budget {STARTUP_TIMEOUT_MS}ms)"
        )
    if kind == "coroutine":
        operation_name = operation or "unknown"
        return f"Performance: coroutine timeout in {operation_name}"
    route = normalize_route_template(route_template or "__unmatched__")
    return (
        f"Performance: {(method or 'GET').upper()} {route} "
        f"took {duration_ms:.0f}ms (budget {REQUEST_TIMEOUT_MS}ms)"
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


async def _file_decision_background(
    *,
    decision: FilingDecision,
    title: str,
    body: str,
    labels: list[str],
) -> None:
    """File or update a GitHub issue in bounded background work.

    Failure is logged and observable but never propagates to the caller:
    a GitHub outage must not turn a successful user request into a 5xx.

    Args:
        decision: Synchronous filing decision for the event.
        title: Issue title for new issues.
        body: Issue body with evidence and fingerprint marker.
        labels: Factory intake labels.
    """
    try:
        from app.services import github_service as gh
    except ImportError as exc:
        logger.warning("Performance issue filing skipped: GitHub client unavailable: %s", exc)
        return
    try:
        if decision.action == "update":
            known = _tracker.open_issue_for(decision.fingerprint)
            if known is not None:
                try:
                    await gh.add_performance_issue_comment(
                        known,
                        f"Performance incident recurred ({decision.reason}).",
                    )
                    return
                except RuntimeError as exc:
                    logger.warning(
                        "Performance occurrence update failed for #%s: %s", known, exc
                    )
                    return
        existing = await gh.find_open_issue_by_fingerprint(decision.fingerprint)
        if existing is not None:
            _tracker.mark_open(decision.fingerprint, existing)
            try:
                await gh.add_performance_issue_comment(
                    existing,
                    f"Performance incident recurred ({decision.reason}).",
                )
            except RuntimeError as exc:
                logger.warning(
                    "Performance occurrence update failed for #%s: %s", existing, exc
                )
            return
        prior = _tracker.closed_issue_for(decision.fingerprint)
        if prior is None:
            try:
                prior = await gh.find_closed_issue_by_fingerprint(decision.fingerprint)
            except RuntimeError as exc:
                logger.warning("Performance regression lookup failed: %s", exc)
                prior = None
        issue_number: int | None = None
        try:
            filing_body = body
            if prior is not None and f"#{prior}" not in filing_body:
                filing_body = (
                    f"{filing_body}\n- Regression: this signature previously "
                    f"closed in #{prior}; opened as a new regression issue "
                    f"referencing #{prior}."
                )
            url = await gh.create_performance_issue(
                title=title, body=filing_body, labels=labels
            )
            issue_number = _issue_number_from_url(url)
        except RuntimeError as exc:
            logger.warning("Performance issue filing failed: %s", exc)
            return
        if issue_number is not None:
            _tracker.record_filed(decision.fingerprint, issue_number)
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


def schedule_filing(
    *,
    decision: FilingDecision,
    title: str,
    body: str,
    labels: list[str],
) -> None:
    """Schedule non-blocking background filing for a filing decision.

    Must never delay or fail the production request that triggered the
    telemetry. When no running event loop is available, the filing is
    logged and dropped rather than raising.

    Args:
        decision: Synchronous filing decision for the event.
        title: Issue title for new issues.
        body: Issue body with evidence and fingerprint marker.
        labels: Factory intake labels.
    """
    if decision.action == "accumulate":
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "Performance issue filing skipped: no running event loop (%s)",
            decision.reason,
        )
        return
    loop.create_task(
        _file_decision_background(
            decision=decision, title=title, body=body, labels=labels
        )
    )


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
    decision = evaluate_request_event(
        method=method,
        route_template=route_template,
        duration_ms=duration_ms,
        cold=cold,
        dominant_phase=dominant_phase,
        db_time_ms=db_time_ms,
        db_queries=db_queries,
    )
    if decision is None:
        return
    _tracker.record_occurrence(
        fingerprint=decision.fingerprint,
        canonical=decision.canonical,
        duration_ms=duration_ms,
        request_id=request_id,
        deployment_id=deployment_id,
        now=time.time(),
    )
    if decision.action == "accumulate":
        return
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
    event_label = "violation" if duration_ms >= REQUEST_TIMEOUT_MS else "warning"
    threshold = REQUEST_TIMEOUT_MS if event_label == "violation" else REQUEST_WARNING_MS
    app_time = max(duration_ms - db_time_ms, 0.0)
    workload = classify_workload(duration_ms, db_time_ms, db_queries)
    likely = "database" if workload == "db-heavy" else None
    prior = _tracker.closed_issue_for(decision.fingerprint)
    title = build_issue_title(
        kind="request",
        method=method,
        route_template=route_template,
        duration_ms=duration_ms,
    )
    body = build_issue_body(
        kind="request",
        fingerprint=decision.fingerprint,
        canonical=decision.canonical,
        method=method,
        route_template=route_template,
        duration_ms=duration_ms,
        threshold_ms=float(threshold),
        event_label=event_label,
        cold=cold,
        db_queries=db_queries,
        db_time_ms=db_time_ms,
        app_time_ms=app_time,
        request_ids=[request_id] if request_id else None,
        deployment_id=deployment_id,
        first_seen=first_seen,
        last_seen=last_seen,
        occurrence_count=occurrence_count,
        server_timing=server_timing,
        likely_subsystem=likely,
        prior_issue=prior,
    )
    schedule_filing(
        decision=decision,
        title=title,
        body=body,
        labels=build_labels(high_priority=decision.high_priority, subsystem="backend"),
    )


def handle_startup_telemetry(
    *,
    duration_ms: float,
    operation: str = "startup.readiness",
    deployment_id: str | None = None,
) -> None:
    """Evaluate startup telemetry and schedule filing without blocking.

    Args:
        duration_ms: Measured ping-ready startup duration in milliseconds.
        operation: Named startup phase/operation attribution.
        deployment_id: Deployment/commit identifier.
    """
    decision = evaluate_startup_event(duration_ms=duration_ms, operation=operation)
    if decision is None or decision.action == "accumulate":
        return
    event_label = (
        "startup failure" if duration_ms >= STARTUP_TIMEOUT_MS else "warning"
    )
    threshold = (
        STARTUP_TIMEOUT_MS if duration_ms >= STARTUP_TIMEOUT_MS else STARTUP_WARNING_MS
    )
    prior = _tracker.closed_issue_for(decision.fingerprint)
    title = build_issue_title(
        kind="startup", operation=operation, duration_ms=duration_ms
    )
    body = build_issue_body(
        kind="startup",
        fingerprint=decision.fingerprint,
        canonical=decision.canonical,
        duration_ms=duration_ms,
        threshold_ms=float(threshold),
        event_label=event_label,
        deployment_id=deployment_id,
        occurrence_count=1,
        operation=operation,
        likely_subsystem="infrastructure",
        prior_issue=prior,
    )
    schedule_filing(
        decision=decision,
        title=title,
        body=body,
        labels=build_labels(
            high_priority=decision.high_priority, subsystem="infrastructure"
        ),
    )


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
    decision = evaluate_coroutine_timeout(
        operation=operation, exception_type=exception_type
    )
    if decision.action == "accumulate":
        return
    prior = _tracker.closed_issue_for(decision.fingerprint)
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
    schedule_filing(
        decision=decision,
        title=title,
        body=body,
        labels=build_labels(high_priority=True, subsystem="infrastructure"),
    )
