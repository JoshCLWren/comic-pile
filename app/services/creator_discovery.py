"""Creator discovery services (issue #3093).

Discovery views surface useful patterns in user's creator ratings that they may
not think to search for manually, while keeping every result deterministic and
explainable.

Each discovery mode uses explicit, deterministic calculations with clear minimum
sample requirements to ensure statistical validity.
"""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_summary import (
    CreatorSummaryInputs,
    load_creator_summary_inputs,
)
from app.schemas.creator_discovery import (
    DiscoveryMode,
    DiscoveryResponse,
    DiscoveryResultItem,
    DiscoveryModesResponse,
)
from app.services.creator_summary import HEADLINE_ROLES


class DiscoveryCalculator:
    """Handles discovery metric calculations for different modes."""

    def __init__(self, inputs: CreatorSummaryInputs):
        """Initialize with creator summary inputs."""
        self.inputs = inputs

    def _calculate_rating_stddev(self, ratings: list[float]) -> float:
        """Calculate population standard deviation of ratings."""
        if not ratings:
            return 0.0
        mean = sum(ratings) / len(ratings)
        squared_diffs = [(r - mean) ** 2 for r in ratings]
        return math.sqrt(sum(squared_diffs) / len(ratings))

    def _calculate_top_rating_rate(self, ratings: list[float], top_rating: float = 5.0) -> float:
        """Calculate percentage of ratings that are at the top rating."""
        if not ratings:
            return 0.0
        top_count = sum(1 for r in ratings if r == top_rating)
        return round((top_count / len(ratings)) * 100, 1)

    def _get_creator_ratings(self, creator_id: int) -> list[float]:
        """Get all headline-eligible ratings for a creator."""
        issue_ids = set()
        for issue_id, credits in self.inputs.issue_creator_credits.items():
            for credit in credits:
                if credit.external_id == creator_id:
                    if any(role in HEADLINE_ROLES for role in credit.roles):
                        issue_ids.add(issue_id)
        
        return [
            self.inputs.effective_ratings[issue_id]
            for issue_id in issue_ids
            if issue_id in self.inputs.effective_ratings
        ]

    def discover_consistently_loved(
        self, min_sample: int = 5, max_stddev: float = 0.8
    ) -> list[DiscoveryResultItem]:
        """Find creators with high average and low rating dispersion.
        
        Args:
            min_sample: Minimum number of ratings required (default 5)
            max_stddev: Maximum standard deviation for consistency (default 0.8)
            
        Returns:
            Creators with high average rating and consistent ratings.
        """
        results = []
        
        for creator_id, _issue_ids in self._get_creator_issues().items():
            ratings = self._get_creator_ratings(creator_id)
            if len(ratings) < min_sample:
                continue
                
            avg_rating = sum(ratings) / len(ratings)
            if avg_rating < 4.0:  # High threshold for "loved"
                continue
                
            stddev = self._calculate_rating_stddev(ratings)
            if stddev > max_stddev:
                continue
                
            result = self._build_result_item(
                creator_id, 
                qualifying_metrics={
                    "sample_size": len(ratings),
                    "consistency_score": round((max_stddev - stddev) / max_stddev * 100, 1),
                    "stddev": round(stddev, 2),
                }
            )
            results.append(result)
        
        # Sort by average rating desc, then by consistency score desc
        results.sort(key=lambda x: (
            -(x.average_rating or 0.0),
            -float(x.qualifying_metrics.get("consistency_score", 0.0) or 0.0)
        ))
        return results

    def discover_polarizing(
        self, min_sample: int = 5, min_range: float = 2.0
    ) -> list[DiscoveryResultItem]:
        """Find creators with broad rating spread.
        
        Args:
            min_sample: Minimum number of ratings required (default 5)
            min_range: Minimum rating range for polarization (default 2.0)
            
        Returns:
            Creators with polarizing rating patterns.
        """
        results = []
        
        for creator_id, _issue_ids in self._get_creator_issues().items():
            ratings = self._get_creator_ratings(creator_id)
            if len(ratings) < min_sample:
                continue
                
            rating_range = max(ratings) - min(ratings)
            if rating_range < min_range:
                continue
                
            result = self._build_result_item(
                creator_id,
                qualifying_metrics={
                    "sample_size": len(ratings),
                    "polarization_score": round(rating_range / 4.0 * 100, 1),  # Normalize to 0-100
                    "rating_range": round(rating_range, 1),
                    "min_rating": min(ratings),
                    "max_rating": max(ratings),
                }
            )
            results.append(result)
        
        # Sort by polarization score desc, then by rating range desc
        results.sort(key=lambda x: (
            -float(x.qualifying_metrics.get("polarization_score", 0.0) or 0.0),
            -float(x.qualifying_metrics.get("rating_range", 0.0) or 0.0)
        ))
        return results

    def discover_most_read(self, min_sample: int = 1) -> list[DiscoveryResultItem]:
        """Find creators with highest rated sample counts.
        
        Args:
            min_sample: Minimum number of ratings required (default 1)
            
        Returns:
            Creators with most rated issues.
        """
        results = []
        
        for creator_id, _issue_ids in self._get_creator_issues().items():
            ratings = self._get_creator_ratings(creator_id)
            if len(ratings) < min_sample:
                continue
                
            result = self._build_result_item(
                creator_id,
                qualifying_metrics={
                    "sample_size": len(ratings),
                }
            )
            results.append(result)
        
        # Sort by sample size desc, then by average rating desc
        results.sort(key=lambda x: (
            -float(x.qualifying_metrics.get("sample_size", 0) or 0),
            -(x.average_rating or 0.0)
        ))
        return results

    def discover_highest_top_rating_rate(
        self, min_sample: int = 3, min_top_rate: float = 60.0
    ) -> list[DiscoveryResultItem]:
        """Find creators with highest percentage of top ratings.
        
        Args:
            min_sample: Minimum number of ratings required (default 3)
            min_top_rate: Minimum top rating percentage to qualify (default 60%)
            
        Returns:
            Creators with highest top rating rates.
        """
        results = []
        
        for creator_id, _issue_ids in self._get_creator_issues().items():
            ratings = self._get_creator_ratings(creator_id)
            if len(ratings) < min_sample:
                continue
                
            top_rate = self._calculate_top_rating_rate(ratings)
            if top_rate < min_top_rate:
                continue
                
            result = self._build_result_item(
                creator_id,
                qualifying_metrics={
                    "sample_size": len(ratings),
                    "top_rating_rate": top_rate,
                    "top_rating_count": sum(1 for r in ratings if r == 5.0),
                }
            )
            results.append(result)
        
        # Sort by top rate desc, then by sample size desc
        results.sort(key=lambda x: (
            -float(x.qualifying_metrics.get("top_rating_rate", 0.0) or 0.0),
            -float(x.qualifying_metrics.get("sample_size", 0) or 0)
        ))
        return results

    def discover_great_average_small_sample(
        self, min_sample: int = 2, max_sample: int = 5, min_avg: float = 4.0
    ) -> list[DiscoveryResultItem]:
        """Find promising creators with limited evidence.
        
        Args:
            min_sample: Minimum number of ratings required (default 2)
            max_sample: Maximum sample size for "small sample" (default 5)
            min_avg: Minimum average rating for "great" (default 4.0)
            
        Returns:
            Creators with great averages but limited evidence.
        """
        results = []
        
        for creator_id, _issue_ids in self._get_creator_issues().items():
            ratings = self._get_creator_ratings(creator_id)
            if len(ratings) < min_sample or len(ratings) > max_sample:
                continue
                
            avg_rating = sum(ratings) / len(ratings)
            if avg_rating < min_avg:
                continue
                
            result = self._build_result_item(
                creator_id,
                qualifying_metrics={
                    "sample_size": len(ratings),
                    "potential_score": round(avg_rating * (len(ratings) / max_sample) * 100, 1),
                }
            )
            results.append(result)
        
        # Sort by average rating desc, then by potential score desc
        results.sort(key=lambda x: (
            -(x.average_rating or 0.0),
            -float(x.qualifying_metrics.get("potential_score", 0.0) or 0.0)
        ))
        return results

    def discover_loved_with_unread(
        self, min_avg: float = 4.0, min_unread: int = 1
    ) -> list[DiscoveryResultItem]:
        """Find highly-rated creators with unread work.
        
        Args:
            min_avg: Minimum average rating for "loved" (default 4.0)
            min_unread: Minimum unread issues required (default 1)
            
        Returns:
            Creators with high ratings plus unread issues.
        """
        results = []
        
        # Build creator issue mapping including unread issues
        creator_issues = self._get_creator_issues(include_unread=True)
        
        for creator_id, issue_ids in creator_issues.items():
            ratings = self._get_creator_ratings(creator_id)
            if not ratings:
                continue
                
            avg_rating = sum(ratings) / len(ratings)
            if avg_rating < min_avg:
                continue
                
            # Count unread issues for this creator
            unread_count = 0
            for issue_id in issue_ids:
                if (issue_id in self.inputs.owned_issues and 
                    self.inputs.owned_issues[issue_id] == "unread"):
                    unread_count += 1
                    
            if unread_count < min_unread:
                continue
                
            result = self._build_result_item(
                creator_id,
                qualifying_metrics={
                    "average_rating": round(avg_rating, 2),
                    "unread_count": unread_count,
                    "read_potential": avg_rating * unread_count,
                }
            )
            results.append(result)
        
        # Sort by average rating desc, then by unread count desc
        results.sort(key=lambda x: (
            -(x.average_rating or 0.0),
            -float(x.qualifying_metrics.get("unread_count", 0) or 0)
        ))
        return results

    def _get_creator_issues(self, include_unread: bool = False) -> dict[int, set[int]]:
        """Get mapping of creator IDs to their issue IDs."""
        creator_issues: dict[int, set[int]] = defaultdict(set)
        
        for issue_id, credits in self.inputs.issue_creator_credits.items():
            for credit in credits:
                creator_issues[credit.external_id].add(issue_id)
                
        return creator_issues

    def _build_result_item(self, creator_id: int, qualifying_metrics: dict[str, float | int | str]) -> DiscoveryResultItem:
        """Build a discovery result item for a creator."""
        # Get creator basic info
        issue_ids = self._get_creator_issues()[creator_id]
        ratings = self._get_creator_ratings(creator_id)
        
        # Get creator name and roles
        display_name = ""
        normalized_roles = set()
        
        for _issue_id, credits in self.inputs.issue_creator_credits.items():
            for credit in credits:
                if credit.external_id == creator_id:
                    display_name = credit.display_name
                    normalized_roles.update(credit.roles)
        
        # Calculate basic stats
        avg_rating = sum(ratings) / len(ratings) if ratings else None
        ratings_count = len(ratings)
        
        # Get read/unread counts
        read_unrated_count = 0
        upcoming_count = 0
        
        for issue_id in issue_ids:
            if issue_id in self.inputs.owned_issues:
                status = self.inputs.owned_issues[issue_id]
                if status == "read" and issue_id not in self.inputs.effective_ratings:
                    read_unrated_count += 1
                elif status == "unread":
                    upcoming_count += 1
        
        return DiscoveryResultItem(
            canonical_creator_key=f"creator:{creator_id}",
            display_name=display_name,
            normalized_roles=sorted(normalized_roles),
            average_rating=avg_rating,
            ratings_count=ratings_count,
            qualifying_metrics=qualifying_metrics,
            read_unrated_count=read_unrated_count,
            upcoming_count=upcoming_count,
        )


async def get_discovery_modes() -> DiscoveryModesResponse:
    """Get list of available discovery modes."""
    modes = [
        {
            "mode": DiscoveryMode.CONSISTENTLY_LOVED.value,
            "title": "Most Consistently Loved",
            "description": "High average rating with consistent ratings across multiple issues",
        },
        {
            "mode": DiscoveryMode.POLARIZING.value,
            "title": "Most Polarizing", 
            "description": "Broad range of ratings - some loved, some less so",
        },
        {
            "mode": DiscoveryMode.MOST_READ.value,
            "title": "Most Read",
            "description": "Highest number of rated issues in your library",
        },
        {
            "mode": DiscoveryMode.HIGHEST_TOP_RATING_RATE.value,
            "title": "Highest Top Rating Rate",
            "description": "Highest percentage of 5-star ratings",
        },
        {
            "mode": DiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE.value,
            "title": "Great Average, Small Sample",
            "description": "Promising creators with limited but excellent ratings",
        },
        {
            "mode": DiscoveryMode.LOVED_WITH_UNREAD.value,
            "title": "Loved Creators with Unread Work",
            "description": "Highly-rated creators whose work you haven't read yet",
        },
    ]
    
    return DiscoveryModesResponse(modes=modes)


async def get_discovery(
    db: AsyncSession,
    user_id: int,
    mode: DiscoveryMode,
    limit: int = 20,
    offset: int = 0,
) -> DiscoveryResponse:
    """Get discovery results for a specific mode.
    
    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        mode: Discovery mode to use.
        limit: Page size (bounded, max 50).
        offset: Page offset.
        
    Returns:
        Discovery results for the specified mode.
    """
    # Load base creator data
    inputs = await load_creator_summary_inputs(db, user_id)
    
    # Calculate discovery results
    calculator = DiscoveryCalculator(inputs)
    
    if mode == DiscoveryMode.CONSISTENTLY_LOVED:
        items = calculator.discover_consistently_loved()
        title = "Most Consistently Loved"
        description = "Creators with high average ratings and consistent quality across multiple issues"
    elif mode == DiscoveryMode.POLARIZING:
        items = calculator.discover_polarizing()
        title = "Most Polarizing"
        description = "Creators with a wide range of ratings - some issues loved, others less so"
    elif mode == DiscoveryMode.MOST_READ:
        items = calculator.discover_most_read()
        title = "Most Read"
        description = "Creators you've rated the most issues from"
    elif mode == DiscoveryMode.HIGHEST_TOP_RATING_RATE:
        items = calculator.discover_highest_top_rating_rate()
        title = "Highest Top Rating Rate"
        description = "Creators with the highest percentage of 5-star ratings"
    elif mode == DiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE:
        items = calculator.discover_great_average_small_sample()
        title = "Great Average, Small Sample"
        description = "Promising creators where you have limited but excellent data"
    elif mode == DiscoveryMode.LOVED_WITH_UNREAD:
        items = calculator.discover_loved_with_unread()
        title = "Loved Creators with Unread Work"
        description = "Highly-rated creators whose work you haven't read yet"
    else:
        raise ValueError(f"Unknown discovery mode: {mode}")
    
    # Apply pagination
    total = len(items)
    paged_items = items[offset : offset + limit]
    
    return DiscoveryResponse(
        mode=mode,
        title=title,
        description=description,
        items=paged_items,
        total=total,
        limit=limit,
        offset=offset,
    )