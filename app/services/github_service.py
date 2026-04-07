"""GitHub service for creating bug report issues."""

from datetime import datetime, UTC

from github import Github

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
    repo = g.get_repo(f"{settings.github_repo_owner}/{settings.github_repo_name}")

    body = f"**Reported by:** {username}\n\n{description}"

    if screenshot_bytes:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = f"bug-reports/screenshots/{ts}.png"
        repo.create_file(
            path,
            f"Add bug report screenshot {ts}",
            screenshot_bytes,
            branch="main",
        )
        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{settings.github_repo_owner}/{settings.github_repo_name}/main/{path}"
        )
        body += f"\n\n![Screenshot]({raw_url})"

    issue = repo.create_issue(title=title, body=body, labels=["bug", "user-reported"])
    return issue.html_url
