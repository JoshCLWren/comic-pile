"""Tests for Familiar intent weighting from confirmed Taste Bank signals.

Covers the issue #1757 acceptance contract: transparent confirmed factors,
verdict strength ordering, rejected-signal neutrality, missing-metadata
neutrality, bounded-pool containment, and per-family matching plus caps.
"""

from __future__ import annotations

from comic_pile.familiar_weighting import (
    CONFIRMED_MATCH_BONUS,
    MAX_FAMILIAR_BONUS,
    SOMETIMES_MATCH_BONUS,
    CandidateFamiliarKeys,
    CreatorCreditKey,
    FamiliarFactor,
    TasteKind,
    TasteSignal,
    compute_familiar_factor,
    compute_familiar_factors,
    era_key_from_cover_date,
    extract_candidate_familiar_keys,
    normalize_key,
)


def _confirmed(kind: TasteKind, key: str) -> TasteSignal:
    """Build a confirmed explicit signal for tests."""
    return TasteSignal(kind=kind, key=key, verdict="confirmed")


def test_normalize_key_is_stable_across_provider_shapes() -> None:
    """Case, punctuation, and whitespace variants must produce equal keys."""
    assert normalize_key("Grant Morrison") == "grant morrison"
    assert normalize_key("  X-Men!") == "x men"
    assert normalize_key("X   Men") == "x men"
    assert normalize_key(None) == ""
    assert normalize_key(42) == ""


def test_era_keys_use_decade_buckets() -> None:
    """Cover dates must map onto stable decade buckets and reject junk."""
    assert era_key_from_cover_date("1987-03-12") == "1980s"
    assert era_key_from_cover_date("Published 1994") == "1990s"
    assert era_key_from_cover_date(2003) == "2000s"
    assert era_key_from_cover_date("unknown") == ""
    assert era_key_from_cover_date(None) == ""


def test_extraction_reads_comicvine_credit_shapes() -> None:
    """Extraction should read creator/character/team/publisher/era fields."""
    keys = extract_candidate_familiar_keys(
        {
            "creator_credits": [
                {"name": "Grant Morrison", "role": "writer"},
                {"name": "X-Men", "role": None},
            ],
            "person_credits": [{"name": "grant morrison!", "role": "writer, cover"}],
            "character_credits": [{"name": "Batman"}],
            "team_credits": [{"name": "Justice League"}],
            "publisher": {"name": "DC Comics"},
            "cover_date": "1987-05-01",
        }
    )

    creator_names = {credit.key for credit in keys.creator_roles}
    assert creator_names == {"grant morrison", "x men"}
    morrison = next(c for c in keys.creator_roles if c.key == "grant morrison")
    assert "writer" in morrison.roles
    assert keys.characters == frozenset({"batman"})
    assert keys.teams == frozenset({"justice league"})
    assert keys.publishers == frozenset({"dc comics"})
    assert keys.eras == frozenset({"1980s"})


def test_confirmed_creator_role_match_produces_transparent_factor() -> None:
    """A confirmed creator match must yield a positive factor with reasons."""
    keys = CandidateFamiliarKeys(
        creator_roles=(CreatorCreditKey(key="grant morrison", roles=frozenset({"writer"})),)
    )
    signals = [_confirmed("creator_role", "grant morrison")]

    factor = compute_familiar_factor(11, keys, signals)

    assert factor.candidate_id == 11
    assert factor.multiplier > 1.0
    assert factor.bonus == CONFIRMED_MATCH_BONUS
    assert not factor.capped
    assert len(factor.matches) == 1
    assert factor.matches[0].kind == "creator_role"
    assert factor.matches[0].key == "grant morrison"
    assert factor.matches[0].verdict == "confirmed"
    assert factor.matches[0].contribution == CONFIRMED_MATCH_BONUS


def test_sometimes_verdict_is_weaker_than_confirmed() -> None:
    """Qualified verdicts must rank strictly below explicit confirmations."""
    assert SOMETIMES_MATCH_BONUS < CONFIRMED_MATCH_BONUS

    keys = CandidateFamiliarKeys(characters=frozenset({"batman"}))
    confirmed = compute_familiar_factor(
        1,
        keys,
        [TasteSignal(kind="character", key="batman", verdict="confirmed")],
    )
    sometimes = compute_familiar_factor(
        2,
        keys,
        [TasteSignal(kind="character", key="batman", verdict="sometimes")],
    )

    assert sometimes.multiplier > 1.0
    assert sometimes.bonus < confirmed.bonus


def test_rejected_signal_never_boosts_a_candidate() -> None:
    """Rejected verdicts must not add any positive weight."""
    keys = CandidateFamiliarKeys(characters=frozenset({"batman"}))
    signals = [
        TasteSignal(kind="character", key="batman", verdict="rejected"),
        TasteSignal(kind="character", key="batman", verdict="sometimes"),
    ]

    rejected_only = compute_familiar_factor(
        5,
        keys,
        [TasteSignal(kind="character", key="batman", verdict="rejected")],
    )
    mixed = compute_familiar_factor(6, keys, signals)

    assert rejected_only.multiplier == 1.0
    assert rejected_only.matches == ()
    assert rejected_only.bonus == 0.0
    assert mixed.bonus == SOMETIMES_MATCH_BONUS


def test_missing_and_unconfirmed_metadata_fail_to_neutral() -> None:
    """No matches means exactly neutral; empty metadata never raises."""
    neutral = compute_familiar_factor(3, CandidateFamiliarKeys(), [_confirmed("team", "x-men")])
    empty = compute_familiar_factor(4, CandidateFamiliarKeys(), [])

    assert neutral.multiplier == 1.0
    assert neutral.matches == ()
    assert empty.multiplier == 1.0


def test_inferred_signals_contribute_nothing_until_permitted() -> None:
    """Unconfirmed inferred evidence must stay silent; verdicts rule."""
    from comic_pile.familiar_weighting import ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS

    assert ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS is False

    keys = CandidateFamiliarKeys(publishers=frozenset({"image comics"}))
    inferred = TasteSignal(
        kind="publisher",
        key="image comics",
        verdict="confirmed",
        source="inferred",
    )

    factor = compute_familiar_factor(7, keys, [inferred])

    assert factor.multiplier == 1.0
    assert factor.matches == ()


def test_inferred_signals_use_only_the_dedicated_tiny_effect_when_permitted() -> None:
    """If the gate opens later, inferred evidence stays capped and tiny."""
    import comic_pile.familiar_weighting as weighting

    keys = CandidateFamiliarKeys(characters=frozenset({"batman"}))
    inferred = TasteSignal(
        kind="character",
        key="batman",
        verdict="confirmed",
        source="inferred",
    )

    original_gate = weighting.ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS
    original_effect = weighting.INFERRED_UNCONFIRMED_CONTRIBUTION
    try:
        weighting.ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS = True
        weighting.INFERRED_UNCONFIRMED_CONTRIBUTION = 0.005
        factor = compute_familiar_factor(18, keys, [inferred])
    finally:
        weighting.ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS = original_gate
        weighting.INFERRED_UNCONFIRMED_CONTRIBUTION = original_effect

    assert factor.bonus == 0.005
    assert factor.multiplier == round(1.0 + 0.005, 6)
    assert factor.matches[0].contribution == 0.005
    assert factor.bonus < CONFIRMED_MATCH_BONUS


def test_character_and_team_matches_use_normalized_keys() -> None:
    """Character and team families must match through normalized keys."""
    character_keys = CandidateFamiliarKeys(characters=frozenset({"batman"}))
    team_keys = CandidateFamiliarKeys(teams=frozenset({"justice league"}))

    character_factor = compute_familiar_factor(
        8, character_keys, [_confirmed("character", "BATMAN!!")]
    )
    team_factor = compute_familiar_factor(
        9, team_keys, [_confirmed("team", "justice-league")]
    )

    assert character_factor.multiplier > 1.0
    assert character_factor.matches[0].kind == "character"
    assert team_factor.multiplier > 1.0
    assert team_factor.matches[0].kind == "team"


def test_publisher_matches_accept_flat_and_volume_shapes() -> None:
    """Publisher signals must hit both flat and volume-nested metadata."""
    flat = extract_candidate_familiar_keys({"publisher": {"name": "Image Comics"}})
    nested = extract_candidate_familiar_keys(
        {"volume": {"name": "Saga", "publisher": {"id": 4, "name": "image comics"}}}
    )

    signal = [_confirmed("publisher", "image comics")]

    assert flat.publishers == frozenset({"image comics"})
    assert compute_familiar_factor(10, flat, signal).multiplier > 1.0
    assert nested.publishers == frozenset({"image comics"})
    assert compute_familiar_factor(11, nested, signal).multiplier > 1.0


def test_era_signals_match_decade_buckets_from_metadata() -> None:
    """Era preferences must match the decade bucket of the cover date."""
    keys = extract_candidate_familiar_keys({"cover_date": "1989-11-01"})

    factor = compute_familiar_factor(12, keys, [_confirmed("era", "1980s")])

    assert factor.multiplier > 1.0
    assert factor.matches[0].key == "1980s"


def test_creator_role_narrowing_requires_role_overlap() -> None:
    """Role-narrowed creator signals only match credits holding that role."""
    writer_only = CandidateFamiliarKeys(
        creator_roles=(CreatorCreditKey(key="james robinson", roles=frozenset({"writer"})),)
    )
    inker_only = CandidateFamiliarKeys(
        creator_roles=(CreatorCreditKey(key="james robinson", roles=frozenset({"inks"})),)
    )
    signal = [
        TasteSignal(
            kind="creator_role",
            key="james robinson",
            verdict="confirmed",
            roles=frozenset({"writer"}),
        )
    ]

    assert compute_familiar_factor(13, writer_only, signal).multiplier > 1.0
    assert compute_familiar_factor(14, inker_only, signal).multiplier == 1.0


def test_total_bonus_is_capped_and_reported() -> None:
    """Many confirmed matches must cap at MAX_FAMILIAR_BONUS and flag it."""
    keys = CandidateFamiliarKeys(
        characters=frozenset({"batman"}),
        teams=frozenset({"justice league"}),
        publishers=frozenset({"dc comics"}),
        eras=frozenset({"1980s"}),
    )
    signals = [
        _confirmed("character", "batman"),
        _confirmed("team", "justice league"),
        _confirmed("publisher", "dc comics"),
        _confirmed("era", "1980s"),
    ]

    factor = compute_familiar_factor(15, keys, signals)

    raw_total = 4 * CONFIRMED_MATCH_BONUS
    assert raw_total > MAX_FAMILIAR_BONUS
    assert factor.capped is True
    assert factor.bonus == MAX_FAMILIAR_BONUS
    assert factor.multiplier == round(1.0 + MAX_FAMILIAR_BONUS, 6)
    assert len(factor.matches) == 4


def test_factors_never_introduce_candidates_outside_the_pool() -> None:
    """Output IDs must equal input IDs exactly: the pool stays bounded."""
    candidates = {
        21: CandidateFamiliarKeys(characters=frozenset({"batman"})),
        22: CandidateFamiliarKeys(),
    }
    signals = [
        _confirmed("character", "batman"),
        _confirmed("era", "1990s"),
        _confirmed("team", "avengers"),
    ]

    factors = compute_familiar_factors(candidates, signals)

    assert set(factors) == set(candidates)
    assert isinstance(factors[22], FamiliarFactor)
    assert factors[22].multiplier == 1.0


def test_duplicate_signals_count_once_at_strongest_strength() -> None:
    """Repeated evidence on one key must not stack beyond its strongest verdict."""
    keys = CandidateFamiliarKeys(characters=frozenset({"batman"}))
    signals = [
        TasteSignal(kind="character", key="batman", verdict="sometimes"),
        TasteSignal(kind="character", key="BATMAN!!", verdict="confirmed"),
        TasteSignal(kind="character", key="batman", verdict="confirmed"),
    ]

    factor = compute_familiar_factor(16, keys, signals)

    assert len(factor.matches) == 1
    assert factor.bonus == CONFIRMED_MATCH_BONUS


def test_malformed_metadata_fails_to_neutral_without_raising() -> None:
    """Provider shape garbage must degrade to neutral, never explode."""
    keys = extract_candidate_familiar_keys(
        {
            "creator_credits": "unexpected",
            "character_credits": [None, {"name": ""}, 42],
            "team_credits": {"name": "Justice League"},
            "publisher": 12345,
            "cover_date": ["not", "a", "date"],
            "volume": "unexpected",
        }
    )
    factor = compute_familiar_factor(17, keys, [_confirmed("character", "batman")])

    assert keys.characters == frozenset()
    assert keys.teams == frozenset()
    assert keys.publishers == frozenset()
    assert keys.eras == frozenset()
    assert factor.multiplier == 1.0
