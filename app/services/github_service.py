"""GitHub service for creating user feedback and performance issues."""

import logging

from github import Github, GithubException

from app.config import get_github_settings
from app.schemas.bug_report import BugReportDiagnostics, ReportType

logger = logging.getLogger(__name__)

PERFORMANCE_FINGERPRINT_PREFIX = "performance-fingerprint:v1:"
PERFORMANCE_ISSUE_SEARCH_LIMIT = 100


def _escape_markdown_code(value: str) -> str:
    """Escape backticks in a string to prevent breaking Markdown code blocks."""
    return value.replace("`", "\\`")


def _labels_for_report_type(report_type: ReportType) -> list[str]:
    """Return the canonical GitHub labels for a user-submitted report."""
    if report_type == "feature":
        return ["enhancement", "user-reported"]
    return ["bug", "user-reported"]


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
    """
    settings = get_github_settings()
    g = Github(settings.github_token)
    try:
        repo = g.get_repo(f"{settings.github_repo_owner}/{settings.github_repo_name}")
    except GithubException as e:
        raise RuntimeError(f"Failed to access GitHub repository: {e.data}") from e

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
        issue = repo.create_issue(
            title=title,
            body=body,
            labels=_labels_for_report_type(report_type),
        )
    except GithubException as e:
        raise RuntimeError(f"Failed to create GitHub issue: {e.data}") from e
    return issue.html_url


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


async def create_performance_issue(
    title: str,
    body: str,
    labels: list[str],
) -> str:
    """Create an auto-filed production performance issue.

    This path is isolated from the interactive user-feedback path:
    machine-generated performance incidents never receive ``user-reported``
    and carry factory intake labels instead of report-type labels.

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
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issue = repo.create_issue(title=title, body=body, labels=labels)
    except GithubException as e:
        raise RuntimeError(f"Failed to create performance issue: {e.data}") from e
    return issue.html_url


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


async def find_open_issue_by_fingerprint(fingerprint: str) -> int | None:
    """Find an open performance issue for a fingerprint, if one exists.

    Args:
        fingerprint: Deterministic performance signature hash.

    Returns:
        The open issue number, or None when no open issue matches.

    Raises:
        RuntimeError: If the GitHub lookup fails.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issues = repo.get_issues(state="open", labels=["performance"])
        checked = 0
        for issue in issues:
            if checked >= PERFORMANCE_ISSUE_SEARCH_LIMIT:
                break
            checked += 1
            if getattr(issue, "pull_request", None) is not None:
                continue
            if _issue_matches_fingerprint(getattr(issue, "body", None), fingerprint):
                return issue.number
        return None
    except GithubException as e:
        raise RuntimeError(f"Failed to search performance issues: {e.data}") from e


async def find_closed_issue_by_fingerprint(fingerprint: str) -> int | None:
    """Find a closed performance issue for a fingerprint, if one exists.

    Used for regression detection: when a previously fixed signature
    regresses, a new regression issue references the prior one instead of
    silently reopening historical work.

    Args:
        fingerprint: Deterministic performance signature hash.

    Returns:
        The most recent closed issue number, or None.

    Raises:
        RuntimeError: If the GitHub lookup fails.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issues = repo.get_issues(state="closed", labels=["performance"])
        checked = 0
        for issue in issues:
            if checked >= PERFORMANCE_ISSUE_SEARCH_LIMIT:
                break
            checked += 1
            if getattr(issue, "pull_request", None) is not None:
                continue
            if _issue_matches_fingerprint(getattr(issue, "body", None), fingerprint):
                return issue.number
        return None
    except GithubException as e:
        raise RuntimeError(f"Failed to search closed performance issues: {e.data}") from e


async def add_performance_issue_comment(issue_number: int, comment: str) -> None:
    """Append occurrence evidence to an existing performance issue.

    Args:
        issue_number: GitHub issue number to comment on.
        comment: Short recurrence note (not one comment per raw request).

    Raises:
        RuntimeError: If the comment cannot be posted.
    """
    try:
        repo = _performance_repo()
    except RuntimeError:
        raise
    try:
        issue = repo.get_issue(number=issue_number)
        issue.create_comment(comment)
    except GithubException as e:
        raise RuntimeError(
            f"Failed to update performance issue #{issue_number}: {e.data}"
        ) from e
