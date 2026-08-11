"""Tests for historical changelog import parsing and provenance."""

from pathlib import Path
import re

from app.services.release_import import audit_changelog_corpus, parse_changelog_source

_FRAGMENT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(\d+)\.md$")


def test_fragment_preserves_filename_pr_and_provenance() -> None:
    """A valid fragment keeps its authoritative filename identity and exact source audit data."""
    text = """## 2026-08-11

### Roll

- [#1077](https://github.com/JoshCLWren/comic-pile/pull/1077) repairs feedback E2E.
"""

    candidates, anomalies = parse_changelog_source(
        Path("docs/changelog.d/2026-08-11-1077.md"),
        text,
    )

    assert anomalies == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_pr_number == 1077
    assert candidate.source_date == "2026-08-11"
    assert candidate.category == "Roll"
    assert candidate.source_order == 0
    assert candidate.provenance()["raw_source"] == (
        "- [#1077](https://github.com/JoshCLWren/comic-pile/pull/1077) repairs feedback E2E."
    )
    assert len(candidate.source_checksum) == 64


def test_archive_keeps_historical_entry_without_inventing_pr_identity() -> None:
    """Historical notes without explicit PR evidence remain representable without a fake mapping."""
    text = """## 2025-12-30

**Foundation**

ComicPile launched with dice-driven reading queues.
"""

    candidates, anomalies = parse_changelog_source(Path("docs/changelog.md"), text)

    assert anomalies == []
    assert len(candidates) == 1
    assert candidates[0].source_pr_number is None
    assert candidates[0].category == "Foundation"
    assert candidates[0].summary == "ComicPile launched with dice-driven reading queues."


def test_archive_preserves_bold_feature_area_heading() -> None:
    """The frozen archive's bold headings remain feature areas instead of becoming notes."""
    text = """## 2026-08-06

**Crossovers and reading order**

- Reading-order groups are now presented as Crossovers.
"""

    candidates, anomalies = parse_changelog_source(Path("docs/changelog.md"), text)

    assert anomalies == []
    assert len(candidates) == 1
    assert candidates[0].category == "Crossovers and reading order"


def test_archive_multi_pr_entry_is_preserved_as_ambiguous() -> None:
    """A historical bullet with several PRs stays readable without inventing one identity."""
    text = """## 2026-08-05

**Maintenance**

- Fixed both paths ([#810](https://github.com/JoshCLWren/comic-pile/pull/810), [#811](https://github.com/JoshCLWren/comic-pile/pull/811)).
"""

    candidates, anomalies = parse_changelog_source(Path("docs/changelog.md"), text)

    assert len(candidates) == 1
    assert candidates[0].source_pr_number is None
    assert any("multiple PRs" in anomaly.message for anomaly in anomalies)


def test_conflicting_fragment_identity_is_reported_instead_of_guessed() -> None:
    """A filename/link disagreement becomes an anomaly and never silently rewrites provenance."""
    text = """## 2026-08-11

### Reliability

- [#999](https://github.com/JoshCLWren/comic-pile/pull/999) conflicting note.
"""

    candidates, anomalies = parse_changelog_source(
        Path("docs/changelog.d/2026-08-11-1078.md"),
        text,
    )

    assert candidates == []
    assert any("conflicts with linked PR 999" in anomaly.message for anomaly in anomalies)


def test_fragment_date_mismatch_is_preserved_as_anomaly() -> None:
    """Filename and heading date disagreements stay visible to the dry-run audit."""
    text = """## 2026-08-10

### Reliability

- fixed a thing
"""

    candidates, anomalies = parse_changelog_source(
        Path("docs/changelog.d/2026-08-11-1078.md"),
        text,
    )

    assert len(candidates) == 1
    assert candidates[0].source_date == "2026-08-10"
    assert any("does not match filename date" in anomaly.message for anomaly in anomalies)


def test_repository_changelog_corpus_represents_every_valid_fragment() -> None:
    """The dry-run parser covers the real frozen archive and every valid current fragment."""
    repository_root = Path(__file__).resolve().parents[1]
    report = audit_changelog_corpus(repository_root)
    fragment_paths: dict[str, int] = {}
    for path in (repository_root / "docs" / "changelog.d").glob("*.md"):
        match = _FRAGMENT_RE.fullmatch(path.name)
        if match is not None:
            fragment_paths[str(path.relative_to(repository_root))] = int(match.group(1))

    assert report.candidates
    assert any(candidate.category != "General" for candidate in report.candidates)
    candidates_by_path = {candidate.source_path: candidate for candidate in report.candidates}
    assert fragment_paths.keys() <= candidates_by_path.keys()
    for source_path, pr_number in fragment_paths.items():
        assert candidates_by_path[source_path].source_pr_number == pr_number
