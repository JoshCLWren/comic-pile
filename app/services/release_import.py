"""Parse and import historical changelog Markdown into the durable release ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.release import ReleaseUpsertRequest
from app.services.release_ledger import (
    ReleaseSourceConflictError,
    create_historical_release,
    find_historical_release,
    find_release_by_source,
    upsert_release,
)

IMPORTER_VERSION = "release-import-v1"
SOURCE_REPOSITORY = "JoshCLWren/comic-pile"
_DATE_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:[ T].*)?\s*$")
_MARKDOWN_CATEGORY_RE = re.compile(r"^###\s+(.+?)\s*$")
_BOLD_CATEGORY_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
_PR_LINK_RE = re.compile(r"github\.com/[^/]+/[^/]+/pull/(\d+)")
_FRAGMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d+)\.md$")


@dataclass(frozen=True)
class ReleaseImportCandidate:
    """One source-backed release note candidate discovered in Markdown."""

    source_path: str
    source_checksum: str
    source_date: str
    category: str
    summary: str
    source_pr_number: int | None
    source_order: int
    raw_source: str
    importer_version: str = IMPORTER_VERSION

    def provenance(self) -> dict[str, object]:
        """Return stable provenance metadata suitable for the release ledger."""
        return {
            "source_path": self.source_path,
            "source_checksum": self.source_checksum,
            "source_date": self.source_date,
            "source_order": self.source_order,
            "raw_source": self.raw_source,
            "importer_version": self.importer_version,
        }


@dataclass(frozen=True)
class ReleaseImportAnomaly:
    """One ambiguous or malformed source condition preserved for audit."""

    source_path: str
    line_number: int
    message: str


@dataclass
class ReleaseImportReport:
    """Machine-readable dry-run report for a changelog corpus."""

    files_scanned: int = 0
    candidates: list[ReleaseImportCandidate] = field(default_factory=list)
    anomalies: list[ReleaseImportAnomaly] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """Serialize the report without losing source-level audit detail."""
        return {
            "importer_version": IMPORTER_VERSION,
            "files_scanned": self.files_scanned,
            "candidate_count": len(self.candidates),
            "pr_backed_count": sum(c.source_pr_number is not None for c in self.candidates),
            "historical_count": sum(c.source_pr_number is None for c in self.candidates),
            "anomaly_count": len(self.anomalies),
            "candidates": [asdict(candidate) for candidate in self.candidates],
            "anomalies": [asdict(anomaly) for anomaly in self.anomalies],
        }


@dataclass(frozen=True)
class ReleaseImportConflict:
    """One source record that could not be safely reconciled with durable state."""

    source_path: str
    source_order: int
    message: str


@dataclass
class ReleaseWriteReport:
    """Machine-readable result of a write or reconciliation pass."""

    source_count: int
    imported_count: int = 0
    unchanged_count: int = 0
    missing_count: int = 0
    conflicts: list[ReleaseImportConflict] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """Serialize write/reconciliation totals and conflicts."""
        return {
            "source_count": self.source_count,
            "imported_count": self.imported_count,
            "unchanged_count": self.unchanged_count,
            "missing_count": self.missing_count,
            "conflict_count": len(self.conflicts),
            "conflicts": [asdict(conflict) for conflict in self.conflicts],
        }


def _checksum(text: str) -> str:
    """Return a stable checksum for exact source-content reconciliation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fragment_identity(path: Path) -> tuple[str | None, int | None]:
    """Read authoritative date and PR identity from a valid fragment filename."""
    match = _FRAGMENT_RE.fullmatch(path.name)
    if match is None:
        return None, None
    return match.group(1), int(match.group(2))


def _extract_pr_numbers(text: str) -> tuple[int, ...]:
    """Extract explicit GitHub pull-request identities without guessing."""
    return tuple(dict.fromkeys(int(value) for value in _PR_LINK_RE.findall(text)))


def _category(stripped: str) -> str | None:
    """Recognize both modern Markdown and frozen-archive feature-area headings."""
    markdown_match = _MARKDOWN_CATEGORY_RE.match(stripped)
    if markdown_match is not None:
        return markdown_match.group(1).strip()
    bold_match = _BOLD_CATEGORY_RE.match(stripped)
    if bold_match is not None:
        return bold_match.group(1).strip()
    return None


def parse_changelog_source(
    path: Path,
    text: str,
) -> tuple[list[ReleaseImportCandidate], list[ReleaseImportAnomaly]]:
    """Parse one changelog source into ordered candidates and anomalies."""
    checksum = _checksum(text)
    fragment_date, fragment_pr = _fragment_identity(path)
    current_date = fragment_date
    current_category = "General"
    candidates: list[ReleaseImportCandidate] = []
    anomalies: list[ReleaseImportAnomaly] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        date_match = _DATE_HEADING_RE.match(stripped)
        if date_match is not None:
            current_date = date_match.group(1)
            if fragment_date is not None and current_date != fragment_date:
                anomalies.append(
                    ReleaseImportAnomaly(
                        str(path),
                        line_number,
                        f"fragment heading date {current_date} does not match filename date {fragment_date}",
                    )
                )
            continue

        category = _category(stripped)
        if category is not None:
            current_category = category
            continue

        if stripped.startswith("#"):
            continue

        if current_date is None:
            anomalies.append(
                ReleaseImportAnomaly(
                    str(path),
                    line_number,
                    "content appears before any parseable release date",
                )
            )
            continue

        summary = stripped[2:].strip() if stripped.startswith("- ") else stripped
        if not summary:
            continue

        linked_prs = _extract_pr_numbers(summary)
        linked_pr = linked_prs[0] if len(linked_prs) == 1 else None
        if len(linked_prs) > 1:
            anomalies.append(
                ReleaseImportAnomaly(
                    str(path),
                    line_number,
                    "entry references multiple PRs; preserving it without a singular PR identity",
                )
            )
        if fragment_pr is not None and linked_pr not in {None, fragment_pr}:
            anomalies.append(
                ReleaseImportAnomaly(
                    str(path),
                    line_number,
                    f"fragment filename PR {fragment_pr} conflicts with linked PR {linked_pr}",
                )
            )
            continue
        if fragment_pr is not None and len(linked_prs) > 1 and fragment_pr not in linked_prs:
            anomalies.append(
                ReleaseImportAnomaly(
                    str(path),
                    line_number,
                    f"fragment filename PR {fragment_pr} is absent from linked PR set {linked_prs}",
                )
            )
            continue

        candidates.append(
            ReleaseImportCandidate(
                source_path=str(path),
                source_checksum=checksum,
                source_date=current_date,
                category=current_category,
                summary=summary,
                source_pr_number=fragment_pr if fragment_pr is not None else linked_pr,
                source_order=len(candidates),
                raw_source=line,
            )
        )

    if not candidates:
        anomalies.append(ReleaseImportAnomaly(str(path), 0, "source produced no release candidates"))
    return candidates, anomalies


def audit_changelog_corpus(repository_root: Path) -> ReleaseImportReport:
    """Parse the frozen archive and every valid current fragment without mutating data."""
    sources = [repository_root / "docs" / "changelog.md"]
    fragments_dir = repository_root / "docs" / "changelog.d"
    report = ReleaseImportReport()
    if fragments_dir.exists():
        for fragment in sorted(fragments_dir.glob("*.md")):
            if _FRAGMENT_RE.fullmatch(fragment.name) is None:
                report.anomalies.append(
                    ReleaseImportAnomaly(
                        str(fragment.relative_to(repository_root)),
                        0,
                        "ignored changelog fragment with invalid filename",
                    )
                )
                continue
            sources.append(fragment)

    for source in sources:
        relative_path = source.relative_to(repository_root)
        text = source.read_text(encoding="utf-8")
        candidates, anomalies = parse_changelog_source(relative_path, text)
        report.files_scanned += 1
        report.candidates.extend(candidates)
        report.anomalies.extend(anomalies)
    return report


def released_at(candidate: ReleaseImportCandidate) -> datetime:
    """Convert a source date into the deterministic UTC release timestamp used by importers."""
    return datetime.strptime(candidate.source_date, "%Y-%m-%d").replace(tzinfo=UTC)


def _title(candidate: ReleaseImportCandidate) -> str:
    """Derive a stable display title without discarding the full summary."""
    return candidate.summary[:255]


def _payload(candidate: ReleaseImportCandidate, *, sort_order: int) -> ReleaseUpsertRequest:
    """Build the release-service payload for a PR-backed candidate."""
    if candidate.source_pr_number is None:
        raise ValueError("PR-backed payload requires source_pr_number")
    return ReleaseUpsertRequest(
        source_repository=SOURCE_REPOSITORY,
        source_pr_number=candidate.source_pr_number,
        released_at=released_at(candidate),
        category=candidate.category,
        title=_title(candidate),
        summary=candidate.summary,
        sort_order=sort_order,
        provenance_json=candidate.provenance(),
    )


def _checksum_matches(candidate: ReleaseImportCandidate, provenance: dict[str, object]) -> bool:
    """Return whether durable provenance still matches the exact source corpus."""
    return provenance.get("source_checksum") == candidate.source_checksum


async def import_changelog_report(
    db: AsyncSession,
    report: ReleaseImportReport,
) -> ReleaseWriteReport:
    """Persist audited candidates idempotently while refusing silent source rewrites."""
    result = ReleaseWriteReport(source_count=len(report.candidates))
    for corpus_order, candidate in enumerate(report.candidates):
        sort_order = -corpus_order
        if candidate.source_pr_number is not None:
            existing = await find_release_by_source(
                db,
                source_repository=SOURCE_REPOSITORY,
                source_pr_number=candidate.source_pr_number,
                source_merge_sha=None,
            )
            if existing is not None and not _checksum_matches(
                candidate,
                existing.provenance_json or {},
            ):
                result.conflicts.append(
                    ReleaseImportConflict(
                        candidate.source_path,
                        candidate.source_order,
                        f"source checksum changed for PR #{candidate.source_pr_number}",
                    )
                )
                continue
            if existing is not None:
                result.unchanged_count += 1
                continue
            await upsert_release(db, _payload(candidate, sort_order=sort_order))
            result.imported_count += 1
            continue

        existing = await find_historical_release(
            db,
            source_repository=SOURCE_REPOSITORY,
            source_path=candidate.source_path,
            source_order=candidate.source_order,
        )
        if existing is not None and not _checksum_matches(
            candidate,
            existing.provenance_json or {},
        ):
            result.conflicts.append(
                ReleaseImportConflict(
                    candidate.source_path,
                    candidate.source_order,
                    "historical source checksum changed",
                )
            )
            continue
        if existing is not None:
            result.unchanged_count += 1
            continue
        try:
            await create_historical_release(
                db,
                source_repository=SOURCE_REPOSITORY,
                released_at=released_at(candidate),
                category=candidate.category,
                title=_title(candidate),
                summary=candidate.summary,
                sort_order=sort_order,
                provenance_json=candidate.provenance(),
            )
        except ReleaseSourceConflictError as error:
            result.conflicts.append(
                ReleaseImportConflict(candidate.source_path, candidate.source_order, str(error))
            )
            continue
        result.imported_count += 1
    return result


async def reconcile_changelog_report(
    db: AsyncSession,
    report: ReleaseImportReport,
) -> ReleaseWriteReport:
    """Verify source-to-database coverage, provenance, dates, content, and ordering."""
    result = ReleaseWriteReport(source_count=len(report.candidates))
    for corpus_order, candidate in enumerate(report.candidates):
        if candidate.source_pr_number is not None:
            release = await find_release_by_source(
                db,
                source_repository=SOURCE_REPOSITORY,
                source_pr_number=candidate.source_pr_number,
                source_merge_sha=None,
            )
        else:
            release = await find_historical_release(
                db,
                source_repository=SOURCE_REPOSITORY,
                source_path=candidate.source_path,
                source_order=candidate.source_order,
            )

        if release is None:
            result.missing_count += 1
            continue

        expected = {
            "checksum": candidate.source_checksum,
            "released_at": released_at(candidate),
            "category": candidate.category,
            "summary": candidate.summary,
            "sort_order": -corpus_order,
        }
        actual = {
            "checksum": (release.provenance_json or {}).get("source_checksum"),
            "released_at": release.released_at,
            "category": release.category,
            "summary": release.summary,
            "sort_order": release.sort_order,
        }
        if actual != expected:
            result.conflicts.append(
                ReleaseImportConflict(
                    candidate.source_path,
                    candidate.source_order,
                    "durable release does not match source provenance/content/order",
                )
            )
            continue
        result.unchanged_count += 1
    return result
