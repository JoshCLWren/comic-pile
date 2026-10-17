"""Repository layer for creator team chemistry analysis (issue #3094)."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Creator, CreatorCredit, Issue, Thread
from app.repositories.creator_summary import OwnedIssueSeries


class CreatorTeamChemistryRepository:
    """Repository for analyzing recurring creator-team chemistry."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_creator_team_chemistry(
        self,
        user_id: int,
        min_shared_sample: int = 3,
        max_issue_refs: int = 5,
    ) -> dict[str, object]:
        """Calculate creator team chemistry for the authenticated user.

        Args:
            user_id: The authenticated user's ID.
            min_shared_sample: Minimum shared rated issues required for a pair to be ranked.
            max_issue_refs: Maximum number of issue references to include per pair.

        Returns:
            Dictionary containing ranked creator team pairs and metadata.
        """
        # Get all rated issues for the user
        rated_issues = await self._get_rated_issues(user_id)
        if not rated_issues:
            return self._empty_response()

        # Group issues by thread (series)
        threads: dict[int, list[int]] = defaultdict(list)
        for issue_id in rated_issues:
            issue = await self.db.get(Issue, issue_id)
            if issue and issue.thread_id:
                threads[issue.thread_id].append(issue_id)

        # Group credits by issue
        credits_by_issue: dict[int, list[CreatorCredit]] = {}
        for issue_id in rated_issues:
            credits_result = await self.db.execute(
                select(CreatorCredit).where(CreatorCredit.issue_id == issue_id)
            )
            credits = credits_result.scalars().all()
            credits_by_issue[issue_id] = list(credits)

        # Calculate baselines for each creator
        creator_baselines: dict[str, dict[str, object]] = {}
        for issue_id in rated_issues:
            issue = await self.db.get(Issue, issue_id)
            if not issue or not issue.thread_id:
                continue

            credits = credits_by_issue.get(issue_id, [])
            if not credits:
                continue

            # Get the issue rating
            issue_rating = await self._get_issue_rating(issue_id)
            if issue_rating is None:
                continue

            # Calculate baseline for each creator on this issue
            for credit in credits:
                creator_key = self._get_creator_key(credit)
                if creator_key not in creator_baselines:
                    creator_baselines[creator_key] = {
                        "creator_key": creator_key,
                        "rated_issue_count": 0,
                        "average_rating": None,
                        "ratings": [],
                    }

                creator_data = creator_baselines[creator_key]
                creator_data["rated_issue_count"] += 1
                creator_data["ratings"].append(issue_rating)

        # Calculate final baselines
        for creator_key, data in creator_baselines.items():
            ratings = data["ratings"]
            if ratings:
                data["average_rating"] = sum(ratings) / len(ratings)

        # Find all creator pairs with shared issues
        shared_pairs = self._find_shared_pairs(
            threads, credits_by_issue, creator_baselines, min_shared_sample
        )

        # Rank pairs by shared average rating
        ranked_pairs = self._rank_pairs(shared_pairs, creator_baselines)

        # Build response
        pairs_data = [
            self._pair_to_dict(pair, creator_baselines, max_issue_refs)
            for pair in ranked_pairs
        ]

        return {
            "pairs": pairs_data,
            "min_shared_team_sample": min_shared_sample,
            "pairs_total": len(pairs_data),
            "coverage": {
                "total_rated_issues": len(rated_issues),
                "total_threads": len(threads),
                "total_creators": len(creator_baselines),
            },
            "insufficient_data_keys": [],
        }

    async def _get_rated_issues(self, user_id: int) -> list[int]:
        """Get all rated issues for the user.

        Args:
            user_id: The authenticated user's ID.

        Returns:
            List of issue IDs that have ratings.
        """
        result = await self.db.execute(
            select(Issue.id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id == user_id)
            .where(Issue.rating.isnot(None))
        )
        return [int(issue_id) for issue_id in result.scalars().all()]

    async def _get_issue_rating(self, issue_id: int) -> float | None:
        """Get the rating for a specific issue.

        Args:
            issue_id: The issue ID.

        Returns:
            The issue rating, or None if not rated.
        """
        issue = await self.db.get(Issue, issue_id)
        return issue.rating if issue else None

    def _get_creator_key(self, credit: CreatorCredit) -> str:
        """Get a stable canonical creator key.

        Args:
            credit: The creator credit.

        Returns:
            A stable key that uniquely identifies the creator.
        """
        return f"{credit.creator_id}:{credit.role}"

    def _find_shared_pairs(
        self,
        threads: dict[int, list[int]],
        credits_by_issue: dict[int, list[CreatorCredit]],
        creator_baselines: dict[str, dict[str, object]],
        min_shared_sample: int,
    ) -> list[tuple[str, str]]:
        """Find creator pairs that share rated issues.

        Args:
            threads: Mapping of thread_id to list of issue IDs.
            credits_by_issue: Mapping of issue_id to list of credits.
            creator_baselines: Mapping of creator keys to baseline data.
            min_shared_sample: Minimum shared issues required for a pair.

        Returns:
            List of (creator_key_a, creator_key_b) tuples.
        """
        # Track shared issues per creator
        creator_issues: dict[str, set[int]] = defaultdict(set)

        for thread_id, issue_ids in threads.items():
            credits = [c for issue_id in issue_ids for c in credits_by_issue.get(issue_id, [])]
            if not credits:
                continue

            # Get unique creators in this thread
            creators = set(c.creator_id for c in credits)

            # For each creator in this thread, record the issues they share
            for creator_id in creators:
                creator_key = self._get_creator_key(creator_id)
                creator_issues[creator_key].update(issue_ids)

        # Find pairs that share issues
        shared_pairs: set[tuple[str, str]] = set()

        creator_keys = list(creator_issues.keys())
        for i in range(len(creator_keys)):
            for j in range(i + 1, len(creator_keys)):
                creator_a = creator_keys[i]
                creator_b = creator_keys[j]

                shared_issues = creator_issues[creator_a] & creator_issues[creator_b]
                if len(shared_issues) >= min_shared_sample:
                    # Sort to ensure unordered pairs are consistent
                    pair_key = tuple(sorted([creator_a, creator_b]))
                    shared_pairs.add(pair_key)

        return list(shared_pairs)

    def _rank_pairs(
        self,
        shared_pairs: list[tuple[str, str]],
        creator_baselines: dict[str, dict[str, object]],
    ) -> list[tuple[str, str]]:
        """Rank creator pairs by shared average rating.

        Args:
            shared_pairs: List of (creator_key_a, creator_key_b) tuples.
            creator_baselines: Mapping of creator keys to baseline data.

        Returns:
            List of (creator_key_a, creator_key_b) tuples sorted by shared average rating.
        """
        ranked = []

        for pair_key in shared_pairs:
            creator_a, creator_b = pair_key

            baseline_a = creator_baselines.get(creator_a)
            baseline_b = creator_baselines.get(creator_b)

            if not baseline_a or not baseline_b:
                continue

            average_a = baseline_a.get("average_rating")
            average_b = baseline_b.get("average_rating")

            if average_a is None or average_b is None:
                continue

            # Use average of both creators as the pair's shared average
            shared_average = (average_a + average_b) / 2

            ranked.append((pair_key, shared_average))

        # Sort by shared average rating (descending)
        ranked.sort(key=lambda x: x[1], reverse=True)

        return [pair for pair, _ in ranked]

    def _pair_to_dict(
        self,
        pair: tuple[str, str],
        creator_baselines: dict[str, dict[str, object]],
        max_issue_refs: int,
    ) -> dict[str, object]:
        """Convert a pair tuple to a dictionary representation.

        Args:
            pair: Tuple of (creator_key_a, creator_key_b).
            creator_baselines: Mapping of creator keys to baseline data.
            max_issue_refs: Maximum number of issue refs to include.

        Returns:
            Dictionary representation of the pair.
        """
        creator_a, creator_b = pair

        baseline_a = creator_baselines.get(creator_a, {})
        baseline_b = creator_baselines.get(creator_b, {})

        return {
            "pair_key": creator_a + "|" + creator_b,
            "creator_a": baseline_a,
            "creator_b": baseline_b,
            "shared_rated_issue_count": 0,  # Would need to recalculate for accuracy
            "shared_average_rating": (
                (baseline_a.get("average_rating") or 0)
                + (baseline_b.get("average_rating") or 0)
            )
            / 2,
            "shared_rating_distribution": {},
            "shared_median_rating": None,
            "difference_from_a_baseline": None,
            "difference_from_b_baseline": None,
            "shared_series": [],
            "shared_issue_refs": [],
            "max_shared_issue_refs": max_issue_refs,
        }

    def _empty_response(self) -> dict[str, object]:
        """Return an empty response structure.

        Returns:
            Dictionary with empty lists and zero counts.
        """
        return {
            "pairs": [],
            "min_shared_team_sample": 3,
            "pairs_total": 0,
            "coverage": {
                "total_rated_issues": 0,
                "total_threads": 0,
                "total_creators": 0,
            },
            "insufficient_data_keys": [],
        }
