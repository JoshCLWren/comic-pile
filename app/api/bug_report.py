"""Bug report API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth import get_current_user
from app.config import get_github_settings
from app.models.user import User
from app.schemas.bug_report import BugReportResponse
from app.services.github_service import create_bug_report_issue

router = APIRouter(tags=["bug-reports"])

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_SCREENSHOT_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_SCREENSHOT_TYPES = {"image/png", "image/jpeg"}


@router.post("/", response_model=BugReportResponse, status_code=status.HTTP_201_CREATED)
async def create_bug_report(
    title: Annotated[str, Form(max_length=MAX_TITLE_LENGTH)],
    description: Annotated[str, Form(max_length=MAX_DESCRIPTION_LENGTH)],
    current_user: Annotated[User, Depends(get_current_user)],
    screenshot: Annotated[UploadFile, File()] | None = None,
) -> BugReportResponse:
    """Create a bug report issue on GitHub.

    Args:
        title: Bug report title (max 200 chars)
        description: Bug report description (max 2000 chars)
        current_user: The authenticated user
        screenshot: Optional screenshot file (PNG/JPEG, max 5MB)

    Returns:
        Created bug report issue URL

    Raises:
        HTTPException: If validation fails or GitHub integration not configured
    """
    github_settings = get_github_settings()
    if not github_settings.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub integration not configured",
        )

    screenshot_bytes = None
    screenshot_filename = None

    if screenshot:
        if screenshot.content_type not in ALLOWED_SCREENSHOT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid screenshot type. Allowed: {', '.join(ALLOWED_SCREENSHOT_TYPES)}",
            )

        content = await screenshot.read()
        if len(content) > MAX_SCREENSHOT_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Screenshot too large. Max size: {MAX_SCREENSHOT_SIZE // (1024 * 1024)}MB",
            )

        screenshot_bytes = content
        screenshot_filename = screenshot.filename

    issue_url = await create_bug_report_issue(
        title=title,
        description=description,
        username=current_user.username,
        screenshot_bytes=screenshot_bytes,
        screenshot_filename=screenshot_filename,
    )

    return BugReportResponse(issue_url=issue_url)
