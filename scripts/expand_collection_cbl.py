"""Expand collection-level CBL reading lists into issue-level CBL files.

The operator tool is deliberately conservative. It uses a local ComicVine snapshot
to turn collection entries (trade paperbacks, hardcovers, omnibuses) into the
source issues they collect. When collection metadata is incomplete or ambiguous,
the entry is reported instead of guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.cbl_ingest import CBLBook, parse_cbl_file
from comic_pile.local_comicvine import LocalComicVineResult, LocalComicVineSnapshot


_COLLECTION_MARKER_RE = re.compile(r"\b(?:collects?|collecting)\b", re.IGNORECASE)
_SERIES_TOKEN_RE = re.compile(
    r"\[\[CVSERIES:(?P<id>\d+)\]\](?P<title>.*?)\[\[/CVSERIES\]\]",
    re.DOTALL,
)
_REF_ID_RE = re.compile(r"(?:^|-)4050-(\d+)$")
_HREF_SERIES_RE = re.compile(r"/4050-(\d+)(?:/|$)")


class SnapshotReader(Protocol):
    """Read-only ComicVine data needed by collection expansion."""

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Return one issue by provider ID."""
        ...

    def get_volume(self, volume_id: int) -> LocalComicVineResult | None:
        """Return one volume by provider ID."""
        ...

    def get_volume_issues(self, volume_id: int) -> list[LocalComicVineResult]:
        """Return all locally cached issues for one volume."""
        ...


@dataclass(frozen=True, slots=True)
class SeriesReference:
    """One source series mentioned by a collection's contents metadata."""

    volume_id: int
    title: str
    issue_numbers: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ExpandedBook:
    """One issue-level CBL output row."""

    series_name: str
    issue_number: str
    volume_year: int | None
    publication_year: int | None
    comicvine_series_id: int
    comicvine_issue_id: int
    source_collection_position: int
    source_collection_issue_id: int


@dataclass(frozen=True, slots=True)
class ExpansionProblem:
    """One collection or linked-series expansion that could not be proven."""

    collection_position: int
    collection_title: str
    message: str


@dataclass(frozen=True, slots=True)
class ExpansionResult:
    """Complete expansion output plus unresolved diagnostics."""

    books: tuple[ExpandedBook, ...]
    problems: tuple[ExpansionProblem, ...]
    duplicate_issue_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _HtmlBlock:
    tag: str
    text: str


class _CollectionHTMLParser(HTMLParser):
    """Preserve text blocks and ComicVine series links from collection HTML."""

    _BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_HtmlBlock] = []
        self._tag: str | None = None
        self._parts: list[str] = []
        self._linked = False

    @staticmethod
    def _series_id(attrs: list[tuple[str, str | None]]) -> int | None:
        values = {key: value or "" for key, value in attrs}
        ref_match = _REF_ID_RE.search(values.get("data-ref-id", ""))
        if ref_match:
            return int(ref_match.group(1))
        href_match = _HREF_SERIES_RE.search(values.get("href", ""))
        return int(href_match.group(1)) if href_match else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_TAGS:
            self._flush()
            self._tag = tag
        if tag == "a":
            series_id = self._series_id(attrs)
            if series_id is not None:
                self._parts.append(f"[[CVSERIES:{series_id}]]")
                self._linked = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._linked:
            self._parts.append("[[/CVSERIES]]")
            self._linked = False
        if tag in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join("".join(self._parts).split())
        if text:
            self.blocks.append(_HtmlBlock(self._tag or "text", text))
        self._parts = []
        self._tag = None
        self._linked = False


def _expand_numeric_range(start: str, end: str) -> tuple[str, ...]:
    first = int(start)
    last = int(end)
    if last < first or last - first > 500:
        return ()
    return tuple(str(value) for value in range(first, last + 1))


def _issue_numbers_from_suffix(suffix: str) -> tuple[str, ...] | None:
    """Extract explicit numeric issue labels following one linked series."""
    found: list[tuple[int, tuple[str, ...]]] = []
    occupied: list[tuple[int, int]] = []
    range_patterns = (
        re.compile(r"#\s*(\d+)\s*[-–—]\s*#?\s*(\d+)"),
        re.compile(r"\bissues?\s+(\d+)\s*[-–—]\s*(\d+)", re.IGNORECASE),
    )
    for pattern in range_patterns:
        for match in pattern.finditer(suffix):
            labels = _expand_numeric_range(match.group(1), match.group(2))
            if labels:
                found.append((match.start(), labels))
                occupied.append(match.span())

    list_pattern = re.compile(
        r"#\s*(\d+)(?P<rest>(?:\s*(?:,|&|and)\s*#?\s*\d+)+)",
        re.IGNORECASE,
    )
    for match in list_pattern.finditer(suffix):
        labels = (match.group(1), *re.findall(r"\d+", match.group("rest")))
        found.append((match.start(), labels))
        occupied.append(match.span())

    def inside_group(index: int) -> bool:
        return any(start <= index < end for start, end in occupied)

    for match in re.finditer(r"#\s*(\d+)", suffix):
        if not inside_group(match.start()):
            found.append((match.start(), (match.group(1),)))

    if not found:
        return None

    labels: list[str] = []
    seen: set[str] = set()
    for _position, group in sorted(found, key=lambda item: item[0]):
        for label in group:
            if label not in seen:
                labels.append(label)
                seen.add(label)
    return tuple(labels) or None


def _refs_from_text(text: str) -> list[SeriesReference]:
    matches = list(_SERIES_TOKEN_RE.finditer(text))
    refs: list[SeriesReference] = []
    for index, match in enumerate(matches):
        suffix_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        suffix = text[match.end() : suffix_end]
        refs.append(
            SeriesReference(
                volume_id=int(match.group("id")),
                title=" ".join(match.group("title").split()),
                issue_numbers=_issue_numbers_from_suffix(suffix),
            )
        )
    return refs


def collection_references(description: str | None) -> tuple[SeriesReference, ...]:
    """Extract linked source series from ComicVine collection metadata."""
    if not description:
        return ()
    parser = _CollectionHTMLParser()
    parser.feed(description)
    parser.close()

    refs: list[SeriesReference] = []
    collecting_list = False
    for block in parser.blocks:
        normalized = block.text.strip().rstrip(":").casefold()
        if block.tag.startswith("h"):
            collecting_list = normalized in {"collect", "collects", "collecting", "contents"}
            continue

        marker = _COLLECTION_MARKER_RE.search(block.text)
        if marker:
            refs.extend(_refs_from_text(block.text[marker.end() :]))
            collecting_list = True
            continue
        if collecting_list and block.tag == "li":
            refs.extend(_refs_from_text(block.text))
            continue
        if collecting_list and block.tag not in {"li", "text"}:
            collecting_list = False

    deduped: list[SeriesReference] = []
    seen: set[tuple[int, tuple[str, ...] | None]] = set()
    for ref in refs:
        key = (ref.volume_id, ref.issue_numbers)
        if key not in seen:
            deduped.append(ref)
            seen.add(key)
    return tuple(deduped)


def _provider_id(data: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    return None


def _year(value: object) -> int | None:
    if isinstance(value, int) and 1000 <= value <= 9999:
        return value
    if isinstance(value, str):
        match = re.search(r"\b(\d{4})\b", value)
        if match:
            return int(match.group(1))
    return None


def _issue_key(value: object) -> tuple[tuple[int, object], ...]:
    raw = str(value or "").strip().casefold().removeprefix("#").strip()
    parts = re.split(r"(\d+)", raw)
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part
    )


def _normalize_issue_number(value: object) -> str:
    return str(value or "").strip().casefold().removeprefix("#").strip()


def _descriptions(*results: LocalComicVineResult | None) -> tuple[str, ...]:
    values: list[str] = []
    for result in results:
        if result is None:
            continue
        description = result.data.get("description")
        if isinstance(description, str) and description.strip():
            values.append(description)
    return tuple(values)


def _refs_for_collection(
    *,
    issue: LocalComicVineResult | None,
    volume: LocalComicVineResult | None,
) -> tuple[SeriesReference, ...]:
    refs: list[SeriesReference] = []
    for description in _descriptions(volume, issue):
        refs.extend(collection_references(description))
    deduped: list[SeriesReference] = []
    seen: set[tuple[int, tuple[str, ...] | None]] = set()
    for ref in refs:
        key = (ref.volume_id, ref.issue_numbers)
        if key not in seen:
            deduped.append(ref)
            seen.add(key)
    return tuple(deduped)


def _load_overrides(path: Path | None) -> dict[int, tuple[SeriesReference, ...]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("override file must be a JSON object keyed by collection issue ID")

    overrides: dict[int, tuple[SeriesReference, ...]] = {}
    for raw_issue_id, rows in raw.items():
        collection_issue_id = int(raw_issue_id)
        if not isinstance(rows, list):
            raise ValueError(f"override {raw_issue_id} must be a list")
        refs: list[SeriesReference] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"override {raw_issue_id} entries must be objects")
            volume_id = int(row["series_id"])
            title = str(row.get("series_name") or f"ComicVine series {volume_id}")
            issue_spec = row.get("issues", "all")
            if issue_spec == "all":
                numbers = None
            elif isinstance(issue_spec, list):
                numbers = tuple(str(value) for value in issue_spec)
            else:
                raise ValueError(
                    f"override {raw_issue_id} issues must be \"all\" or a list"
                )
            refs.append(SeriesReference(volume_id, title, numbers))
        overrides[collection_issue_id] = tuple(refs)
    return overrides


def _select_issues(
    ref: SeriesReference,
    issues: list[LocalComicVineResult],
    *,
    implicit_series_limit: int,
) -> tuple[list[LocalComicVineResult], str | None]:
    if ref.issue_numbers is None:
        if len(issues) > implicit_series_limit:
            return [], (
                f"{ref.title} ({ref.volume_id}) has {len(issues)} issues but the collection "
                "metadata gives no issue range"
            )
        return sorted(issues, key=lambda row: _issue_key(row.data.get("issue_number"))), None

    by_number: dict[str, list[LocalComicVineResult]] = {}
    for issue in issues:
        key = _normalize_issue_number(issue.data.get("issue_number"))
        by_number.setdefault(key, []).append(issue)

    selected: list[LocalComicVineResult] = []
    for number in ref.issue_numbers:
        matches = by_number.get(_normalize_issue_number(number), [])
        if len(matches) != 1:
            return [], (
                f"{ref.title} ({ref.volume_id}) issue {number!r} resolved to "
                f"{len(matches)} local ComicVine rows"
            )
        selected.append(matches[0])
    return selected, None


def _expand_ref(
    snapshot: SnapshotReader,
    ref: SeriesReference,
    *,
    collection_position: int,
    collection_title: str,
    collection_issue_id: int,
    implicit_series_limit: int,
    depth: int,
    seen_collection_issue_ids: frozenset[int],
) -> tuple[list[ExpandedBook], list[ExpansionProblem]]:
    volume = snapshot.get_volume(ref.volume_id)
    issues = snapshot.get_volume_issues(ref.volume_id)
    if volume is None or not issues:
        return [], [
            ExpansionProblem(
                collection_position,
                collection_title,
                f"ComicVine series {ref.volume_id} is missing from the local snapshot",
            )
        ]

    selected, error = _select_issues(
        ref,
        issues,
        implicit_series_limit=implicit_series_limit,
    )
    if error:
        return [], [ExpansionProblem(collection_position, collection_title, error)]

    books: list[ExpandedBook] = []
    problems: list[ExpansionProblem] = []
    volume_name = str(volume.data.get("name") or ref.title).strip() or ref.title
    volume_year = _year(volume.data.get("start_year"))

    for row in selected:
        issue_id = _provider_id(row.data, "id", "comicvine_id", "issue_id")
        if issue_id is None:
            problems.append(
                ExpansionProblem(
                    collection_position,
                    collection_title,
                    f"{volume_name} has a local issue row without a provider issue ID",
                )
            )
            continue

        nested_refs = _refs_for_collection(issue=row, volume=volume)
        if (
            nested_refs
            and depth < 4
            and issue_id not in seen_collection_issue_ids
            and len(selected) == 1
        ):
            nested_seen = seen_collection_issue_ids | {issue_id}
            for nested_ref in nested_refs:
                nested_books, nested_problems = _expand_ref(
                    snapshot,
                    nested_ref,
                    collection_position=collection_position,
                    collection_title=collection_title,
                    collection_issue_id=collection_issue_id,
                    implicit_series_limit=implicit_series_limit,
                    depth=depth + 1,
                    seen_collection_issue_ids=nested_seen,
                )
                books.extend(nested_books)
                problems.extend(nested_problems)
            continue

        issue_number = str(row.data.get("issue_number") or "").strip()
        if not issue_number:
            problems.append(
                ExpansionProblem(
                    collection_position,
                    collection_title,
                    f"ComicVine issue {issue_id} has no issue number",
                )
            )
            continue
        publication_year = _year(row.data.get("cover_date")) or _year(
            row.data.get("store_date")
        )
        books.append(
            ExpandedBook(
                series_name=volume_name,
                issue_number=issue_number,
                volume_year=volume_year,
                publication_year=publication_year,
                comicvine_series_id=ref.volume_id,
                comicvine_issue_id=issue_id,
                source_collection_position=collection_position,
                source_collection_issue_id=collection_issue_id,
            )
        )
    return books, problems


def expand_cbl(
    source_books: tuple[CBLBook, ...],
    snapshot: SnapshotReader,
    *,
    implicit_series_limit: int = 12,
    overrides: dict[int, tuple[SeriesReference, ...]] | None = None,
) -> ExpansionResult:
    """Expand collection-level CBL entries in source order."""
    configured_overrides = overrides or {}
    books: list[ExpandedBook] = []
    problems: list[ExpansionProblem] = []
    duplicate_ids: list[int] = []
    seen_issue_ids: set[int] = set()

    for position, source in enumerate(source_books, start=1):
        title = f"{source.series} #{source.issue_number}"
        try:
            collection_issue_id = int(source.comicvine_issue_id or "")
        except ValueError:
            problems.append(
                ExpansionProblem(position, title, "source entry has no ComicVine issue ID")
            )
            continue
        try:
            collection_volume_id = int(source.comicvine_series_id or "")
        except ValueError:
            collection_volume_id = 0

        issue = snapshot.get_issue(collection_issue_id)
        volume = snapshot.get_volume(collection_volume_id) if collection_volume_id else None
        refs = configured_overrides.get(collection_issue_id) or _refs_for_collection(
            issue=issue,
            volume=volume,
        )
        if not refs:
            problems.append(
                ExpansionProblem(
                    position,
                    title,
                    "collection contents could not be proven from local ComicVine metadata",
                )
            )
            continue

        for ref in refs:
            expanded, ref_problems = _expand_ref(
                snapshot,
                ref,
                collection_position=position,
                collection_title=title,
                collection_issue_id=collection_issue_id,
                implicit_series_limit=implicit_series_limit,
                depth=0,
                seen_collection_issue_ids=frozenset({collection_issue_id}),
            )
            problems.extend(ref_problems)
            for book in expanded:
                if book.comicvine_issue_id in seen_issue_ids:
                    duplicate_ids.append(book.comicvine_issue_id)
                    continue
                seen_issue_ids.add(book.comicvine_issue_id)
                books.append(book)

    return ExpansionResult(tuple(books), tuple(problems), tuple(duplicate_ids))


def write_cbl(path: Path, name: str, books: tuple[ExpandedBook, ...]) -> None:
    """Write issue-level CBL XML with ComicVine identities."""
    root = ET.Element("ReadingList")
    ET.SubElement(root, "Name").text = name
    ET.SubElement(root, "NumIssues").text = str(len(books))
    books_node = ET.SubElement(root, "Books")
    for book in books:
        attrs = {"Series": book.series_name, "Number": book.issue_number}
        if book.volume_year is not None:
            attrs["Volume"] = str(book.volume_year)
        if book.publication_year is not None:
            attrs["Year"] = str(book.publication_year)
        book_node = ET.SubElement(books_node, "Book", attrs)
        ET.SubElement(
            book_node,
            "Database",
            {
                "Name": "cv",
                "Series": str(book.comicvine_series_id),
                "Issue": str(book.comicvine_issue_id),
            },
        )
    ET.indent(root, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_report(path: Path, source_name: str, result: ExpansionResult) -> None:
    """Write a machine-readable audit report for the expansion."""
    payload = {
        "source_name": source_name,
        "expanded_issue_count": len(result.books),
        "unresolved_count": len(result.problems),
        "duplicate_issue_count": len(result.duplicate_issue_ids),
        "duplicate_issue_ids": list(result.duplicate_issue_ids),
        "problems": [asdict(problem) for problem in result.problems],
        "books": [asdict(book) for book in result.books],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse operator CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_cbl", type=Path)
    parser.add_argument("--comicvine-db", type=Path, required=True)
    parser.add_argument("--output-cbl", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--implicit-series-limit", type=int, default=12)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any collection entry remains unresolved.",
    )
    return parser.parse_args()


def main() -> int:
    """Expand one collection CBL using a developer-local ComicVine snapshot."""
    args = parse_args()
    if args.implicit_series_limit < 1:
        raise SystemExit("--implicit-series-limit must be at least 1")
    if not args.source_cbl.is_file():
        raise SystemExit(f"source CBL not found: {args.source_cbl}")
    if not args.comicvine_db.is_file():
        raise SystemExit(f"ComicVine snapshot not found: {args.comicvine_db}")
    if args.output_cbl.resolve() == args.source_cbl.resolve():
        raise SystemExit("--output-cbl must not overwrite the collection-level source CBL")

    source = parse_cbl_file(args.source_cbl, mirror_path=args.source_cbl.parent)
    snapshot = LocalComicVineSnapshot(args.comicvine_db)
    overrides = _load_overrides(args.overrides)
    result = expand_cbl(
        source.books,
        snapshot,
        implicit_series_limit=args.implicit_series_limit,
        overrides=overrides,
    )
    output_name = args.name or f"{source.name} (Issue-Level Expansion)"
    write_cbl(args.output_cbl, output_name, result.books)
    write_report(args.report, source.name, result)

    print(
        json.dumps(
            {
                "source_entries": len(source.books),
                "expanded_issues": len(result.books),
                "unresolved": len(result.problems),
                "duplicates_removed": len(result.duplicate_issue_ids),
                "output_cbl": str(args.output_cbl),
                "report": str(args.report),
            },
            sort_keys=True,
        )
    )
    return 1 if args.strict and result.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
