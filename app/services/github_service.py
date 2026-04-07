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
) -> str:
    """Create a GitHub issue for a bug report. Returns the issue HTML URL."""
    settings = get_github_settings()
    g = Github(settings.github_token)
    try:
        repo = g.get_repo(f"{settings.github_repo_owner}/{settings.github_repo_name}")
    except GithubException as e:
        raise RuntimeError(f"Failed to access GitHub repository: {e.data}") from e

    body = f"**Reported by:** {username}\n\n{description}"

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
