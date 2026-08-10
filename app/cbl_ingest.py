"""Parse CBL reading-list mirrors into normalized import records."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class CBLBook:
    """One ordered comic reference declared by a CBL reading list."""

    position: int
    series: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_series_id: str | None
    comicvine_issue_id: str | None


@dataclass(frozen=True, slots=True)
class CBLList:
    """One parsed CBL file plus provenance needed for idempotent syncing."""

    source_path: str
    content_hash: str
    name: str
    declared_issue_count: int | None
    books: tuple[CBLBook, ...]


@dataclass(frozen=True, slots=True)
class CBLParseFailure:
    """Path-specific parse failure that does not prevent other files importing."""

    source_path: str
    message: str


def discover_cbl_files(mirror_path: Path) -> tuple[Path, ...]:
    """Return every CBL file beneath a mirror in deterministic relative-path order.

    Args:
        mirror_path: Root directory of the configured local CBL mirror.

    Returns:
        All discovered CBL file paths sorted by case-insensitive relative path.
    """
    return tuple(
        sorted(
            (path for path in mirror_path.rglob("*") if path.is_file() and path.suffix.lower() == ".cbl"),
            key=lambda path: path.relative_to(mirror_path).as_posix().casefold(),
        )
    )


def parse_cbl_file(path: Path, *, mirror_path: Path) -> CBLList:
    """Parse a CBL file without performing database or network I/O.

    Args:
        path: CBL file to parse.
        mirror_path: Root directory used to derive stable source-relative provenance.

    Returns:
        Parsed list metadata, ordered book entries, source path, and content hash.
    """
    raw = path.read_bytes()
    relative_path = path.relative_to(mirror_path).as_posix()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"{relative_path}: malformed CBL XML: {exc}") from exc

    name = _text(root.find("Name")) or path.stem
    declared_issue_count = _optional_int(_text(root.find("NumIssues")))
    books_node = root.find("Books")
    book_nodes = [] if books_node is None else books_node.findall("Book")
    books = tuple(_parse_book(node, index) for index, node in enumerate(book_nodes, start=1))
    return CBLList(
        source_path=relative_path,
        content_hash=sha256(raw).hexdigest(),
        name=name,
        declared_issue_count=declared_issue_count,
        books=books,
    )


def parse_cbl_mirror(mirror_path: Path) -> tuple[tuple[CBLList, ...], tuple[CBLParseFailure, ...]]:
    """Parse all CBL files while isolating malformed files with path-specific diagnostics.

    Args:
        mirror_path: Root directory of the configured local CBL mirror.

    Returns:
        A pair containing successfully parsed lists and path-specific parse failures.
    """
    parsed: list[CBLList] = []
    failures: list[CBLParseFailure] = []
    for path in discover_cbl_files(mirror_path):
        try:
            parsed.append(parse_cbl_file(path, mirror_path=mirror_path))
        except (OSError, ValueError) as exc:
            failures.append(
                CBLParseFailure(
                    source_path=path.relative_to(mirror_path).as_posix(),
                    message=str(exc),
                )
            )
    return tuple(parsed), tuple(failures)


def _parse_book(node: ET.Element, position: int) -> CBLBook:
    series = (node.get("Series") or "").strip()
    issue_number = (node.get("Number") or "").strip()
    if not series or not issue_number:
        raise ValueError(f"book {position} is missing required Series or Number")

    volume_year = _optional_int(node.get("Volume"))
    publication_year = _optional_int(node.get("Year"))
    series_id, issue_id = _comicvine_ids(node)
    return CBLBook(
        position=position,
        series=series,
        issue_number=issue_number,
        volume_year=volume_year,
        publication_year=publication_year,
        comicvine_series_id=series_id,
        comicvine_issue_id=issue_id,
    )


def _comicvine_ids(node: ET.Element) -> tuple[str | None, str | None]:
    series_id = _first_attr(node, "SeriesID", "SeriesId", "VolumeID", "VolumeId")
    issue_id = _first_attr(node, "IssueID", "IssueId")
    database = node.find("Database")
    if database is not None and (database.get("Name") or "").casefold() == "comicvine":
        series_id = series_id or _first_attr(database, "Series", "SeriesID", "Volume", "VolumeID")
        issue_id = issue_id or _first_attr(database, "Issue", "IssueID")
    return series_id, issue_id


def _first_attr(node: ET.Element, *names: str) -> str | None:
    for name in names:
        value = node.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"expected integer value, got {value!r}") from exc
