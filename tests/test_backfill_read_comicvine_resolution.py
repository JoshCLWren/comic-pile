"""Focused regression tests for conservative read-issue ComicVine resolution.

These cover the issue #2856 contract for ``scripts/backfill_read_comicvine.py``:
exact title/year search hints, exact issue-label matching across several
candidate volumes, unusual labels that only exact provider evidence may prove,
and the rule that ambiguity never silently creates an identity.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/backfill_read_comicvine.py"


def _module() -> ModuleType:
    """Import the operator CLI without treating ``scripts/`` as a package."""
    module_name = "backfill_read_comicvine"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _issue(cli: ModuleType, **overrides: object) -> object:
    """Build one unmapped read issue with confirmed series evidence."""
    values: dict[str, object] = {
        "issue_id": 1,
        "thread_id": 1,
        "thread_title": "X-Men",
        "issue_number": "1",
        "position": 1,
        "identity_id": None,
        "external_id": None,
        "has_creator_credits": False,
        "has_person_credit_source": False,
        "creator_credit_count": 0,
        "series_identity_id": 10,
        "series_external_id": "4050-10",
        "series_volume_id": 100,
        "series_name": "X-Men",
        "sibling_volume_ids": (),
    }
    values.update(overrides)
    return cli.ReadIssue(**values)


def _roster_client(rosters: dict[int, list[dict[str, object]]]) -> AsyncMock:
    """Return a provider client stub that serves one roster per volume."""
    client = AsyncMock()
    client.fetch_volume_issues.side_effect = lambda volume_id: rosters.get(volume_id, [])
    return client


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("X-Men (1963)", ("X-Men", 1963)),
        ("X-Factor (Vol. 1) (1985 - 1998)", ("X-Factor (Vol. 1)", 1985)),
        ("Spider-Man", ("Spider-Man", None)),
        ("The Avengers (1963-present)", ("The Avengers", 1963)),
    ],
)
def test_title_search_hint_extracts_single_years_and_year_ranges(
    title: str,
    expected: tuple[str, int | None],
) -> None:
    """Year hints are parsed from both ``(1963)`` suffixes and ``(1963-1998)`` ranges."""
    cli = _module()
    assert cli._title_search_hint(title) == expected


@pytest.mark.asyncio
async def test_provider_resolution_unique_label_wins_over_ambiguous_volume() -> None:
    """One exact label match resolves even when the surrounding volumes are ambiguous."""
    cli = _module()
    client = _roster_client(
        {
            100: [
                {"id": 1001, "issue_number": "1", "volume": {"id": 100, "name": "X-Men"}},
                {"id": 1002, "issue_number": "2", "volume": {"id": 100, "name": "X-Men"}},
            ],
            101: [{"id": 2001, "issue_number": "2", "volume": {"id": 101, "name": "X-Men"}}],
        }
    )
    issue = _issue(cli, sibling_volume_ids=(101,))

    with patch.object(cli, "_persist_resolved_mapping", new_callable=AsyncMock) as persist:
        persist.return_value = (200, "1001")
        result = await cli._resolve_provider_issue(
            AsyncMock(),
            client,
            user_id=1,
            issue=issue,
            roster_cache={},
        )

    assert result == (200, "1001")
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_resolution_refuses_distinct_matches_across_candidate_volumes() -> None:
    """Two candidate volumes naming different provider issues stay unresolved."""
    cli = _module()
    client = _roster_client(
        {
            100: [{"id": 1001, "issue_number": "1", "volume": {"id": 100}}],
            101: [{"id": 2001, "issue_number": "1", "volume": {"id": 101}}],
        }
    )
    issue = _issue(cli, sibling_volume_ids=(101,))
    persist = AsyncMock()

    with patch.object(cli, "_persist_resolved_mapping", persist):
        result = await cli._resolve_provider_issue(
            AsyncMock(),
            client,
            user_id=1,
            issue=issue,
            roster_cache={},
        )

    assert result is None
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_resolution_accepts_duplicate_rosters_naming_one_issue() -> None:
    """Candidate volumes that repeat a single provider issue still prove one identity."""
    cli = _module()
    client = _roster_client(
        {
            100: [{"id": 1001, "issue_number": "1", "volume": {"id": 100}}],
            101: [{"id": 1001, "issue_number": "1", "volume": {"id": 100}}],
        }
    )
    issue = _issue(cli, sibling_volume_ids=(101,))

    with patch.object(cli, "_persist_resolved_mapping", new_callable=AsyncMock) as persist:
        persist.return_value = (200, "1001")
        result = await cli._resolve_provider_issue(
            AsyncMock(),
            client,
            user_id=1,
            issue=issue,
            roster_cache={},
        )

    assert result == (200, "1001")
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_resolution_never_searches_when_confirmed_evidence_exists() -> None:
    """Confirmed series/sibling volume evidence is preferred over a provider search."""
    cli = _module()
    client = _roster_client(
        {100: [{"id": 1001, "issue_number": "1", "volume": {"id": 100}}]},
    )
    issue = _issue(cli)

    with (
        patch.object(cli, "_persist_resolved_mapping", new_callable=AsyncMock) as persist,
        patch.object(cli, "_provider_search_volume", new_callable=AsyncMock) as search,
    ):
        persist.return_value = (200, "1001")
        result = await cli._resolve_provider_issue(
            AsyncMock(),
            client,
            user_id=1,
            issue=issue,
            roster_cache={},
        )

    assert result == (200, "1001")
    search.assert_not_awaited()


def test_unusual_labels_are_classified_and_normalized_exactly() -> None:
    """Annuals/specials are flagged while fractional labels normalize without merging."""
    cli = _module()
    assert cli._is_ambiguous_special("Annual 1") is True
    assert cli._is_ambiguous_special("Special Edition") is True
    assert cli._is_ambiguous_special("One-Shot") is True
    assert cli._is_ambiguous_special("5") is False
    assert cli._is_ambiguous_special("-1") is False
    assert cli._is_ambiguous_special(None) is False
    assert cli._normalize_issue_label(" #5 ") == "5"
    assert cli._normalize_issue_label("1/2") == "1/2"


@pytest.mark.asyncio
async def test_unusual_labels_require_exact_provider_label_evidence() -> None:
    """Unusual labels resolve only against an exactly matching provider label."""
    cli = _module()
    issue = _issue(cli, issue_number="½", series_identity_id=10, series_volume_id=100)

    miss = _roster_client({100: [{"id": 1001, "issue_number": "1", "volume": {"id": 100}}]})
    with patch.object(cli, "_persist_resolved_mapping", new_callable=AsyncMock) as persist:
        assert (
            await cli._resolve_provider_issue(
                AsyncMock(),
                miss,
                user_id=1,
                issue=issue,
                roster_cache={},
            )
            is None
        )
    persist.assert_not_awaited()

    hit = _roster_client({100: [{"id": 1001, "issue_number": "½", "volume": {"id": 100}}]})
    with patch.object(cli, "_persist_resolved_mapping", new_callable=AsyncMock) as persist:
        persist.return_value = (200, "1001")
        result = await cli._resolve_provider_issue(
            AsyncMock(),
            hit,
            user_id=1,
            issue=issue,
            roster_cache={},
        )
    assert result == (200, "1001")
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_unmapped_resolution_refuses_unusual_labels_without_numeric_proof() -> None:
    """The unmapped pass never invents an identity for annuals or negative labels."""
    cli = _module()
    client = _roster_client(
        {
            100: [
                {"id": 1001, "issue_number": "Annual 1", "volume": {"id": 100}},
                {"id": 1002, "issue_number": "-1", "volume": {"id": 100}},
            ],
        }
    )
    persist = AsyncMock()

    with patch.object(cli, "_persist_resolved_mapping", persist):
        annual = await cli._resolve_unmapped_issue(
            AsyncMock(),
            client,
            user_id=1,
            issue=_issue(cli, issue_number="Annual 1"),
        )
        negative = await cli._resolve_unmapped_issue(
            AsyncMock(),
            client,
            user_id=1,
            issue=_issue(cli, issue_number="-1"),
        )

    assert annual is None
    assert negative is None
    persist.assert_not_awaited()
