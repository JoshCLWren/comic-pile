"""Server-side rolling-hour limit for ComicPile GitHub issue submissions.

Non-admin users may create at most one GitHub issue per rolling hour through
ComicPile. The limit is enforced with the durable
``github_issue_submission_limits`` row rather than process memory, so it holds
across app instances and serverless invocations. The slot is claimed
atomically before the GitHub call and only recorded as consumed after GitHub
confirms creation, so a failed attempt never locks the user out.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.github_issue_rate_limit_repository import (
    claim_submission_slot,
    get_submission_limit,
    record_successful_submission,
)
from app.schemas.bug_report import BugReportDiagnostics, ReportType
from app.services.github_service import create_bug_report_issue

GITHUB_ISSUE_SUBMISSION_WINDOW = timedelta(hours=1)


class GithubIssueSubmissionRateLimitError(Exception):
    """Raised when a non-admin submits a second issue inside the rolling window."""

    def __init__(self, *, retry_after_seconds: int, resets_at: datetime) -> None:
        """Build the rate-limit signal with the client-visible reset details.

        Args:
            retry_after_seconds: Whole seconds until the user may submit again.
            resets_at: Instant when the rolling window opens for the user.
        """
        super().__init__("Non-admin accounts can submit one GitHub issue per hour")
        self.retry_after_seconds = retry_after_seconds
        self.resets_at = resets_at


def _blocked_until(
    limit_last_submitted_at: datetime | None,
    *,
    now: datetime,
) -> datetime:
    """Return when the user's rolling window opens again.

    Args:
        limit_last_submitted_at: Stored successful submission time, if any.
        now: Current UTC instant used as a defensive fallback.

    Returns:
        The confirmable reset instant for the user's allowance.
    """
    if limit_last_submitted_at is None:
        return now + GITHUB_ISSUE_SUBMISSION_WINDOW
    return limit_last_submitted_at + GITHUB_ISSUE_SUBMISSION_WINDOW


def retry_after_seconds(resets_at: datetime, *, now: datetime) -> int:
    """Return the non-negative full seconds until ``resets_at``.

    Args:
        resets_at: Instant when the user may submit again.
        now: Current UTC instant.

    Returns:
        At least one second so clients always receive a usable cooldown.
    """
    return max(math.ceil((resets_at - now).total_seconds()), 1)


async def submit_github_issue(
    db: AsyncSession,
    *,
    user: User,
    report_type: ReportType,
    title: str,
    description: str,
    diagnostics: BugReportDiagnostics | None = None,
) -> str:
    """Create a GitHub issue for ``user`` under the non-admin hourly limit.

    Admins bypass the limit. For everyone else the rolling-window slot is
    claimed atomically before contacting GitHub; the claim is only committed
    after GitHub confirms creation. A blocked user raises
    ``GithubIssueSubmissionRateLimitError``; a failed GitHub call rolls the claim
    back so the allowance is not consumed.

    Args:
        db: SQLAlchemy async session owning the transaction.
        user: Authenticated ComicPile user submitting the report.
        report_type: Whether the feedback is a bug report or feature request.
        title: User-provided issue title.
        description: User-provided issue description.
        diagnostics: Optional browser diagnostics to append to the issue body.

    Returns:
        The HTML URL of the newly created GitHub issue.

    Raises:
        GithubIssueSubmissionRateLimitError: If a non-admin already submitted an
            issue inside the rolling hour.
        RuntimeError: If GitHub issue creation fails.
    """
    if user.is_admin:
        return await create_bug_report_issue(
            report_type=report_type,
            title=title,
            description=description,
            username=user.username,
            diagnostics_data=diagnostics,
        )

    user_id = user.id
    username = user.username
    now = datetime.now(UTC)

    claimed = await claim_submission_slot(
        db,
        user_id=user_id,
        window_start=now - GITHUB_ISSUE_SUBMISSION_WINDOW,
    )
    if not claimed:
        limit = await get_submission_limit(db, user_id=user_id)
        resets_at = _blocked_until(
            limit.last_submitted_at if limit is not None else None,
            now=now,
        )
        await db.rollback()
        raise GithubIssueSubmissionRateLimitError(
            retry_after_seconds=retry_after_seconds(resets_at, now=now),
            resets_at=resets_at,
        )

    try:
        issue_url = await create_bug_report_issue(
            report_type=report_type,
            title=title,
            description=description,
            username=username,
            diagnostics_data=diagnostics,
        )
    except BaseException:
        # The claim is uncommitted; rolling back releases the row lock without
        # consuming the user's allowance.
        await db.rollback()
        raise

    await record_successful_submission(
        db,
        user_id=user_id,
        submitted_at=datetime.now(UTC),
    )
    await db.commit()
    return issue_url
