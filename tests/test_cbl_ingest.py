"""Focused coverage for CBL mirror discovery and parsing."""

from pathlib import Path

import pytest

from app.cbl_ingest import discover_cbl_files, parse_cbl_file, parse_cbl_mirror


CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>X of Swords</Name>
  <NumIssues>2</NumIssues>
  <Books>
    <Book Series="X-Men" Number="12" Volume="2019" Year="2020" SeriesID="123" IssueID="456" />
    <Book Series="X of Swords: Creation" Number="1" Year="2020">
      <Database Name="ComicVine" Series="789" Issue="101112" />
    </Book>
  </Books>
</ReadingList>
"""


def test_discovers_all_cbl_files_recursively_and_deterministically(tmp_path: Path) -> None:
    """Discover CBL files recursively in deterministic relative-path order."""
    (tmp_path / "Marvel" / "Events").mkdir(parents=True)
    (tmp_path / "DC" / "Other").mkdir(parents=True)
    (tmp_path / "Marvel" / "Events" / "z.cbl").write_text(CBL)
    (tmp_path / "DC" / "Other" / "A.CBL").write_text(CBL)
    (tmp_path / "ignored.xml").write_text(CBL)

    discovered = discover_cbl_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in discovered] == [
        "DC/Other/A.CBL",
        "Marvel/Events/z.cbl",
    ]


def test_parses_order_provenance_and_comicvine_evidence(tmp_path: Path) -> None:
    """Preserve ordered books, provenance, hashes, and ComicVine evidence."""
    path = tmp_path / "Events" / "x.cbl"
    path.parent.mkdir()
    path.write_text(CBL)

    parsed = parse_cbl_file(path, mirror_path=tmp_path)

    assert parsed.name == "X of Swords"
    assert parsed.declared_issue_count == 2
    assert parsed.source_path == "Events/x.cbl"
    assert len(parsed.content_hash) == 64
    assert [(book.position, book.series, book.issue_number) for book in parsed.books] == [
        (1, "X-Men", "12"),
        (2, "X of Swords: Creation", "1"),
    ]
    assert parsed.books[0].volume_year == 2019
    assert parsed.books[0].publication_year == 2020
    assert parsed.books[0].comicvine_series_id == "123"
    assert parsed.books[0].comicvine_issue_id == "456"
    assert parsed.books[1].comicvine_series_id == "789"
    assert parsed.books[1].comicvine_issue_id == "101112"


def test_malformed_file_is_isolated_from_successful_files(tmp_path: Path) -> None:
    """Isolate malformed CBL files without discarding valid parse results."""
    (tmp_path / "good.cbl").write_text(CBL)
    (tmp_path / "bad.cbl").write_text("<ReadingList><Books>")

    parsed, failures = parse_cbl_mirror(tmp_path)

    assert [item.source_path for item in parsed] == ["good.cbl"]
    assert len(failures) == 1
    assert failures[0].source_path == "bad.cbl"
    assert "malformed CBL XML" in failures[0].message


def test_invalid_book_reports_path_specific_failure(tmp_path: Path) -> None:
    """Report the source path when a book omits required identity fields."""
    path = tmp_path / "broken.cbl"
    path.write_text("<ReadingList><Books><Book Series='X-Men' /></Books></ReadingList>")

    parsed, failures = parse_cbl_mirror(tmp_path)

    assert parsed == ()
    assert failures[0].source_path == "broken.cbl"
    assert "missing required Series or Number" in failures[0].message


def test_invalid_numeric_metadata_is_rejected(tmp_path: Path) -> None:
    """Reject malformed numeric metadata instead of silently coercing it."""
    path = tmp_path / "bad-year.cbl"
    path.write_text("<ReadingList><Books><Book Series='X-Men' Number='1' Year='nope' /></Books></ReadingList>")

    with pytest.raises(ValueError, match="expected integer value"):
        parse_cbl_file(path, mirror_path=tmp_path)
