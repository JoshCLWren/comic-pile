"""Focused coverage for CBL mirror discovery and parsing."""

from pathlib import Path
from hashlib import sha256

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

CV_ALIAS_CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>B.P.R.D. source syntax</Name>
  <NumIssues>1</NumIssues>
  <Books>
    <Book Series="B.P.R.D.: The Universal Machine" Number="1" Volume="2006" Year="2006">
      <Database Name="cv" Series="18435" Issue="108135" />
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


def test_parses_cv_database_alias_used_by_source_repository(tmp_path: Path) -> None:
    """Accept the standard ``cv`` shorthand for ComicVine database evidence."""
    path = tmp_path / "bprd.cbl"
    path.write_text(CV_ALIAS_CBL)

    parsed = parse_cbl_file(path, mirror_path=tmp_path)

    assert len(parsed.books) == 1
    assert parsed.books[0].comicvine_series_id == "18435"
    assert parsed.books[0].comicvine_issue_id == "108135"


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
    path.write_text(
        "<ReadingList><Books><Book Series='X-Men' Number='1' Year='nope' /></Books></ReadingList>"
    )

    with pytest.raises(ValueError, match="expected integer value"):
        parse_cbl_file(path, mirror_path=tmp_path)


@pytest.mark.parametrize("attribute", ["Volume", "Year"])
@pytest.mark.parametrize("value", ["None", " none ", "NONE"])
def test_explicit_unknown_year_preserves_comicvine_evidence(
    tmp_path: Path,
    attribute: str,
    value: str,
) -> None:
    """An unknown optional year does not discard the source or its exact IDs."""
    original = 'Volume="2019"' if attribute == "Volume" else 'Year="2020"'
    path = tmp_path / "unknown.cbl"
    raw = CBL.replace(original, f'{attribute}="{value}"', 1)
    path.write_text(raw)

    parsed = parse_cbl_file(path, mirror_path=tmp_path)

    assert len(parsed.books) == 2
    book = parsed.books[0]
    assert (book.volume_year if attribute == "Volume" else book.publication_year) is None
    assert (book.comicvine_series_id, book.comicvine_issue_id) == ("123", "456")
    assert parsed.content_hash == sha256(raw.encode()).hexdigest()


def test_unknown_volume_keeps_unresolved_occurrence_in_source_order(tmp_path: Path) -> None:
    """Retain an unresolved occurrence without fabricating provider identity."""
    path = tmp_path / "ordered.cbl"
    path.write_text(
        CBL.replace(
            '<Book Series="X of Swords: Creation"',
            '<Book Series="O Judoka" Number="27" Volume="None" Year="0" />'
            '<Book Series="X of Swords: Creation"',
        ).replace("<NumIssues>2</NumIssues>", "<NumIssues>3</NumIssues>")
    )

    parsed, failures = parse_cbl_mirror(tmp_path)

    assert not failures
    assert parsed[0].declared_issue_count == len(parsed[0].books) == 3
    assert [book.position for book in parsed[0].books] == [1, 2, 3]
    unresolved = parsed[0].books[1]
    assert (unresolved.series, unresolved.issue_number) == ("O Judoka", "27")
    assert unresolved.volume_year is None
    assert unresolved.comicvine_series_id is None
    assert unresolved.comicvine_issue_id is None
    assert parsed[0].books[2].comicvine_issue_id == "101112"


def test_unknown_volume_preserves_nested_fork_identity(tmp_path: Path) -> None:
    """The actual fork's unknown year does not erase its nested Comic Vine IDs."""
    path = tmp_path / "nested.cbl"
    path.write_text(
        '<ReadingList><Books><Book Series="O Judoka" Number="27" Volume="None" Year="0">'
        '<Database Name="cv" Series="154917" Issue="1032915" />'
        '</Book></Books></ReadingList>'
    )
    book = parse_cbl_file(path, mirror_path=tmp_path).books[0]
    assert book.volume_year is None
    assert book.publication_year == 0
    assert (book.comicvine_series_id, book.comicvine_issue_id) == ("154917", "1032915")


@pytest.mark.parametrize("attribute", ["Volume", "Year"])
def test_other_invalid_year_values_remain_errors(tmp_path: Path, attribute: str) -> None:
    """Only the explicit None sentinel is recognized, not arbitrary bad metadata."""
    path = tmp_path / "invalid.cbl"
    path.write_text(
        f'<ReadingList><Books><Book Series="X" Number="1" {attribute}="unknown" /></Books></ReadingList>'
    )
    with pytest.raises(ValueError, match="expected integer value"):
        parse_cbl_file(path, mirror_path=tmp_path)


def test_unknown_sentinel_does_not_relax_declared_count_validation(tmp_path: Path) -> None:
    """NumIssues remains a numeric count rather than optional year metadata."""
    path = tmp_path / "invalid-count.cbl"
    path.write_text(CBL.replace("<NumIssues>2</NumIssues>", "<NumIssues>None</NumIssues>"))
    with pytest.raises(ValueError, match="expected integer value"):
        parse_cbl_file(path, mirror_path=tmp_path)
