"""GitHub service for creating bug report issues."""

from github import Github, GithubException

from app.config import get_github_settings
from app.schemas.bug_report import BugReportDiagnostics


def _escape_markdown_code(value: str) -> str:
    """Escape backticks in a string to prevent breaking Markdown code blocks."""
    return value.replace("`", "\\`")


async def create_bug_report_issue(
    title: str,
    description: str,
    username: str,
    diagnostics_data: BugReportDiagnostics | None = None,
) -> str:
    """Create a GitHub issue for a bug report. Returns the issue HTML URL."""
    settings = get_github_settings()
    g = Github(settings.github_token)
    try:
        repo = g.get_repo(f"{settings.github_repo_owner}/{settings.github_repo_name}")
    except GithubException as e:
        raise RuntimeError(f"Failed to access GitHub repository: {e.data}") from e

    body = f"**Reported by:** {_escape_markdown_code(username)}\n\n{description}"

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
        issue = repo.create_issue(title=title, body=body, labels=["bug", "user-reported"])
    except GithubException as e:
        raise RuntimeError(f"Failed to create GitHub issue: {e.data}") from e
    return issue.html_url
