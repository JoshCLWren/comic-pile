"""Bug report API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.auth import get_current_user
from app.config import get_github_settings
from app.models.user import User
from app.schemas.bug_report import BugReportCreate, BugReportResponse
from app.services.github_service import create_bug_report_issue

router = APIRouter(tags=["bug-reports"])

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


@router.post("/", response_model=BugReportResponse, status_code=status.HTTP_201_CREATED)
async def create_bug_report(
    body: Annotated[BugReportCreate, Body()],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BugReportResponse:
    """Create a bug report issue on GitHub.

    Args:
        body: Bug report with title, description, and optional diagnostics
        current_user: The authenticated user

    Returns:
        Created bug report issue URL

    Raises:
        HTTPException: If validation fails or GitHub integration not configured
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

    diagnostics_data = body.diagnostics

    try:
        issue_url = await create_bug_report_issue(
            title=title,
            description=description,
            username=current_user.username,
            diagnostics_data=diagnostics_data,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    return BugReportResponse(issue_url=issue_url)
