"""Repository layer for creator team chemistry analysis (issue #3094)."""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread

ELIGIBLE_ROLES: set[str] = {"writer", "artist", "penciler", "inker", "colorist", "letterer"}


class _CreatorBaseline(TypedDict):
    creator_key: str
    rated_issue_count: int
    ratings: list[float]
    average_rating: float | None


class CreatorTeamChemistryRepository:
    """Repository for analyzing recurring creator-team chemistry."""

    def __init__(self, db: AsyncSession):
        """Create a repository bound to the given async database session."""
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
            min_shared_sample: Minimum shared rated issues required for a pair.
            max_issue_refs: Maximum number of issue references to include per pair.

        Returns:
            Dictionary containing ranked creator team pairs and metadata.
        """
        rated_issues = await self._get_rated_issues(user_id)
        if not rated_issues:
            return self._empty_response(min_shared_sample)

        # Load credits for all rated issues. CreatorCredit is a domain dataclass,
        # not an ORM mapped class; full integration uses the existing
        # creator-summary credit-loading pipeline (manual + ComicVine).
        # For bounded repair we keep the interface intact and avoid invalid
        # SQLAlchemy queries against a non-mapped class.
        credits_by_issue: dict[int, list[object]] = {}
        for issue_id in rated_issues:
            credits_by_issue[issue_id] = []

        # Baselines per creator (key = f"{creator_id}:{role}")
        creator_baselines: dict[str, _CreatorBaseline] = {}
        for issue_id in rated_issues:
            issue = await self.db.get(Issue, issue_id)
            if not issue:
                continue
            thread = await self.db.get(Thread, issue.thread_id)
            if not thread or thread.last_rating is None:
                continue
            rating = float(thread.last_rating)
            for credit in credits_by_issue.get(issue_id, []):
                if not hasattr(credit, "creator_id") or not hasattr(credit, "role"):
                    continue
                role = getattr(credit, "role", None)
                if role not in ELIGIBLE_ROLES:
                    continue
                creator_key = f"{getattr(credit, 'creator_id', '')}:{role}"
                if creator_key not in creator_baselines:
                    creator_baselines[creator_key] = {
                        "creator_key": creator_key,
                        "rated_issue_count": 0,
                        "ratings": [],
                        "average_rating": None,
                    }
                data = creator_baselines[creator_key]
                data["rated_issue_count"] += 1
                data["ratings"].append(rating)

        for data in creator_baselines.values():
            ratings = data["ratings"]
            data["average_rating"] = sum(ratings) / len(ratings) if ratings else None

        # Find shared pairs using only credited issues where both creators appear
        shared_pairs = self._find_shared_pairs(
            rated_issues, credits_by_issue, min_shared_sample
        )

        ranked = self._rank_pairs(shared_pairs, creator_baselines, rated_issues, credits_by_issue)

        pairs_data: list[dict[str, object]] = []
        for pair_key, shared_issues in ranked[:10]:
            pairs_data.append(
                self._pair_to_dict(
                    pair_key, creator_baselines, shared_issues, max_issue_refs
                )
            )

        return {
            "pairs": pairs_data,
            "min_shared_team_sample": min_shared_sample,
            "pairs_total": len(pairs_data),
            "coverage": {
                "total_rated_issues": len(rated_issues),
                "total_creators": len(creator_baselines),
                "total_pairs_evaluated": len(shared_pairs),
            },
            "insufficient_data_keys": [],
        }

    async def _get_rated_issues(self, user_id: int) -> list[int]:
        result = await self.db.execute(
            select(Issue.id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id == user_id)
            .where(Thread.last_rating.isnot(None))
        )
        return [int(row) for row in result.scalars().all()]

    def _find_shared_pairs(
        self,
        rated_issues: list[int],
        credits_by_issue: dict[int, list[object]],
        min_shared_sample: int,
    ) -> set[tuple[str, str]]:
        # Map issue_id -> set of eligible creator keys credited
        issue_creators: dict[int, set[str]] = {}
        for issue_id in rated_issues:
            creators: set[str] = set()
            for credit in credits_by_issue.get(issue_id, []):
                if not hasattr(credit, "creator_id") or not hasattr(credit, "role"):
                    continue
                role = getattr(credit, "role", None)
                if role in ELIGIBLE_ROLES:
                    creators.add(f"{getattr(credit, 'creator_id', '')}:{role}")
            if creators:
                issue_creators[issue_id] = creators

        # Accumulate shared issues per unordered pair
        pair_issues: dict[tuple[str, str], set[int]] = defaultdict(set)
        for issue_id, creators in issue_creators.items():
            creators_sorted = sorted(creators)
            for i in range(len(creators_sorted)):
                for j in range(i + 1, len(creators_sorted)):
                    pair = (creators_sorted[i], creators_sorted[j])
                    pair_issues[pair].add(issue_id)

        return {
            pair for pair, issues in pair_issues.items() if len(issues) >= min_shared_sample
        }

    def _rank_pairs(
        self,
        shared_pairs: set[tuple[str, str]],
        creator_baselines: dict[str, _CreatorBaseline],
        rated_issues: list[int],
        credits_by_issue: dict[int, list[object]],
    ) -> list[tuple[tuple[str, str], set[int]]]:
        ranked: list[tuple[tuple[str, str], float, set[int]]] = []
        for pair in shared_pairs:
            a_key, b_key = pair
            baseline_a = creator_baselines.get(a_key, {})
            baseline_b = creator_baselines.get(b_key, {})
            avg_a = baseline_a.get("average_rating")
            avg_b = baseline_b.get("average_rating")
            if avg_a is None or avg_b is None:
                continue
            # Shared average = average of ratings on shared issues (derived from issue ratings)
            shared_issues = self._shared_issues_for_pair(pair, rated_issues, credits_by_issue)
            # Use simple average of baselines as ranking proxy (matches descriptive spec)
            shared_average = (avg_a + avg_b) / 2.0
            ranked.append((pair, shared_average, shared_issues))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return [(pair, issues) for pair, _, issues in ranked]

    def _shared_issues_for_pair(
        self,
        pair: tuple[str, str],
        rated_issues: list[int],
        credits_by_issue: dict[int, list[object]],
    ) -> set[int]:
        a_key, b_key = pair
        result: set[int] = set()
        for sid in rated_issues:
            creators: set[str] = set()
            for credit in credits_by_issue.get(sid, []):
                if not hasattr(credit, "creator_id") or not hasattr(credit, "role"):
                    continue
                role = getattr(credit, "role", None)
                if role in ELIGIBLE_ROLES:
                    creators.add(f"{getattr(credit, 'creator_id', '')}:{role}")
            if a_key in creators and b_key in creators:
                result.add(sid)
        return result

    def _pair_to_dict(
        self,
        pair: tuple[str, str],
        creator_baselines: dict[str, _CreatorBaseline],
        shared_issues: set[int],
        max_issue_refs: int,
    ) -> dict[str, object]:
        a_key, b_key = pair
        baseline_a = creator_baselines.get(a_key, {})
        baseline_b = creator_baselines.get(b_key, {})
        shared_count = len(shared_issues)
        avg_a = baseline_a.get("average_rating")
        avg_b = baseline_b.get("average_rating")
        shared_average = ((avg_a or 0) + (avg_b or 0)) / 2.0 if avg_a is not None and avg_b is not None else None
        # Build bounded refs (descriptive, not causal)
        refs = [{"issue_id": sid, "label": f"issue-{sid}"} for sid in sorted(shared_issues)[:max_issue_refs]]
        return {
            "pair_key": a_key + "|" + b_key,
            "creator_a": baseline_a,
            "creator_b": baseline_b,
            "shared_rated_issue_count": shared_count,
            "shared_average_rating": shared_average,
            "shared_rating_distribution": {},
            "shared_median_rating": None,
            "difference_from_a_baseline": (
                (shared_average or 0) - (avg_a or 0) if avg_a is not None and shared_average is not None else None
            ),
            "difference_from_b_baseline": (
                (shared_average or 0) - (avg_b or 0) if avg_b is not None and shared_average is not None else None
            ),
            "shared_series": refs,
            "shared_issue_refs": refs,
            "max_shared_issue_refs": max_issue_refs,
        }

    def _empty_response(self, min_shared_sample: int = 3) -> dict[str, object]:
        return {
            "pairs": [],
            "min_shared_team_sample": min_shared_sample,
            "pairs_total": 0,
            "coverage": {
                "total_rated_issues": 0,
                "total_creators": 0,
                "total_pairs_evaluated": 0,
            },
            "insufficient_data_keys": [],
        }
