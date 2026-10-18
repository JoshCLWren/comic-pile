"""Bug report API endpoints."""

import math
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_github_settings
from app.database import get_db
from app.models.user import User
from app.schemas.bug_report import BugReportCreate, BugReportResponse
from app.services.github_issue_rate_limit import (
    GithubIssueSubmissionRateLimitError,
    submit_github_issue,
)

router = APIRouter(tags=["bug-reports"])

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


def _rate_limit_detail(exc: GithubIssueSubmissionRateLimitError) -> str:
    """Build the client-facing 429 explanation with the next allowed time.

    Args:
        exc: Rate-limit signal carrying the user's reset instant.

    Returns:
        A human-readable message that states the hourly policy and when the
        user may submit again.
    """
    minutes = max(math.ceil(exc.retry_after_seconds / 60), 1)
    return (
        "Non-admin accounts can submit one GitHub issue per hour. "
        f"Try again in {minutes} minute(s), after "
        f"{exc.resets_at.strftime('%Y-%m-%d %H:%M')} UTC."
    )


@router.post("/", response_model=BugReportResponse, status_code=status.HTTP_201_CREATED)
async def create_bug_report(
    body: Annotated[BugReportCreate, Body()],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BugReportResponse:
    """Create a bug report or feature request issue on GitHub.

    Non-admin users are limited to one successfully created issue per rolling
    hour. Admins bypass the limit.

    Args:
        body: Report type, title, description, and optional diagnostics.
        current_user: The authenticated user.
        db: Database session used for the durable rate-limit state.

    Returns:
        Created GitHub issue URL.

    Raises:
        HTTPException: If validation fails, GitHub integration is unavailable,
            the non-admin hourly limit is reached, or GitHub rejects the issue.
    """
    title = body.title.strip()
    description = body.description.strip()
    if not title or not description:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Title and description must not be blank",
        )

    github_settings = get_github_settings()
    if not github_settings.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub integration not configured",
        )

    try:
        issue_url = await submit_github_issue(
            db,
            user=current_user,
            report_type=body.report_type,
            title=title,
            description=description,
            diagnostics=body.diagnostics,
        )
    except GithubIssueSubmissionRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_rate_limit_detail(exc),
            headers={
                "Retry-After": str(exc.retry_after_seconds),
                "X-RateLimit-Reset": exc.resets_at.isoformat(),
            },
        ) from exc
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    return BugReportResponse(issue_url=issue_url)
