"""Creator metric drilldown service for explaining analytics (issue #3176).

This service provides detailed explanations of creator metrics including:
- The exact calculation formula
- The specific issues included in the calculation
- The issues excluded and why
- Pagination for large result sets

All calculations use the same semantics as the comparison and detail APIs
to ensure consistency between summary and drilldown views.
"""

from __future__ import annotations

import math
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.creator_comparison import (
    CreatorMetricCalculation,
    CreatorMetricDrilldown,
    CreatorMetricIssue,
    CreatorRatingDistributionDrilldown,
    CreatorRoleDrilldown,
    CreatorSeriesDrilldown,
)
from app.services.creator_detail import get_creator_issues_with_metadata


async def get_creator_metric_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    metric_type: str,
    role: str | None = None,
    rating_value: str | None = None,
    series_key: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> CreatorMetricDrilldown:
    """Return detailed drilldown for a specific creator metric.

    Args:
        db: Async database session.
        user_id: Authenticated user ID.
        creator_key: Canonical creator key (e.g. ``creator:12345``).
        metric_type: Type of metric to drill down.
        role: Specific role for role-based metrics.
        rating_value: Specific rating value for distribution metrics.
        series_key: Specific series key for series metrics.
        page: Page number for paginated results.
        page_size: Number of items per page.

    Returns:
        Detailed drilldown with calculation and issue lists.

    Raises:
        ValueError: When the metric type is invalid or parameters are missing.
        KeyError: When the creator or requested data is not found.
    """
    # Validate metric type
    valid_metric_types = {
        "average-rating",
        "median-rating",
        "rated-issue-count",
        "five-star-rate",
        "rating-distribution",
        "unread-count",
        "read-unrated-count",
        "role-stats",
        "series-stats",
    }
    
    if metric_type not in valid_metric_types:
        raise ValueError(f"Invalid metric type: {metric_type}. Valid types: {valid_metric_types}")

    # Get the creator's issues with metadata
    creator_issues = await get_creator_issues_with_metadata(db, user_id, creator_key)
    
    if not creator_issues:
        raise KeyError(f"Creator {creator_key} not found in user's library")

    # Filter based on metric type and optional parameters
    if metric_type == "role-stats" and not role:
        raise ValueError("Role is required for role-stats metric type")
    
    if metric_type == "rating-distribution" and not rating_value:
        raise ValueError("Rating value is required for rating-distribution metric type")
    
    if metric_type == "series-stats" and not series_key:
        raise ValueError("Series key is required for series-stats metric type")

    # Calculate drilldown based on metric type
    if metric_type == "average-rating":
        return await _calculate_average_rating_drilldown(
            creator_issues, creator_key, page, page_size
        )
    elif metric_type == "median-rating":
        return await _calculate_median_rating_drilldown(
            creator_issues, creator_key, page, page_size
        )
    elif metric_type == "rated-issue-count":
        return await _calculate_rated_issue_count_drilldown(
            creator_issues, creator_key, page, page_size
        )
    elif metric_type == "five-star-rate":
        return await _calculate_five_star_rate_drilldown(
            creator_issues, creator_key, page, page_size
        )
    elif metric_type == "rating-distribution":
        return await _calculate_rating_distribution_drilldown(
            creator_issues, creator_key, rating_value, page, page_size
        )
    elif metric_type == "unread-count":
        return await _calculate_unread_count_drilldown(
            creator_issues, creator_key, page, page_size
        )
    elif metric_type == "read-unrated-count":
        return await _calculate_read_unrated_count_drilldown(
            creator_issues, creator_key, page, page_size
        )
    elif metric_type == "role-stats":
        return await _calculate_role_stats_drilldown(
            creator_issues, creator_key, role, page, page_size
        )
    elif metric_type == "series-stats":
        return await _calculate_series_stats_drilldown(
            creator_issues, creator_key, series_key, page, page_size
        )
    else:
        raise ValueError(f"Unsupported metric type: {metric_type}")


async def _calculate_average_rating_drilldown(
    creator_issues: list[dict], creator_key: str, page: int, page_size: int
) -> CreatorMetricDrilldown:
    """Calculate drilldown for average rating metric."""
    # Filter rated issues
    rated_issues = [issue for issue in creator_issues if issue.get("effective_rating") is not None]
    total_ratings = len(rated_issues)
    
    if total_ratings == 0:
        calculation = CreatorMetricCalculation(
            formula="No ratings available",
            numerator="No rated issues",
            denominator=None,
            percentage=None,
        )
        
        return CreatorMetricDrilldown(
            metric_type="average-rating",
            creator_key=creator_key,
            calculation=calculation,
            total_count=0,
            included_issues=[],
            excluded_issues=creator_issues,  # All issues excluded due to no rating
            pagination={"page": page, "page_size": page_size, "total_pages": 0},
        )

    # Calculate average
    total_rating_points = sum(issue["effective_rating"] for issue in rated_issues)
    average_rating = total_rating_points / total_ratings

    calculation = CreatorMetricCalculation(
        formula=f"{total_rating_points} total rating points ÷ {total_ratings} rated issues = {average_rating:.2f}★",
        numerator=f"{total_rating_points} total rating points",
        denominator=f"{total_ratings} rated issues",
        percentage=f"{average_rating:.2f}★",
    )

    # Paginate rated issues
    total_pages = math.ceil(len(rated_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = rated_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (those without ratings)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason="No stored effective rating")
        for issue in creator_issues
        if issue.get("effective_rating") is None
    ]

    return CreatorMetricDrilldown(
        metric_type="average-rating",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_ratings,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
    )


async def _calculate_median_rating_drilldown(
    creator_issues: list[dict], creator_key: str, page: int, page_size: int
) -> CreatorMetricDrilldown:
    """Calculate drilldown for median rating metric."""
    # Filter rated issues
    rated_issues = [issue for issue in creator_issues if issue.get("effective_rating") is not None]
    total_ratings = len(rated_issues)
    
    if total_ratings == 0:
        calculation = CreatorMetricCalculation(
            formula="No ratings available",
            numerator="No rated issues",
            denominator=None,
            percentage=None,
        )
        
        return CreatorMetricDrilldown(
            metric_type="median-rating",
            creator_key=creator_key,
            calculation=calculation,
            total_count=0,
            included_issues=[],
            excluded_issues=creator_issues,  # All issues excluded due to no rating
            pagination={"page": page, "page_size": page_size, "total_pages": 0},
        )

    # Sort by rating for median calculation
    sorted_issues = sorted(rated_issues, key=lambda x: x["effective_rating"])
    
    # Calculate median
    if total_ratings % 2 == 1:
        # Odd number of observations - middle value
        median_idx = total_ratings // 2
        median_rating = sorted_issues[median_idx]["effective_rating"]
        median_observation = f"middle value (#{median_idx + 1}) = {median_rating}★"
    else:
        # Even number of observations - average of two middle values
        median_idx1 = total_ratings // 2 - 1
        median_idx2 = total_ratings // 2
        median_rating1 = sorted_issues[median_idx1]["effective_rating"]
        median_rating2 = sorted_issues[median_idx2]["effective_rating"]
        median_rating = (median_rating1 + median_rating2) / 2
        median_observation = f"middle observations (#{median_idx1 + 1} and #{median_idx2 + 1}) = {median_rating1}★ and {median_rating2}★, average = {median_rating}★"

    calculation = CreatorMetricCalculation(
        formula=f"{total_ratings} rated issues sorted by rating\n{median_observation}",
        numerator=f"{median_observation}",
        denominator=f"{total_ratings} rated issues",
        percentage=f"{median_rating:.2f}★",
    )

    # Paginate all rated issues (median depends on all data)
    total_pages = math.ceil(len(sorted_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = sorted_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Highlight the median observation(s)
    for issue in included_issues:
        if total_ratings % 2 == 1:
            if issue["issue_id"] == sorted_issues[median_idx]["issue_id"]:
                issue["exclusion_reason"] = "Median observation"
        else:
            if issue["issue_id"] in [sorted_issues[median_idx1]["issue_id"], sorted_issues[median_idx2]["issue_id"]]:
                issue["exclusion_reason"] = "Median observation"

    # Excluded issues (those without ratings)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason="No stored effective rating")
        for issue in creator_issues
        if issue.get("effective_rating") is None
    ]

    return CreatorMetricDrilldown(
        metric_type="median-rating",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_ratings,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
    )


async def _calculate_rated_issue_count_drilldown(
    creator_issues: list[dict], creator_key: str, page: int, page_size: int
) -> CreatorMetricDrilldown:
    """Calculate drilldown for rated issue count metric."""
    rated_issues = [issue for issue in creator_issues if issue.get("effective_rating") is not None]
    total_count = len(rated_issues)

    calculation = CreatorMetricCalculation(
        formula=f"{total_count} rated issues",
        numerator=f"{total_count} rated issues",
        denominator=None,
        percentage=None,
    )

    # Paginate rated issues
    total_pages = math.ceil(len(rated_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = rated_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (those without ratings)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason="No stored effective rating")
        for issue in creator_issues
        if issue.get("effective_rating") is None
    ]

    return CreatorMetricDrilldown(
        metric_type="rated-issue-count",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_count,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
    )


async def _calculate_five_star_rate_drilldown(
    creator_issues: list[dict], creator_key: str, page: int, page_size: int
) -> CreatorMetricDrilldown:
    """Calculate drilldown for 5★ rate metric."""
    rated_issues = [issue for issue in creator_issues if issue.get("effective_rating") is not None]
    total_ratings = len(rated_issues)
    
    if total_ratings == 0:
        calculation = CreatorMetricCalculation(
            formula="No ratings available",
            numerator="No rated issues",
            denominator=None,
            percentage="0%",
        )
        
        return CreatorMetricDrilldown(
            metric_type="five-star-rate",
            creator_key=creator_key,
            calculation=calculation,
            total_count=0,
            included_issues=[],
            excluded_issues=creator_issues,
            pagination={"page": page, "page_size": page_size, "total_pages": 0},
        )

    five_star_issues = [issue for issue in rated_issues if issue["effective_rating"] == 5.0]
    five_star_count = len(five_star_issues)
    five_star_rate = five_star_count / total_ratings * 100

    calculation = CreatorMetricCalculation(
        formula=f"{five_star_count} five-star ratings ÷ {total_ratings} rated issues = {five_star_rate:.1f}%",
        numerator=f"{five_star_count} five-star ratings",
        denominator=f"{total_ratings} rated issues",
        percentage=f"{five_star_rate:.1f}%",
    )

    # Paginate 5★ issues
    total_pages = math.ceil(len(five_star_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = five_star_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (non-5★ ratings)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason=f"Rated {issue['effective_rating']}★, not 5★")
        for issue in rated_issues
        if issue["effective_rating"] != 5.0
    ]

    return CreatorMetricDrilldown(
        metric_type="five-star-rate",
        creator_key=creator_key,
        calculation=calculation,
        total_count=five_star_count,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
    )


async def _calculate_rating_distribution_drilldown(
    creator_issues: list[dict], creator_key: str, rating_value: str, page: int, page_size: int
) -> CreatorRatingDistributionDrilldown:
    """Calculate drilldown for rating distribution bucket."""
    rated_issues = [issue for issue in creator_issues if issue.get("effective_rating") is not None]
    total_ratings = len(rated_issues)
    
    # Parse rating value (e.g., "5.0", "4.5")
    try:
        target_rating = float(rating_value)
    except ValueError as err:
        raise ValueError(f"Invalid rating value: {rating_value}") from err

    # Filter issues with the specific rating
    bucket_issues = [issue for issue in rated_issues if issue["effective_rating"] == target_rating]
    bucket_count = len(bucket_issues)
    bucket_percentage = (bucket_count / total_ratings * 100) if total_ratings > 0 else 0

    calculation = CreatorMetricCalculation(
        formula=f"{bucket_count} of {total_ratings} rated issues are exactly {rating_value}★ = {bucket_percentage:.1f}%",
        numerator=f"{bucket_count} issues with {rating_value}★ rating",
        denominator=f"{total_ratings} rated issues",
        percentage=f"{bucket_percentage:.1f}%",
    )

    # Paginate bucket issues
    total_pages = math.ceil(len(bucket_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = bucket_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (other ratings)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason=f"Rated {issue['effective_rating']}★, not {rating_value}★")
        for issue in rated_issues
        if issue["effective_rating"] != target_rating
    ]

    drilldown = CreatorRatingDistributionDrilldown(
        metric_type="rating-distribution",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_ratings,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
        rating_value=rating_value,
        bucket_count=bucket_count,
        bucket_percentage=bucket_percentage,
    )

    return drilldown


async def _calculate_unread_count_drilldown(
    creator_issues: list[dict], creator_key: str, page: int, page_size: int
) -> CreatorMetricDrilldown:
    """Calculate drilldown for unread count metric."""
    unread_issues = [issue for issue in creator_issues if issue.get("status") == "unread"]
    total_count = len(unread_issues)

    calculation = CreatorMetricCalculation(
        formula=f"{total_count} unread issues attributed to this creator",
        numerator=f"{total_count} unread issues",
        denominator=None,
        percentage=None,
    )

    # Paginate unread issues
    total_pages = math.ceil(len(unread_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = unread_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (read issues)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason="Issue is marked as read")
        for issue in creator_issues
        if issue.get("status") == "read"
    ]

    return CreatorMetricDrilldown(
        metric_type="unread-count",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_count,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
    )


async def _calculate_read_unrated_count_drilldown(
    creator_issues: list[dict], creator_key: str, page: int, page_size: int
) -> CreatorMetricDrilldown:
    """Calculate drilldown for read with no stored rating count metric."""
    # Filter read issues without ratings
    read_unrated_issues = [
        issue for issue in creator_issues 
        if issue.get("status") == "read" and issue.get("effective_rating") is None
    ]
    total_count = len(read_unrated_issues)

    calculation = CreatorMetricCalculation(
        formula=f"{total_count} attributed issues are marked read and have no effective rate event",
        numerator=f"{total_count} read issues without ratings",
        denominator=None,
        percentage=None,
    )

    # Paginate read unrated issues
    total_pages = math.ceil(len(read_unrated_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = read_unrated_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue, exclusion_reason="Read but has no effective rating")
        for issue in paginated_issues
    ]

    # Excluded issues (either unread or rated)
    excluded_issues = []
    for issue in creator_issues:
        if issue.get("status") == "unread":
            excluded_issues.append(
                _create_metric_issue(issue, exclusion_reason="Issue is unread")
            )
        elif issue.get("effective_rating") is not None:
            excluded_issues.append(
                _create_metric_issue(issue, exclusion_reason="Issue has an effective rating")
            )

    return CreatorMetricDrilldown(
        metric_type="read-unrated-count",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_count,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
    )


async def _calculate_role_stats_drilldown(
    creator_issues: list[dict], creator_key: str, role: str, page: int, page_size: int
) -> CreatorRoleDrilldown:
    """Calculate drilldown for role statistics metric."""
    # Filter issues where the creator has the specified role
    role_issues = [
        issue for issue in creator_issues 
        if role in issue.get("creator_roles", [])
    ]
    total_issues = len(role_issues)
    
    # Filter rated issues for the role
    role_rated_issues = [
        issue for issue in role_issues 
        if issue.get("effective_rating") is not None
    ]
    rated_count = len(role_rated_issues)
    
    # Calculate average rating for the role
    if rated_count > 0:
        total_rating_points = sum(issue["effective_rating"] for issue in role_rated_issues)
        average_rating = total_rating_points / rated_count
    else:
        average_rating = None

    calculation = CreatorMetricCalculation(
        formula=(
            f"{role}\n"
            f"{total_issues} credited issues\n"
            f"{rated_count} with effective ratings\n"
            f"{total_rating_points if rated_count > 0 else 0} rating points ÷ {rated_count} = {average_rating:.2f}★" if rated_count > 0
            else f"{role}\n{total_issues} credited issues\n{rated_count} with effective ratings\nNo rating data available"
        ),
        numerator=f"{rated_count} rated issues" if rated_count > 0 else "No rated issues",
        denominator=f"{total_issues} total issues",
        percentage=f"{average_rating:.2f}★" if average_rating is not None else "No rating",
    )

    # Paginate role issues
    total_pages = math.ceil(len(role_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = role_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (creator doesn't have this role)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason=f"Creator not credited as {role} on this issue")
        for issue in creator_issues
        if role not in issue.get("creator_roles", [])
    ]

    drilldown = CreatorRoleDrilldown(
        metric_type="role-stats",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_issues,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
        role=role,
        role_issue_count=total_issues,
        role_rated_issue_count=rated_count,
        role_average_rating=average_rating,
    )

    return drilldown


async def _calculate_series_stats_drilldown(
    creator_issues: list[dict], creator_key: str, series_key: str, page: int, page_size: int
) -> CreatorSeriesDrilldown:
    """Calculate drilldown for series statistics metric."""
    # Extract thread ID from series key (e.g., "thread:123" -> 123)
    try:
        if not series_key.startswith("thread:"):
            raise ValueError(f"Invalid series key format: {series_key}")
        thread_id = int(series_key.split(":")[1])
    except (ValueError, IndexError) as err:
        raise ValueError(f"Invalid series key: {series_key}") from err

    # Filter issues for this specific series/thread
    series_issues = [
        issue for issue in creator_issues 
        if issue.get("thread_id") == thread_id
    ]
    total_issues = len(series_issues)
    
    # Filter rated issues for the series
    series_rated_issues = [
        issue for issue in series_issues 
        if issue.get("effective_rating") is not None
    ]
    rated_count = len(series_rated_issues)
    
    # Calculate average rating for the series
    if rated_count > 0:
        total_rating_points = sum(issue["effective_rating"] for issue in series_rated_issues)
        average_rating = total_rating_points / rated_count
    else:
        average_rating = None

    # Get series title
    series_title = next(
        (issue.get("thread_title") for issue in series_issues if issue.get("thread_title")), 
        "Unknown Series"
    )

    calculation = CreatorMetricCalculation(
        formula=(
            f"{series_title}\n"
            f"{total_issues} attributed issues\n"
            f"{rated_count} with effective ratings\n"
            f"{total_rating_points if rated_count > 0 else 0} rating points ÷ {rated_count} = {average_rating:.2f}★" if rated_count > 0
            else f"{series_title}\n{total_issues} attributed issues\n{rated_count} with effective ratings\nNo rating data available"
        ),
        numerator=f"{rated_count} rated issues" if rated_count > 0 else "No rated issues",
        denominator=f"{total_issues} total issues",
        percentage=f"{average_rating:.2f}★" if average_rating is not None else "No rating",
    )

    # Paginate series issues
    total_pages = math.ceil(len(series_issues) / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_issues = series_issues[start_idx:end_idx]

    included_issues = [
        _create_metric_issue(issue) for issue in paginated_issues
    ]

    # Excluded issues (not part of this series)
    excluded_issues = [
        _create_metric_issue(issue, exclusion_reason=f"Issue not part of {series_title}")
        for issue in creator_issues
        if issue.get("thread_id") != thread_id
    ]

    drilldown = CreatorSeriesDrilldown(
        metric_type="series-stats",
        creator_key=creator_key,
        calculation=calculation,
        total_count=total_issues,
        included_issues=included_issues,
        excluded_issues=excluded_issues,
        pagination={
            "page": page,
            "page_size": page_size,
            "next_page_token": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
        },
        series_id=thread_id,
        series_title=series_title,
        series_issue_count=total_issues,
        series_rated_issue_count=rated_count,
        series_average_rating=average_rating,
    )

    return drilldown


def _create_metric_issue(issue_data: dict, exclusion_reason: str | None = None) -> CreatorMetricIssue:
    """Create a CreatorMetricIssue from issue data."""
    return CreatorMetricIssue(
        issue_id=issue_data["issue_id"],
        thread_id=issue_data["thread_id"],
        thread_title=issue_data.get("thread_title", "Unknown Thread"),
        issue_number=issue_data.get("issue_number", "Unknown"),
        status=issue_data.get("status", "unknown"),
        effective_rating=issue_data.get("effective_rating"),
        effective_rating_source=issue_data.get("effective_rating_source"),
        effective_rating_timestamp=issue_data.get("effective_rating_timestamp"),
        creator_roles=issue_data.get("creator_roles", []),
        exclusion_reason=exclusion_reason,
    )