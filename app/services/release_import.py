"""Parse historical changelog Markdown into auditable release-import candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re

IMPORTER_VERSION = "release-import-v1"
_DATE_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:[ T].*)?\s*$")
_CATEGORY_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
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


def _checksum(text: str) -> str:
    """Return a stable checksum for exact source-content reconciliation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fragment_identity(path: Path) -> tuple[str | None, int | None]:
    """Read authoritative date and PR identity from a valid fragment filename."""
    match = _FRAGMENT_RE.fullmatch(path.name)
    if match is None:
        return None, None
    return match.group(1), int(match.group(2))


def _extract_pr_number(text: str) -> int | None:
    """Extract one explicit GitHub pull-request identity without guessing."""
    matches = {int(value) for value in _PR_LINK_RE.findall(text)}
    if len(matches) == 1:
        return matches.pop()
    return None


def parse_changelog_source(path: Path, text: str) -> tuple[list[ReleaseImportCandidate], list[ReleaseImportAnomaly]]:
    """Parse one changelog source into ordered candidates and anomalies.

    Args:
        path: Repository-relative Markdown source path.
        text: Exact source text.

    Returns:
        Ordered import candidates and preserved anomalies.
    """
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

        category_match = _CATEGORY_HEADING_RE.match(stripped)
        if category_match is not None:
            current_category = category_match.group(1).strip()
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

        linked_pr = _extract_pr_number(summary)
        if fragment_pr is not None and linked_pr not in {None, fragment_pr}:
            anomalies.append(
                ReleaseImportAnomaly(
                    str(path),
                    line_number,
                    f"fragment filename PR {fragment_pr} conflicts with linked PR {linked_pr}",
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
    """Parse the frozen archive and every current fragment without mutating data.

    Args:
        repository_root: ComicPile repository root.

    Returns:
        Complete deterministic dry-run report for the source corpus.
    """
    sources = [repository_root / "docs" / "changelog.md"]
    fragments_dir = repository_root / "docs" / "changelog.d"
    if fragments_dir.exists():
        sources.extend(sorted(fragments_dir.glob("*.md")))

    report = ReleaseImportReport()
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
