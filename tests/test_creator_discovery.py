"""Unit tests for creator discovery calculations (issue #3093).

Pure-Python: constructs :class:`CreatorSummaryInputs` directly, so no database
is required. Covers the acceptance criteria: thresholds, ties, insufficient
data, partial metadata coverage, and deterministic ordering across every
discovery mode.
"""

from app.repositories.creator_summary import CreatorCredit, CreatorSummaryInputs
from app.services.creator_discovery import DiscoveryCalculator

HEADLINE = ("writer",)


def _inputs(credit_map, ratings, owned):
    """Build discovery inputs from plain collections.

    ``credit_map``: issue_id -> [(creator_id, roles, display_name), ...]
    ``ratings``: issue_id -> rating
    ``owned``: issue_id -> "read" | "unread"
    """
    issue_creator_credits = {
        issue_id: tuple(
            CreatorCredit(external_id=cid, roles=roles, display_name=name)
            for cid, roles, name in creds
        )
        for issue_id, creds in credit_map.items()
    }
    return CreatorSummaryInputs(
        owned_issues=dict(owned),
        owned_issue_series={},
        issue_creator_credits=issue_creator_credits,
        issues_with_creator_metadata=frozenset(credit_map),
        effective_ratings=dict(ratings),
    )


def _keys(items):
    return [item.canonical_creator_key for item in items]


def test_consistently_loved_requires_min_sample_and_consistency():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Consistent One")],
                2: [(1, HEADLINE, "Consistent One")],
                3: [(1, HEADLINE, "Consistent One")],
                4: [(1, HEADLINE, "Consistent One")],
                5: [(1, HEADLINE, "Consistent One")],
                6: [(2, HEADLINE, "Inconsistent Two")],
                7: [(2, HEADLINE, "Inconsistent Two")],
                8: [(2, HEADLINE, "Inconsistent Two")],
                9: [(2, HEADLINE, "Inconsistent Two")],
                10: [(2, HEADLINE, "Inconsistent Two")],
                11: [(3, HEADLINE, "Low Average Three")],
                12: [(3, HEADLINE, "Low Average Three")],
                13: [(3, HEADLINE, "Low Average Three")],
                14: [(3, HEADLINE, "Low Average Three")],
                15: [(3, HEADLINE, "Low Average Three")],
            },
            {
                1: 5.0,
                2: 5.0,
                3: 5.0,
                4: 4.0,
                5: 5.0,
                6: 5.0,
                7: 5.0,
                8: 5.0,
                9: 5.0,
                10: 1.0,
                11: 3.0,
                12: 3.0,
                13: 3.0,
                14: 3.0,
                15: 3.0,
            },
            {1: "read", 2: "read", 3: "read", 4: "read", 5: "read"},
        )
    )
    items = calc.discover_consistently_loved()
    assert _keys(items) == ["creator:1"]
    item = items[0]
    assert item.average_rating == 4.8
    assert item.ratings_count == 5
    assert item.qualifying_metrics["sample_size"] == 5


def test_consistently_loved_excludes_below_min_sample():
    calc = DiscoveryCalculator(
        _inputs(
            {1: [(1, HEADLINE, "One")], 2: [(1, HEADLINE, "One")]},
            {1: 5.0, 2: 5.0},
            {1: "read", 2: "read"},
        )
    )
    assert calc.discover_consistently_loved() == []


def test_polarizing_requires_min_sample_and_range():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Polar One")],
                2: [(1, HEADLINE, "Polar One")],
                3: [(1, HEADLINE, "Polar One")],
                4: [(1, HEADLINE, "Polar One")],
                5: [(1, HEADLINE, "Polar One")],
                6: [(2, HEADLINE, "Narrow Two")],
                7: [(2, HEADLINE, "Narrow Two")],
                8: [(2, HEADLINE, "Narrow Two")],
                9: [(2, HEADLINE, "Narrow Two")],
                10: [(2, HEADLINE, "Narrow Two")],
                11: [(3, HEADLINE, "Too Few Three")],
                12: [(3, HEADLINE, "Too Few Three")],
                13: [(3, HEADLINE, "Too Few Three")],
                14: [(3, HEADLINE, "Too Few Three")],
            },
            {
                1: 5.0,
                2: 1.0,
                3: 5.0,
                4: 1.0,
                5: 5.0,
                6: 3.0,
                7: 3.0,
                8: 3.0,
                9: 3.0,
                10: 3.0,
                11: 5.0,
                12: 5.0,
                13: 5.0,
                14: 5.0,
            },
            {1: "read", 2: "read", 3: "read", 4: "read", 5: "read"},
        )
    )
    items = calc.discover_polarizing()
    assert _keys(items) == ["creator:1"]
    assert items[0].qualifying_metrics["rating_range"] == 4.0


def test_most_read_sorted_by_sample_then_average():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Most One")],
                2: [(1, HEADLINE, "Most One")],
                3: [(2, HEADLINE, "Most Two")],
                4: [(2, HEADLINE, "Most Two")],
                5: [(2, HEADLINE, "Most Two")],
                6: [(3, HEADLINE, "Most Three")],
            },
            {1: 5.0, 2: 4.0, 3: 3.0, 4: 3.0, 5: 3.0, 6: 5.0},
            {1: "read", 2: "read", 3: "read", 4: "read", 5: "read", 6: "read"},
        )
    )
    items = calc.discover_most_read()
    assert _keys(items) == ["creator:2", "creator:1", "creator:3"]
    assert items[0].ratings_count == 3
    assert items[1].ratings_count == 2


def test_highest_top_rating_rate_threshold():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Top One")],
                2: [(1, HEADLINE, "Top One")],
                3: [(1, HEADLINE, "Top One")],
                4: [(2, HEADLINE, "Top Two")],
                5: [(2, HEADLINE, "Top Two")],
                6: [(2, HEADLINE, "Top Two")],
                7: [(3, HEADLINE, "Too Few Three")],
                8: [(3, HEADLINE, "Too Few Three")],
            },
            {1: 5.0, 2: 5.0, 3: 2.0, 4: 5.0, 5: 2.0, 6: 2.0, 7: 5.0, 8: 5.0},
            {1: "read", 2: "read", 3: "read", 4: "read", 5: "read", 6: "read", 7: "read", 8: "read"},
        )
    )
    items = calc.discover_highest_top_rating_rate()
    assert _keys(items) == ["creator:1"]
    assert items[0].qualifying_metrics["top_rating_rate"] == 66.7


def test_great_average_small_sample_bounds():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Small One")],
                2: [(1, HEADLINE, "Small One")],
                3: [(2, HEADLINE, "Big Two")],
                4: [(2, HEADLINE, "Big Two")],
                5: [(2, HEADLINE, "Big Two")],
                6: [(2, HEADLINE, "Big Two")],
                7: [(2, HEADLINE, "Big Two")],
                8: [(2, HEADLINE, "Big Two")],
                9: [(3, HEADLINE, "Low Three")],
                10: [(3, HEADLINE, "Low Three")],
            },
            {1: 5.0, 2: 5.0, 3: 4.0, 4: 4.0, 5: 4.0, 6: 4.0, 7: 4.0, 8: 4.0, 9: 3.0, 10: 3.0},
            {1: "read", 2: "read", 3: "read", 4: "read", 5: "read", 6: "read", 7: "read", 8: "read", 9: "read", 10: "read"},
        )
    )
    items = calc.discover_great_average_small_sample()
    # creator 1: 2 ratings avg 5.0 (in range 2..5, avg >= 4.0) -> included
    # creator 2: 6 ratings > max_sample 5 -> excluded
    # creator 3: avg 3.0 < min_avg 4.0 -> excluded
    assert _keys(items) == ["creator:1"]


def test_loved_with_unread_requires_avg_and_unread():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Loved One")],
                2: [(1, HEADLINE, "Loved One")],
                3: [(2, HEADLINE, "No Unread Two")],
                4: [(2, HEADLINE, "No Unread Two")],
                5: [(2, HEADLINE, "No Unread Two")],
                6: [(3, HEADLINE, "Low Avg Three")],
                7: [(3, HEADLINE, "Low Avg Three")],
                8: [(3, HEADLINE, "Low Avg Three")],
            },
            {1: 5.0, 2: 5.0, 3: 5.0, 4: 5.0, 5: 5.0, 6: 3.0, 7: 3.0, 8: 3.0},
            {
                1: "read",
                2: "unread",
                3: "read",
                4: "read",
                5: "read",
                6: "unread",
                7: "unread",
                8: "unread",
            },
        )
    )
    items = calc.discover_loved_with_unread()
    assert _keys(items) == ["creator:1"]
    assert items[0].upcoming_count == 1


def test_loved_with_unread_partial_coverage_counts_read_unrated():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Partial One")],
                2: [(1, HEADLINE, "Partial One")],
                3: [(1, HEADLINE, "Partial One")],
            },
            {1: 5.0, 2: 4.0},
            {1: "read", 2: "read", 3: "unread"},
        )
    )
    items = calc.discover_loved_with_unread()
    assert _keys(items) == ["creator:1"]
    item = items[0]
    # issue 3 is unread -> upcoming_count 1; issue 2 read but unrated -> read_unrated_count 1
    assert item.upcoming_count == 1
    assert item.read_unrated_count == 1


def test_ties_break_deterministically_by_secondary_metric():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, HEADLINE, "Tie One")],
                2: [(1, HEADLINE, "Tie One")],
                3: [(1, HEADLINE, "Tie One")],
                4: [(1, HEADLINE, "Tie One")],
                5: [(1, HEADLINE, "Tie One")],
                6: [(2, HEADLINE, "Tie Two")],
                7: [(2, HEADLINE, "Tie Two")],
                8: [(2, HEADLINE, "Tie Two")],
                9: [(2, HEADLINE, "Tie Two")],
                10: [(2, HEADLINE, "Tie Two")],
            },
            {
                1: 5.0,
                2: 4.0,
                3: 4.0,
                4: 4.0,
                5: 3.0,
                6: 4.0,
                7: 4.0,
                8: 4.0,
                9: 4.0,
                10: 4.0,
            },
            {i: "read" for i in range(1, 11)},
        )
    )
    items = calc.discover_consistently_loved()
    # Same average 4.0 for both; creator 2 is fully consistent (stddev 0)
    # ranks above creator 1 (stddev ~0.63) on the consistency tie-break.
    assert _keys(items) == ["creator:2", "creator:1"]


def test_empty_inputs_yield_no_results():
    calc = DiscoveryCalculator(
        CreatorSummaryInputs(
            owned_issues={},
            owned_issue_series={},
            issue_creator_credits={},
            issues_with_creator_metadata=frozenset(),
            effective_ratings={},
        )
    )
    assert calc.discover_consistently_loved() == []
    assert calc.discover_polarizing() == []
    assert calc.discover_most_read() == []
    assert calc.discover_highest_top_rating_rate() == []
    assert calc.discover_great_average_small_sample() == []
    assert calc.discover_loved_with_unread() == []


def test_non_headline_credits_do_not_contribute_ratings():
    calc = DiscoveryCalculator(
        _inputs(
            {
                1: [(1, ("cover",), "Cover Only One")],
                2: [(1, ("cover",), "Cover Only One")],
            },
            {1: 5.0, 2: 5.0},
            {1: "read", 2: "read"},
        )
    )
    assert calc.discover_consistently_loved() == []
    assert calc.discover_most_read() == []
