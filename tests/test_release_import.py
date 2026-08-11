"""Tests for historical changelog import parsing and provenance."""

from pathlib import Path

from app.services.release_import import parse_changelog_source


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
    assert candidate.provenance()["raw_source"].startswith("- [#1077]")
    assert len(candidate.source_checksum) == 64


def test_archive_keeps_historical_entry_without_inventing_pr_identity() -> None:
    """Historical notes without explicit PR evidence remain representable without a fake mapping."""
    text = """## 2025-12-30

### Foundation

ComicPile launched with dice-driven reading queues.
"""

    candidates, anomalies = parse_changelog_source(Path("docs/changelog.md"), text)

    assert anomalies == []
    assert len(candidates) == 1
    assert candidates[0].source_pr_number is None
    assert candidates[0].summary == "ComicPile launched with dice-driven reading queues."


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
