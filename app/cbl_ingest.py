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


@dataclass(frozen=True, slots=True)
class CBLInventoryFile:
    """Per-file inventory row used to verify a complete mirror refresh."""

    source_path: str
    content_hash: str
    publisher: str
    entry_count: int
    comicvine_series_id_count: int
    comicvine_issue_id_count: int
    comicvine_pair_count: int


@dataclass(frozen=True, slots=True)
class CBLInventoryPublisher:
    """File and parse counts for one top-level mirror directory."""

    name: str
    files: int
    parsed: int
    failed: int


@dataclass(frozen=True, slots=True)
class CBLInventory:
    """Deterministic, database-free inventory of a complete CBL mirror revision.

    The inventory is intentionally independent of persistence so a refresh can
    measure the entire fork before opening a database session or applying any
    writes.
    """

    total_files: int
    parsed_files: int
    failed_files: int
    total_entries: int
    entries_with_comicvine_series_id: int
    entries_with_comicvine_issue_id: int
    entries_with_comicvine_pair: int
    distinct_comicvine_series_ids: int
    distinct_comicvine_issue_ids: int
    duplicate_content_hash_groups: int
    duplicate_source_paths: int
    declared_count_mismatches: int
    files: tuple[CBLInventoryFile, ...]
    publishers: tuple[CBLInventoryPublisher, ...]


def discover_cbl_files(mirror_path: Path) -> tuple[Path, ...]:
    """Return every CBL file beneath a mirror in deterministic relative-path order.

    Args:
        mirror_path: Root directory of the configured local CBL mirror.

    Returns:
        All discovered CBL file paths sorted by case-insensitive relative path.
    """
    return tuple(
        sorted(
            (
                path
                for path in mirror_path.rglob("*")
                if path.is_file() and path.suffix.lower() == ".cbl"
            ),
            key=lambda path: (
                path.relative_to(mirror_path).as_posix().casefold(),
                path.relative_to(mirror_path).as_posix(),
            ),
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


def build_cbl_inventory(
    parsed_lists: tuple[CBLList, ...],
    failures: tuple[CBLParseFailure, ...],
) -> CBLInventory:
    """Build an exact, deterministic inventory from parsed mirror results.

    Args:
        parsed_lists: Successfully parsed CBL files for one mirror revision.
        failures: Path-specific failures observed while parsing the same revision.

    Returns:
        Aggregate and per-path counts covering every discovered CBL file.

    Raises:
        ValueError: If parsed lists or failures use an empty source path.
    """
    source_paths = [item.source_path for item in parsed_lists]
    failure_paths = [failure.source_path for failure in failures]
    if any(not path.strip() for path in source_paths + failure_paths):
        raise ValueError("CBL inventory source paths must be non-empty")

    file_rows = tuple(
        sorted(
            (_inventory_file(item) for item in parsed_lists),
            key=lambda row: (row.source_path.casefold(), row.source_path),
        )
    )
    all_paths = source_paths + failure_paths
    hash_paths: dict[str, set[str]] = {}
    for item in parsed_lists:
        hash_paths.setdefault(item.content_hash, set()).add(item.source_path)

    series_ids = {
        book.comicvine_series_id
        for item in parsed_lists
        for book in item.books
        if book.comicvine_series_id is not None
    }
    issue_ids = {
        book.comicvine_issue_id
        for item in parsed_lists
        for book in item.books
        if book.comicvine_issue_id is not None
    }
    publisher_paths: dict[str, list[bool]] = {}
    for item in parsed_lists:
        publisher_paths.setdefault(_publisher_for_path(item.source_path), []).append(True)
    for failure in failures:
        publisher_paths.setdefault(_publisher_for_path(failure.source_path), []).append(False)

    return CBLInventory(
        total_files=len(all_paths),
        parsed_files=len(parsed_lists),
        failed_files=len(failures),
        total_entries=sum(len(item.books) for item in parsed_lists),
        entries_with_comicvine_series_id=sum(
            1
            for item in parsed_lists
            for book in item.books
            if book.comicvine_series_id is not None
        ),
        entries_with_comicvine_issue_id=sum(
            1
            for item in parsed_lists
            for book in item.books
            if book.comicvine_issue_id is not None
        ),
        entries_with_comicvine_pair=sum(
            1
            for item in parsed_lists
            for book in item.books
            if book.comicvine_series_id is not None and book.comicvine_issue_id is not None
        ),
        distinct_comicvine_series_ids=len(series_ids),
        distinct_comicvine_issue_ids=len(issue_ids),
        duplicate_content_hash_groups=sum(
            1 for paths in hash_paths.values() if len(paths) > 1
        ),
        duplicate_source_paths=len(all_paths) - len(set(all_paths)),
        declared_count_mismatches=sum(
            1
            for item in parsed_lists
            if item.declared_issue_count is not None
            and item.declared_issue_count != len(item.books)
        ),
        files=file_rows,
        publishers=tuple(
            sorted(
                (
                    CBLInventoryPublisher(
                        name=name,
                        files=len(parsed_flags),
                        parsed=sum(parsed_flags),
                        failed=len(parsed_flags) - sum(parsed_flags),
                    )
                    for name, parsed_flags in publisher_paths.items()
                ),
                key=lambda publisher: (publisher.name.casefold(), publisher.name),
            )
        ),
    )


def _inventory_file(item: CBLList) -> CBLInventoryFile:
    """Build one per-path inventory row from a parsed CBL list."""
    return CBLInventoryFile(
        source_path=item.source_path,
        content_hash=item.content_hash,
        publisher=_publisher_for_path(item.source_path),
        entry_count=len(item.books),
        comicvine_series_id_count=sum(
            1 for book in item.books if book.comicvine_series_id is not None
        ),
        comicvine_issue_id_count=sum(
            1 for book in item.books if book.comicvine_issue_id is not None
        ),
        comicvine_pair_count=sum(
            1
            for book in item.books
            if book.comicvine_series_id is not None and book.comicvine_issue_id is not None
        ),
    )


def _publisher_for_path(source_path: str) -> str:
    """Derive the publisher folder from a source-relative path."""
    if "/" not in source_path:
        return "(root)"
    return source_path.split("/", 1)[0]


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
    database_name = "" if database is None else (database.get("Name") or "").strip().casefold()
    if database is not None and database_name in {"comicvine", "cv"}:
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
