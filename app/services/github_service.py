"""GitHub service for creating user feedback and performance issues."""

from __future__ import annotations

import asyncio
import logging

import httpx
from github import Github, GithubException

from app.config import GitHubSettings, get_github_settings
from app.schemas.bug_report import BugReportDiagnostics, ReportType

logger = logging.getLogger(__name__)

PERFORMANCE_FINGERPRINT_PREFIX = "performance-fingerprint:v1:"
PERFORMANCE_ISSUE_SEARCH_LIMIT = 100

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_REQUEST_TIMEOUT_SECONDS = 30.0


def _escape_markdown_code(value: str) -> str:
    """Escape backticks in a string to prevent breaking Markdown code blocks."""
    return value.replace("`", "\\`")


def _labels_for_report_type(report_type: ReportType) -> list[str]:
    """Return the canonical GitHub labels for a user-submitted report."""
    if report_type == "feature":
        return ["enhancement", "user-reported"]
    return ["bug", "user-reported"]


def _github_headers(settings: GitHubSettings) -> dict[str, str]:
    """Build common GitHub REST API headers."""
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def _repo_issues_url(settings: GitHubSettings) -> str:
    """Build the repository issues API URL from configured owner and name."""
    return (
        f"{GITHUB_API_BASE}/repos/"
        f"{settings.github_repo_owner}/{settings.github_repo_name}/issues"
    )


async def create_bug_report_issue(
    report_type: ReportType,
    title: str,
    description: str,
    username: str,
    diagnostics_data: BugReportDiagnostics | None = None,
) -> str:
    """Create a GitHub issue for user feedback.

    Args:
        report_type: Whether the feedback is a bug report or feature request.
        title: User-provided issue title.
        description: User-provided issue description.
        username: ComicPile username that submitted the feedback.
        diagnostics_data: Optional browser and runtime diagnostics to append.

    Returns:
        The HTML URL of the newly created GitHub issue.

    Raises:
        RuntimeError: If GitHub integration is not configured or issue creation fails.
    """
    settings = get_github_settings()
    if not settings.is_configured:
        raise RuntimeError("GitHub integration not configured")

    report_label = "Feature request" if report_type == "feature" else "Bug report"
    body = (
        f"**Reported by:** {_escape_markdown_code(username)}\n"
        f"**Report type:** {report_label}\n\n{description}"
    )

    if diagnostics_data:
        timestamp = diagnostics_data.timestamp
        url = diagnostics_data.url
        user_agent = diagnostics_data.user_agent

        screen_width = diagnostics_data.screen.width
        screen_height = diagnostics_data.screen.height
        pixel_ratio = diagnostics_data.screen.pixel_ratio

        viewport_width = diagnostics_data.viewport.width
        viewport_height = diagnostics_data.viewport.height

        scroll_x = diagnostics_data.scroll.x
        scroll_y = diagnostics_data.scroll.y

        dom_complete = diagnostics_data.performance.dom_content_loaded
        load_complete = diagnostics_data.performance.load_complete

        perf_str = ""
        if dom_complete is not None or load_complete is not None:
            parts = []
            if dom_complete is not None:
                parts.append(f"DOMContentLoaded: {dom_complete:.0f}ms")
            if load_complete is not None:
                parts.append(f"Load: {load_complete:.0f}ms")
            perf_str = ", ".join(parts)

        errors = diagnostics_data.errors
        errors_str = "\n".join(
            f"```\n{_escape_markdown_code(error.message)}\n```" for error in errors
        )
        if not errors:
            errors_str = "None"

        body += f"""

<details>
<summary>Diagnostic Information</summary>

**Timestamp:** {_escape_markdown_code(timestamp)}
**URL:** {_escape_markdown_code(url)}
**User Agent:** {_escape_markdown_code(user_agent)}
**Screen:** {screen_width}×{screen_height} @{pixel_ratio}x
**Viewport:** {viewport_width}×{viewport_height}
**Scroll:** ({scroll_x}, {scroll_y})
"""
        if perf_str:
            body += f"**Performance:** {perf_str}\n"

        body += f"""
**Console Errors (last {len(errors)}):**
{errors_str}
</details>"""

    try:
        async with httpx.AsyncClient(timeout=GITHUB_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _repo_issues_url(settings),
                headers=_github_headers(settings),
                json={
                    "title": title,
                    "body": body,
                    "labels": _labels_for_report_type(report_type),
                },
            )
            response.raise_for_status()
            data: object = response.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Failed to create GitHub issue: {e.response.text}") from e
    except (httpx.RequestError, ValueError) as e:
        raise RuntimeError(f"Failed to create GitHub issue: {e}") from e

    html_url = data.get("html_url") if isinstance(data, dict) else None
    if not isinstance(html_url, str) or not html_url:
        raise RuntimeError("Failed to create GitHub issue: response contained no issue URL")
    return html_url


def _performance_repo():
    """Resolve the configured GitHub repository for performance incidents.

    Returns:
        The PyGithub repository object.

    Raises:
        RuntimeError: If GitHub integration is not configured or the
            repository cannot be accessed.
    """
    settings = get_github_settings()
    if not settings.is_configured:
        raise RuntimeError("GitHub integration not configured")
    g = Github(settings.github_token)
    try:
        return g.get_repo(f"{settings.github_repo_owner}/{settings.github_repo_name}")
    except GithubException as e:
        raise RuntimeError(f"Failed to access GitHub repository: {e.data}") from e


def _normalize_route_template(route: str) -> str:
    """Normalize a route template for identity matching.

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


def _issue_matches_fingerprint(issue_body: str | None, fingerprint: str) -> bool:
    """Check whether an issue body carries a performance fingerprint marker.

    Args:
        issue_body: Issue body text, when available.
        fingerprint: Deterministic performance signature hash.

    Returns:
        True when the body contains the fingerprint marker.
    """
    if not issue_body:
        return False
    return f"{PERFORMANCE_FINGERPRINT_PREFIX}{fingerprint}" in issue_body


def _issue_matches_request_identity(
    *,
    title: str | None,
    body: str | None,
    method: str | None,
    route_template: str | None,
) -> bool:
    """Match an open issue by method plus route when the hash marker differs.

    Used so the #3552 fingerprint change reuses issues opened under the
    legacy ``request|METHOD|route|warm|phase|workload`` hash.

    Args:
        title: Issue title, when available.
        body: Issue body, when available.
        method: HTTP method of the new sample.
        route_template: Normalized route of the new sample.

    Returns:
        True when the issue is the same method plus route.
    """
    if not method or not route_template:
        return False
    identity = f"{method.upper()} {_normalize_route_template(route_template)}"
    body_text = body or ""
    title_text = title or ""
    if f"- Method + route: {identity}" in body_text:
        return True
    return f"Performance: {identity} took" in title_text


def _fingerprints_to_search(
    fingerprint: str,
    extra_fingerprints: list[str] | tuple[str, ...] | None,
) -> list[str]:
    """Build the ordered unique fingerprint list for a GitHub search.

    Args:
        fingerprint: Current deterministic performance signature hash.
        extra_fingerprints: Legacy hashes that should reuse the same issue.

    Returns:
        Deduplicated fingerprint hashes, current first.
    """
    ordered = [fingerprint]
    for extra in extra_fingerprints or ():
        if extra and extra not in ordered:
            ordered.append(extra)
    return ordered


def _find_issue_by_identity_sync(
    *,
    state: str,
    fingerprints: list[str],
    method: str | None,
    route_template: str | None,
) -> int | None:
    """Search performance issues for a fingerprint or method-plus-route match.

    Args:
        state: GitHub issue state (``open`` or ``closed``).
        fingerprints: Current and legacy fingerprint hashes to match.
        method: HTTP method for rollout-compatible route matching.
        route_template: Route template for rollout-compatible matching.

    Returns:
        Matching issue number, or None.

    Raises:
        RuntimeError: If the GitHub lookup fails.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issues = repo.get_issues(state=state, labels=["performance"])
        checked = 0
        for issue in issues:
            if checked >= PERFORMANCE_ISSUE_SEARCH_LIMIT:
                break
            checked += 1
            if getattr(issue, "pull_request", None) is not None:
                continue
            body = getattr(issue, "body", None)
            title = getattr(issue, "title", None)
            for candidate in fingerprints:
                if _issue_matches_fingerprint(body, candidate):
                    return issue.number
            if _issue_matches_request_identity(
                title=title,
                body=body,
                method=method,
                route_template=route_template,
            ):
                return issue.number
        return None
    except GithubException as e:
        raise RuntimeError(f"Failed to search performance issues: {e.data}") from e


def _create_performance_issue_sync(title: str, body: str, labels: list[str]) -> str:
    """Create a performance issue on the blocking PyGithub client.

    Args:
        title: Focused issue title with route/operation and duration.
        body: Evidence-rich body containing the hidden fingerprint marker.
        labels: Factory intake labels for the issue.

    Returns:
        The HTML URL of the newly created GitHub issue.

    Raises:
        RuntimeError: If GitHub is unconfigured or issue creation fails.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issue = repo.create_issue(title=title, body=body, labels=labels)
    except GithubException as e:
        raise RuntimeError(f"Failed to create performance issue: {e.data}") from e
    return issue.html_url


def _get_performance_issue_state_sync(issue_number: int) -> str | None:
    """Read a performance issue's GitHub state without commenting.

    Args:
        issue_number: GitHub issue number.

    Returns:
        ``open``, ``closed``, or None when the issue cannot be fetched.

    Raises:
        RuntimeError: If GitHub is unconfigured or the lookup fails.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issue = repo.get_issue(number=issue_number)
        return issue.state
    except GithubException as e:
        raise RuntimeError(
            f"Failed to read performance issue #{issue_number}: {e.data}"
        ) from e


def _add_performance_issue_comment_sync(issue_number: int, comment: str) -> str | None:
    """Comment on an open performance issue; never comment when closed.

    Args:
        issue_number: GitHub issue number to comment on.
        comment: Short recurrence note.

    Returns:
        The issue state after the check (and comment, when open).

    Raises:
        RuntimeError: If GitHub is unconfigured or the update fails.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issue = repo.get_issue(number=issue_number)
        if issue.state != "open":
            return issue.state
        issue.create_comment(comment)
        return issue.state
    except GithubException as e:
        raise RuntimeError(
            f"Failed to update performance issue #{issue_number}: {e.data}"
        ) from e


async def create_performance_issue(
    title: str,
    body: str,
    labels: list[str],
) -> str:
    """Create an auto-filed production performance issue.

    This path is isolated from the interactive user-feedback path:
    machine-generated performance incidents never receive ``user-reported``
    and carry factory intake labels instead of report-type labels.

    PyGithub is synchronous; the blocking client runs in a worker thread so
    the request event loop is not stalled.

    Args:
        title: Focused issue title with route/operation and duration.
        body: Evidence-rich body containing the hidden fingerprint marker.
        labels: Factory intake labels for the issue.

    Returns:
        The HTML URL of the newly created GitHub issue.

    Raises:
        RuntimeError: If GitHub is unconfigured or issue creation fails.
    """
    if "user-reported" in labels:
        raise RuntimeError("Machine-generated performance issues must not use user-reported")
    return await asyncio.to_thread(_create_performance_issue_sync, title, body, labels)


async def get_performance_issue_state(issue_number: int) -> str | None:
    """Return the GitHub state of a performance issue without commenting.

    Args:
        issue_number: GitHub issue number.

    Returns:
        ``open``, ``closed``, or None when unread.

    Raises:
        RuntimeError: If GitHub is unconfigured or the lookup fails.
    """
    return await asyncio.to_thread(_get_performance_issue_state_sync, issue_number)


async def find_open_issue_by_fingerprint(
    fingerprint: str,
    *,
    extra_fingerprints: list[str] | tuple[str, ...] | None = None,
    method: str | None = None,
    route_template: str | None = None,
) -> int | None:
    """Find an open performance issue for a fingerprint, if one exists.

    Lookup is rollout-compatible: the current hash, any legacy hashes, and
    the method-plus-route identity in title or body all match.

    Args:
        fingerprint: Deterministic performance signature hash.
        extra_fingerprints: Legacy hashes that should reuse the same issue.
        method: HTTP method for route-identity fallback matching.
        route_template: Route template for route-identity fallback matching.

    Returns:
        The open issue number, or None when no open issue matches.

    Raises:
        RuntimeError: If the GitHub lookup fails.
    """
    fingerprints = _fingerprints_to_search(fingerprint, extra_fingerprints)
    return await asyncio.to_thread(
        _find_issue_by_identity_sync,
        state="open",
        fingerprints=fingerprints,
        method=method,
        route_template=route_template,
    )


async def find_closed_issue_by_fingerprint(
    fingerprint: str,
    *,
    extra_fingerprints: list[str] | tuple[str, ...] | None = None,
    method: str | None = None,
    route_template: str | None = None,
) -> int | None:
    """Find a closed performance issue for a fingerprint, if one exists.

    Used for regression detection: when a previously fixed signature
    regresses, a new regression issue references the prior one instead of
    silently reopening historical work.

    Args:
        fingerprint: Deterministic performance signature hash.
        extra_fingerprints: Legacy hashes that should reuse the same issue.
        method: HTTP method for route-identity fallback matching.
        route_template: Route template for route-identity fallback matching.

    Returns:
        The most recent closed issue number, or None.

    Raises:
        RuntimeError: If the GitHub lookup fails.
    """
    fingerprints = _fingerprints_to_search(fingerprint, extra_fingerprints)
    return await asyncio.to_thread(
        _find_issue_by_identity_sync,
        state="closed",
        fingerprints=fingerprints,
        method=method,
        route_template=route_template,
    )


async def add_performance_issue_comment(issue_number: int, comment: str) -> str | None:
    """Append occurrence evidence to an existing open performance issue.

    Reads ``issue.state`` before commenting and never comments on a closed
    issue. Callers treat a non-open return as a closed-issue regression that
    must re-enter the daily N-hit threshold.

    Args:
        issue_number: GitHub issue number to comment on.
        comment: Short recurrence note (not one comment per raw request).

    Returns:
        The issue state after the check (``open`` or ``closed``), or None
        when the issue could not be fetched.

    Raises:
        RuntimeError: If the comment cannot be posted on an open issue.
    """
    return await asyncio.to_thread(
        _add_performance_issue_comment_sync, issue_number, comment
    )
