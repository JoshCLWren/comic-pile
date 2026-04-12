"""GitHub service for creating bug report issues."""

from datetime import datetime, UTC
from pathlib import Path

from github import Github, GithubException

from app.config import get_github_settings


async def create_bug_report_issue(
    title: str,
    description: str,
    username: str,
    screenshot_bytes: bytes | None = None,
    screenshot_filename: str | None = None,
    diagnostics_data: dict | None = None,
    screenshot_diagnostics_data: dict | None = None,
) -> str:
    """Create a GitHub issue for a bug report. Returns the issue HTML URL."""
    settings = get_github_settings()
    g = Github(settings.github_token)
    try:
        repo = g.get_repo(f"{settings.github_repo_owner}/{settings.github_repo_name}")
    except GithubException as e:
        raise RuntimeError(f"Failed to access GitHub repository: {e.data}") from e

    body = f"**Reported by:** {username}\n\n{description}"

    if diagnostics_data:
        timestamp = diagnostics_data.get("timestamp", "unknown")
        url = diagnostics_data.get("url", "unknown")
        user_agent = diagnostics_data.get("userAgent", "unknown")

        screen = diagnostics_data.get("screen", {})
        screen_width = screen.get("width", 0)
        screen_height = screen.get("height", 0)
        pixel_ratio = screen.get("pixelRatio", 1)

        viewport = diagnostics_data.get("viewport", {})
        viewport_width = viewport.get("width", 0)
        viewport_height = viewport.get("height", 0)

        scroll = diagnostics_data.get("scroll", {})
        scroll_x = scroll.get("x", 0)
        scroll_y = scroll.get("y", 0)

        perf = diagnostics_data.get("performance", {})
        dom_complete = perf.get("domContentLoaded")
        load_complete = perf.get("loadComplete")

        perf_str = ""
        if dom_complete is not None or load_complete is not None:
            parts = []
            if dom_complete is not None:
                parts.append(f"DOMContentLoaded: {dom_complete:.0f}ms")
            if load_complete is not None:
                parts.append(f"Load: {load_complete:.0f}ms")
            perf_str = ", ".join(parts)

        errors = diagnostics_data.get("errors", [])
        errors_str = "\n".join(f"```\n{error.get('message', 'unknown')}\n```" for error in errors)
        if not errors:
            errors_str = "None"

        body += f"""

<details>
<summary>Diagnostic Information</summary>

**Timestamp:** {timestamp}
**URL:** {url}
**User Agent:** {user_agent}
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

    if screenshot_diagnostics_data:
        target = screenshot_diagnostics_data.get("target", {})
        env = screenshot_diagnostics_data.get("environment", {})
        attempts = screenshot_diagnostics_data.get("captureAttempts", [])
        ancestor = screenshot_diagnostics_data.get("ancestorChain", [])
        body += f"""

<details>
<summary>Screenshot Diagnostics</summary>

**Target:** {target.get("tag", "unknown")}#{target.get("id", "")} (children: {target.get("children", 0)})
**Pixel Ratio:** {env.get("pixelRatio", "unknown")} (device: {env.get("devicePixelRatio", "unknown")})
**ForeignObject Support:** {env.get("canUseForeignObject", "unknown")}

**Capture Attempts:**
"""
        for attempt in attempts:
            method = attempt.get("method", "unknown")
            success = attempt.get("success", False)
            size = attempt.get("size", "N/A")
            error = attempt.get("error", "")
            blank = attempt.get("blank")
            body += f"- {method}: success={success}, size={size}"
            if error:
                body += f", error={error}"
            if blank is not None:
                body += f", blank={blank}"
            body += "\n"

        body += """
**Ancestor Chain:**
"""
        for i, ancestor_info in enumerate(ancestor):
            tag = ancestor_info.get("tag", "?")
            id_ = ancestor_info.get("id", "")
            transform = ancestor_info.get("transform", "none")
            filter_ = ancestor_info.get("filter", "none")
            backdrop = ancestor_info.get("backdropFilter", "none")
            body += f"- {i}: {tag}#{id_} transform={transform} filter={filter_} backdrop-filter={backdrop}\n"

        body += "</details>"

    if screenshot_bytes:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        ext = Path(screenshot_filename).suffix.lower() if screenshot_filename else ".png"
        if ext not in {".png", ".jpg", ".jpeg"}:
            ext = ".png"
        path = f"bug-reports/screenshots/{ts}{ext}"
        try:
            repo.create_file(
                path,
                f"Add bug report screenshot {ts}",
                screenshot_bytes,
                branch="main",
            )
        except GithubException as e:
            raise RuntimeError(f"Failed to upload screenshot: {e.data}") from e
        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{settings.github_repo_owner}/{settings.github_repo_name}/main/{path}"
        )
        body += f"\n\n![Screenshot]({raw_url})"

    try:
        issue = repo.create_issue(title=title, body=body, labels=["bug", "user-reported"])
    except GithubException as e:
        raise RuntimeError(f"Failed to create GitHub issue: {e.data}") from e
    return issue.html_url
