"""Tests for the collection-level CBL expansion operator."""

from __future__ import annotations

from pathlib import Path

from app.cbl_ingest import CBLBook
from comic_pile.local_comicvine import LocalComicVineResult
from scripts.expand_collection_cbl import (
    SeriesReference,
    collection_references,
    expand_cbl,
    write_cbl,
)


class FakeSnapshot:
    """Small in-memory ComicVine snapshot for deterministic expansion tests."""

    def __init__(self) -> None:
        self.issues: dict[int, LocalComicVineResult] = {}
        self.volumes: dict[int, LocalComicVineResult] = {}
        self.volume_issues: dict[int, list[LocalComicVineResult]] = {}

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Return one fake issue."""
        return self.issues.get(issue_id)

    def get_volume(self, volume_id: int) -> LocalComicVineResult | None:
        """Return one fake volume."""
        return self.volumes.get(volume_id)

    def get_volume_issues(self, volume_id: int) -> list[LocalComicVineResult]:
        """Return fake issues for one volume."""
        return list(self.volume_issues.get(volume_id, []))


def _row(**data: object) -> LocalComicVineResult:
    return LocalComicVineResult(data=dict(data))


def _source(
    *,
    series_id: str = "9000",
    issue_id: str = "1000",
    series: str = "Collected Book",
) -> CBLBook:
    return CBLBook(
        position=1,
        series=series,
        issue_number="1",
        volume_year=2020,
        publication_year=2020,
        comicvine_series_id=series_id,
        comicvine_issue_id=issue_id,
    )


def test_collection_references_extracts_ranges_and_implicit_series() -> None:
    """Parse explicit ranges while allowing small linked one-shots."""
    description = """
    <p>Collects
      <a data-ref-id="4050-10">Alpha</a> #1-3,
      <a href="/beta/4050-20/">Beta Special</a>.
    </p>
    <h4>Collected Editions</h4>
    <p><a data-ref-id="4050-999">Not Source Material</a></p>
    """
    assert collection_references(description) == (
        SeriesReference(10, "Alpha", ("1", "2", "3")),
        SeriesReference(20, "Beta Special", None),
    )


def test_collection_references_supports_collects_heading_lists() -> None:
    """Parse list items under an explicit Collects heading."""
    description = """
    <h4>Collects</h4>
    <ul>
      <li><a data-ref-id="4050-30">Gamma</a> #4</li>
      <li><a data-ref-id="4050-40">Delta</a> #1-2</li>
    </ul>
    <h4>Credits</h4>
    <p><a data-ref-id="4050-50">Ignore Me</a></p>
    """
    assert collection_references(description) == (
        SeriesReference(30, "Gamma", ("4",)),
        SeriesReference(40, "Delta", ("1", "2")),
    )


def test_expand_cbl_uses_explicit_ranges_and_small_complete_series() -> None:
    """Expand proven ranges plus a small linked series in source order."""
    snapshot = FakeSnapshot()
    snapshot.issues[1000] = _row(id=1000, volume_id=9000, issue_number="1")
    snapshot.volumes[9000] = _row(
        id=9000,
        name="Collected Book",
        start_year="2020",
        description=(
            '<p>Collects <a data-ref-id="4050-10">Alpha</a> #1-2, '
            '<a data-ref-id="4050-20">Beta Special</a>.</p>'
        ),
    )
    snapshot.volumes[10] = _row(id=10, name="Alpha", start_year="2001")
    snapshot.volume_issues[10] = [
        _row(id=101, issue_number="1", cover_date="2001-01-01"),
        _row(id=102, issue_number="2", cover_date="2001-02-01"),
        _row(id=103, issue_number="3", cover_date="2001-03-01"),
    ]
    snapshot.volumes[20] = _row(id=20, name="Beta Special", start_year="2002")
    snapshot.volume_issues[20] = [
        _row(id=201, issue_number="1", cover_date="2002-04-01"),
    ]

    result = expand_cbl((_source(),), snapshot)

    assert [book.comicvine_issue_id for book in result.books] == [101, 102, 201]
    assert [book.series_name for book in result.books] == ["Alpha", "Alpha", "Beta Special"]
    assert [book.issue_number for book in result.books] == ["1", "2", "1"]
    assert [book.volume_year for book in result.books] == [2001, 2001, 2002]
    assert [book.publication_year for book in result.books] == [2001, 2001, 2002]
    assert result.problems == ()


def test_expand_cbl_fails_closed_for_long_implicit_series() -> None:
    """Refuse to guess that a long ongoing series is wholly collected."""
    snapshot = FakeSnapshot()
    snapshot.volumes[9000] = _row(
        id=9000,
        name="Collected Book",
        description='<p>Collects <a data-ref-id="4050-10">Long Ongoing</a>.</p>',
    )
    snapshot.volumes[10] = _row(id=10, name="Long Ongoing", start_year="2000")
    snapshot.volume_issues[10] = [
        _row(id=100 + number, issue_number=str(number)) for number in range(1, 14)
    ]

    result = expand_cbl((_source(),), snapshot, implicit_series_limit=12)

    assert result.books == ()
    assert len(result.problems) == 1
    assert "13 issues" in result.problems[0].message
    assert "no issue range" in result.problems[0].message


def test_expand_cbl_recursively_expands_nested_collections() -> None:
    """Peel nested collection records until source issues are reached."""
    snapshot = FakeSnapshot()
    snapshot.volumes[9000] = _row(
        id=9000,
        name="Outer Collection",
        description='<p>Collects <a data-ref-id="4050-30">Inner Collection</a>.</p>',
    )
    snapshot.volumes[30] = _row(
        id=30,
        name="Inner Collection",
        start_year="2010",
        description='<p>Collects <a data-ref-id="4050-40">Source Mini</a> #1-2.</p>',
    )
    snapshot.volume_issues[30] = [_row(id=300, issue_number="1")]
    snapshot.volumes[40] = _row(id=40, name="Source Mini", start_year="2009")
    snapshot.volume_issues[40] = [
        _row(id=401, issue_number="1", cover_date="2009-01-01"),
        _row(id=402, issue_number="2", cover_date="2009-02-01"),
    ]

    result = expand_cbl((_source(series="Outer Collection"),), snapshot)

    assert [book.comicvine_issue_id for book in result.books] == [401, 402]
    assert result.problems == ()


def test_expand_cbl_overrides_metadata_and_deduplicates_issue_ids() -> None:
    """Allow explicit operator evidence and remove repeated source issues."""
    snapshot = FakeSnapshot()
    snapshot.volumes[10] = _row(id=10, name="Alpha", start_year="2001")
    snapshot.volume_issues[10] = [_row(id=101, issue_number="1")]
    source_one = _source(issue_id="1000", series="First Collection")
    source_two = CBLBook(
        position=2,
        series="Second Collection",
        issue_number="1",
        volume_year=2021,
        publication_year=2021,
        comicvine_series_id="9001",
        comicvine_issue_id="1001",
    )
    overrides = {
        1000: (SeriesReference(10, "Alpha", ("1",)),),
        1001: (SeriesReference(10, "Alpha", ("1",)),),
    }

    result = expand_cbl((source_one, source_two), snapshot, overrides=overrides)

    assert [book.comicvine_issue_id for book in result.books] == [101]
    assert result.duplicate_issue_ids == (101,)
    assert result.problems == ()


def test_write_cbl_emits_issue_level_comicvine_ids(tmp_path: Path) -> None:
    """Write escaped issue-level CBL XML with provider identities."""
    snapshot = FakeSnapshot()
    snapshot.volumes[10] = _row(id=10, name="Alpha & Omega", start_year="2001")
    snapshot.volume_issues[10] = [
        _row(id=101, issue_number="1", cover_date="2001-01-01"),
    ]
    result = expand_cbl(
        (_source(),),
        snapshot,
        overrides={1000: (SeriesReference(10, "Alpha & Omega", ("1",)),)},
    )
    destination = tmp_path / "expanded.cbl"

    write_cbl(destination, "Expanded & Verified", result.books)

    text = destination.read_text(encoding="utf-8")
    assert "<Name>Expanded &amp; Verified</Name>" in text
    assert 'Series="Alpha &amp; Omega"' in text
    assert 'Number="1"' in text
    assert 'Volume="2001"' in text
    assert 'Year="2001"' in text
    assert 'Name="cv" Series="10" Issue="101"' in text
