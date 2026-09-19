"""Regression tests for the series-first ComicVine read-identity resolver."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/resolve_read_comicvine_series.py"


def _module() -> ModuleType:
    """Import the operator CLI without treating scripts/ as a package."""
    module_name = "resolve_read_comicvine_series"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_script_isolated_from_application_database_settings() -> None:
    """The operator must not instantiate ComicPile's global app database/config stack."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from app." not in source
    assert "import app." not in source


def test_neon_libpq_url_is_normalized_for_asyncpg() -> None:
    """The direnv Neon URL works unchanged from the user's shell."""
    cli = _module()

    normalized = cli._async_url(
        "postgresql://owner:secret@ep-prod.example.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )

    assert normalized.startswith("postgresql+asyncpg://")
    assert "ssl=require" in normalized
    assert "sslmode=" not in normalized
    assert "channel_binding=" not in normalized


def test_parse_thread_title_extracts_volume_and_start_year() -> None:
    """Imported catalog titles expose strong series-resolution hints."""
    cli = _module()

    hint = cli._parse_title_hint("X-Factor (Vol. 1) (1985 - 1998)")

    assert hint.query_title == "X-Factor"
    assert hint.volume_hint == 1
    assert hint.start_year == 1985


def test_parse_thread_title_handles_present_range_without_volume_hint() -> None:
    """Modern titles with a year range still provide an exact start-year gate."""
    cli = _module()

    hint = cli._parse_title_hint("Saga (2012 - Present)")

    assert hint.query_title == "Saga"
    assert hint.volume_hint is None
    assert hint.start_year == 2012


def test_series_title_normalization_is_not_fuzzy() -> None:
    """Normalization handles punctuation/articles without accepting different title tokens."""
    cli = _module()

    assert cli._normalize_series_title("The Uncanny X-Men") == cli._normalize_series_title(
        "Uncanny X-Men"
    )
    assert cli._normalize_series_title("WildC.A.T.s: Covert Action Teams") == (
        "wildc a t s covert action teams"
    )
    assert cli._normalize_series_title("X-Force") != cli._normalize_series_title("X-Factor")


def test_search_acceptance_requires_one_exact_title_and_start_year() -> None:
    """Search is only authoritative when normalized title and start year identify one volume."""
    cli = _module()
    hint = cli.TitleHint(query_title="X-Factor", start_year=1985, volume_hint=1)
    rows = [
        {"id": 1, "name": "X-Factor", "start_year": "1985"},
        {"id": 2, "name": "X-Factor", "start_year": "2006"},
        {"id": 3, "name": "X-Force", "start_year": "1985"},
    ]

    assert cli._unique_search_volume(rows, hint=hint) == rows[0]


def test_search_refuses_duplicate_exact_title_year_matches() -> None:
    """Provider ambiguity is preserved instead of selecting an arbitrary series."""
    cli = _module()
    hint = cli.TitleHint(query_title="Example", start_year=1994, volume_hint=1)
    rows = [
        {"id": 10, "name": "Example", "start_year": "1994"},
        {"id": 11, "name": "Example", "start_year": "1994"},
    ]

    assert cli._unique_search_volume(rows, hint=hint) is None


def test_issue_resolution_accepts_exact_special_label_when_unique() -> None:
    """Annuals and specials are safe when the provider roster has one exact label."""
    cli = _module()
    rosters = {
        100: [
            {"id": 1001, "issue_number": "1"},
            {"id": 1099, "issue_number": "Annual 2026"},
        ]
    }

    assert cli._candidate_issue_rows(rosters, "Annual 2026") == [
        (100, {"id": 1099, "issue_number": "Annual 2026"})
    ]


def test_issue_resolution_refuses_same_label_across_candidate_volumes() -> None:
    """Multi-volume threads only map a label when exactly one provider issue matches."""
    cli = _module()
    rosters = {
        100: [{"id": 1001, "issue_number": "1"}],
        200: [{"id": 2001, "issue_number": "1"}],
    }

    assert len(cli._candidate_issue_rows(rosters, "1")) == 2


def test_thread_classification_prefers_existing_evidence_over_search() -> None:
    """A unique sibling volume avoids an unnecessary ComicVine series search."""
    cli = _module()
    work = cli.ThreadWork(
        thread_id=7,
        title="X-Force (Vol. 1) (1991 - 2002)",
        sibling_volumes=[
            cli.SeriesEvidence(
                volume_id=4604,
                name="X-Force",
                start_year=None,
                source="sibling-volume",
            )
        ],
    )

    assert cli._classify_thread(work) == ("existing-volume", [4604])


def test_thread_classification_keeps_multiple_volumes_for_issue_segmentation() -> None:
    """Conflicting sibling volumes become bounded per-issue candidates, not one guessed series."""
    cli = _module()
    work = cli.ThreadWork(
        thread_id=8,
        title="Example (1990 - 1995)",
        sibling_volumes=[
            cli.SeriesEvidence(100, "Example", None, "sibling-volume"),
            cli.SeriesEvidence(200, "Example Annual", None, "sibling-volume"),
        ],
    )

    assert cli._classify_thread(work) == ("multi-volume", [100, 200])


def test_thread_classification_uses_title_year_only_without_provider_evidence() -> None:
    """Title/year search is the fallback after existing provider evidence is exhausted."""
    cli = _module()
    work = cli.ThreadWork(
        thread_id=9,
        title="Excalibur (Vol. 1) (1988 - 1998)",
    )

    assert cli._classify_thread(work) == ("title-year-search", [])
