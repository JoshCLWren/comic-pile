"""Tests for confidence-aware ComicVine identity repair."""

from datetime import UTC, date, datetime

from comic_pile.comicvine_identity_repair import (
    ComicVineCandidate,
    ComicVineRepairContext,
    decide_candidates,
    normalize_title,
    score_candidate,
)


def test_normalize_title_preserves_meaning_while_removing_format_noise() -> None:
    """Title normalization should handle punctuation, casing, and ampersands deterministically."""
    assert normalize_title("B.P.R.D.: Hell on Earth") == "b p r d hell on earth"
    assert normalize_title("Batman & Robin") == normalize_title("BATMAN and ROBIN")


def test_exact_cbl_identity_wins_when_candidate_is_internally_valid() -> None:
    """An embedded ComicVine issue ID should outrank fuzzy/local scoring after validation."""
    context = ComicVineRepairContext(title="X-Men", issue_label="12")
    first = score_candidate(context, ComicVineCandidate(issue_id=111, volume_id=1, volume_name="X-Men", issue_number="12"))
    embedded = score_candidate(context, ComicVineCandidate(issue_id=222, volume_id=2, volume_name="X-Men", issue_number="12"))
    decision = decide_candidates([first, embedded], embedded_cbl_issue_id=222)
    assert decision.status == "confirmed"
    assert decision.winner is not None
    assert decision.winner.candidate.issue_id == 222
    assert "embedded CBL" in decision.reason


def test_existing_confirmed_identity_is_never_replaced_by_fuzzy_candidate() -> None:
    """A later high-scoring candidate must not displace an existing confirmed mapping."""
    context = ComicVineRepairContext(title="Justice League America", issue_label="25", publisher="DC Comics", start_year=1987)
    existing = score_candidate(context, ComicVineCandidate(issue_id=100, volume_id=10, volume_name="Justice League America", issue_number="25", publisher="DC Comics", start_year=1987))
    challenger = score_candidate(context, ComicVineCandidate(issue_id=200, volume_id=20, volume_name="Justice League America", issue_number="25", publisher="DC Comics", start_year=1987, previous_issue_exists=True, next_issue_exists=True))
    decision = decide_candidates([challenger, existing], existing_confirmed_issue_id=100)
    assert decision.status == "confirmed"
    assert decision.winner is not None
    assert decision.winner.candidate.issue_id == 100


def test_special_human_label_can_match_issue_name_instead_of_number() -> None:
    """Special labels such as Revival should resolve through provider issue names."""
    score = score_candidate(
        ComicVineRepairContext(title="B.P.R.D.: War on Frogs", issue_label="Revival", publisher="Dark Horse Comics"),
        ComicVineCandidate(issue_id=819479, volume_id=122077, volume_name="B.P.R.D.: War on Frogs", issue_number="5", issue_name="Revival", publisher="Dark Horse Comics"),
    )
    assert score.rejection_reason is None
    assert "issue name matches human label" in score.evidence
    assert score.score >= 0.68


def test_candidate_without_matching_issue_number_or_name_is_rejected() -> None:
    """Volume title similarity alone must never establish issue identity."""
    score = score_candidate(ComicVineRepairContext(title="B.P.R.D.: The Dead", issue_label="6"), ComicVineCandidate(issue_id=55, volume_id=12, volume_name="B.P.R.D.: The Dead", issue_number="5"))
    assert score.score == 0
    assert score.rejection_reason is not None
    assert "does not contain" in score.rejection_reason


def test_post_snapshot_missing_issue_is_classified_as_stale_not_false_identity_failure() -> None:
    """A comic newer than the local snapshot should remain unresolved for live refresh."""
    score = score_candidate(
        ComicVineRepairContext(title="Absolute Batman", issue_label="21", snapshot_synced_at=datetime(2026, 1, 9, tzinfo=UTC), issue_expected_after=date(2026, 8, 1)),
        ComicVineCandidate(issue_id=1, volume_id=2, volume_name="Absolute Batman", issue_number="20"),
    )
    decision = decide_candidates([score])
    assert score.stale_snapshot is True
    assert score.rejection_reason is not None
    assert "live refresh" in score.rejection_reason
    assert decision.status == "unresolved"
    assert "snapshot may be stale" in decision.reason


def test_same_title_foreign_reprint_is_penalized_by_publisher_and_year() -> None:
    """Numeric coverage from a foreign reprint should not beat original-series evidence."""
    context = ComicVineRepairContext(title="X-Men", issue_label="12", publisher="Marvel", start_year=1991)
    original = score_candidate(context, ComicVineCandidate(issue_id=10, volume_id=100, volume_name="X-Men", issue_number="12", publisher="Marvel", start_year=1991))
    reprint = score_candidate(context, ComicVineCandidate(issue_id=20, volume_id=200, volume_name="X-Men", issue_number="12", publisher="Panini Comics", start_year=2002, previous_issue_exists=True, next_issue_exists=True))
    assert original.score > reprint.score
    decision = decide_candidates([reprint, original])
    assert decision.status == "confirmed"
    assert decision.winner is not None
    assert decision.winner.candidate.issue_id == 10


def test_tied_exact_title_candidates_remain_auditable_instead_of_using_rank() -> None:
    """FTS ordering must not silently break a tie between otherwise equivalent candidates."""
    context = ComicVineRepairContext(title="X-Men", issue_label="1")
    first = score_candidate(context, ComicVineCandidate(issue_id=101, volume_id=1, volume_name="X-Men", issue_number="1"))
    second = score_candidate(context, ComicVineCandidate(issue_id=202, volume_id=2, volume_name="X-Men", issue_number="1"))
    decision = decide_candidates([second, first])
    assert decision.status == "candidate"
    assert decision.winner is None
    assert [item.candidate.issue_id for item in decision.candidates] == [101, 202]


def test_issue_level_scoring_allows_one_thread_to_cross_volume_segments() -> None:
    """Different issues in one reading thread can independently confirm different provider volumes."""
    early = score_candidate(ComicVineRepairContext(title="Justice League America", issue_label="1", publisher="DC Comics", start_year=1987), ComicVineCandidate(issue_id=1, volume_id=10, volume_name="Justice League", issue_number="1", publisher="DC Comics", start_year=1987, segment_start="1", segment_end="6"))
    later = score_candidate(ComicVineRepairContext(title="Justice League America", issue_label="7", publisher="DC Comics", start_year=1987), ComicVineCandidate(issue_id=7, volume_id=20, volume_name="Justice League International", issue_number="7", publisher="DC Comics", start_year=1987, segment_start="7", segment_end="25"))
    assert early.candidate.volume_id != later.candidate.volume_id
    assert early.rejection_reason is None
    assert later.rejection_reason is None


def test_repeated_cbl_evidence_and_neighbor_coverage_are_explainable() -> None:
    """Supporting evidence should increase confidence while remaining visible in the audit trail."""
    score = score_candidate(
        ComicVineRepairContext(title="Planetary", issue_label="15", previous_issue_label="14", next_issue_label="16", repeated_cbl_count=2),
        ComicVineCandidate(issue_id=15, volume_id=99, volume_name="Planetary", issue_number="15", previous_issue_exists=True, next_issue_exists=True, segment_start="1", segment_end="27"),
    )
    assert "previous neighboring issue exists" in score.evidence
    assert "next neighboring issue exists" in score.evidence
    assert "supported by 2 distinct CBL observation(s)" in score.evidence
    assert score.candidate.segment_start == "1"
    assert score.candidate.segment_end == "27"
