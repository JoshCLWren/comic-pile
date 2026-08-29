"""Inferred Taste Bank affinity and confidence from reading history.

This is the calculation layer for issue #1745. It derives cautious taste
signals from a reader's own rating/acceptance history instead of silently
treating one good comic as a permanent creator preference.

The math is intentionally conservative and fully deterministic:

- Affinity is the mean rating lift over the reader's own baseline, normalized
  into ``[-1, 1]``. Positive means the reader rates the feature above their
  usual baseline; negative means below.
- Confidence combines three factors so that a pattern must be *repeated*,
  *consistent*, and *diverse* before it is treated as a real signal:

  - evidence factor: more observations raise confidence, but it saturates;
  - diversity factor: evidence spread across distinct threads/runs raises
    confidence more than the same number of reads stacked inside one thread
    (this is what stops a single-run cluster from looking authoritative);
  - consistency factor: low spread and one-directional agreement raise
    confidence, mixed signs lower it.

Explicit user verdicts (``confirmed``/``sometimes``/``rejected``) are never
written here. Persistence helpers in the repository layer update only the
inferred columns, so a verdict survives every recomputation.

All functions are pure (stdlib only) so the contract can be covered by
focused unit tests without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev

from app.services.comicvine_taste import extract_taste_features


@dataclass(frozen=True)
class InferenceConfig:
    """Tunable constants for the inferred-signal calculation.

    Attributes:
        affinity_normalization: Sustained rating lift (in stars over baseline)
            that maps to a full ``|affinity|`` of 1.0.
        evidence_ceil: Number of observations at which the evidence factor
            saturates at 1.0.
        diversity_ceil: Number of distinct threads/runs at which the diversity
            factor saturates at 1.0.
        consistency_std_ceil: Rating-lift standard deviation that drives the
            consistency factor to 0.0.
        accept_bonus: Lift contributed by one accepted roll with no rating.
        accept_penalty: Lift subtracted by one rejected roll with no rating.
        weight_evidence: Confidence weight for the evidence factor.
        weight_diversity: Confidence weight for the diversity factor.
        weight_consistency: Confidence weight for the consistency factor.
        neutral_rating_baseline: Baseline used when the reader has no ratings.
    """

    affinity_normalization: float = 1.5
    evidence_ceil: int = 10
    diversity_ceil: int = 5
    consistency_std_ceil: float = 1.0
    accept_bonus: float = 0.3
    accept_penalty: float = 0.3
    weight_evidence: float = 0.4
    weight_diversity: float = 0.3
    weight_consistency: float = 0.2
    neutral_rating_baseline: float = 3.0


DEFAULT_INFERENCE_CONFIG = InferenceConfig()


@dataclass
class TasteObservation:
    """One occurrence of a feature in a user's reading history.

    Attributes:
        thread_id: Stable thread/run id, used for evidence diversity. May be
            ``None`` when the source cannot identify a thread.
        rating: The user's rating for the read (stars), or ``None``.
        accepted: Whether the roll was accepted, or ``None`` when unknown.
    """

    thread_id: int | None
    rating: float | None = None
    accepted: bool | None = None


@dataclass
class InferredSignal:
    """Computed inferred state for one taste feature.

    Attributes:
        affinity_estimate: Mean lift over baseline, clamped to ``[-1, 1]``.
        confidence: Statistical confidence in the estimate, in ``[0, 1]``.
        evidence_count: Observations carrying a usable rating or acceptance.
        distinct_thread_count: Distinct threads/runs among the observations.
    """

    affinity_estimate: float
    confidence: float
    evidence_count: int
    distinct_thread_count: int


@dataclass
class FeatureEvidence:
    """Accumulated observations for one normalized feature key.

    Attributes:
        display_name: Human-readable label for the feature.
        observations: Every occurrence of the feature in reading history.
    """

    display_name: str
    observations: list[TasteObservation]


@dataclass
class FeatureResult:
    """Computed inferred signal keyed for persistence.

    Attributes:
        signal_type: One of the canonical ``taste_signal`` signal types.
        external_key: Stable normalized external key for the feature.
        display_name: Human-readable label for the feature.
        inferred: The computed inferred state.
    """

    signal_type: str
    external_key: str
    display_name: str
    inferred: InferredSignal


def _observation_delta(
    observation: TasteObservation,
    baseline_rating: float,
    config: InferenceConfig,
) -> float | None:
    """Convert one observation into a lift-over-baseline signal.

    Args:
        observation: The single history occurrence.
        baseline_rating: The reader's mean rating across all reads.
        config: Active tuning constants.

    Returns:
        The rating lift contributed by this observation, or ``None`` when the
        observation carries no usable evidence.
    """
    if observation.rating is not None:
        return observation.rating - baseline_rating
    if observation.accepted is True:
        return config.accept_bonus
    if observation.accepted is False:
        return -config.accept_penalty
    return None


def compute_inferred_signal(
    observations: list[TasteObservation],
    baseline_rating: float,
    config: InferenceConfig | None = None,
) -> InferredSignal:
    """Compute inferred affinity and confidence from feature observations.

    The function is pure and deterministic. It never reads or writes any
    verdict state; verdicts are the caller's responsibility.

    Args:
        observations: Every occurrence of the feature in a reader's history.
        baseline_rating: The reader's own mean rating (lift is measured
            against this, not an absolute scale).
        config: Tuning constants; defaults to :data:`DEFAULT_INFERENCE_CONFIG`.

    Returns:
        The inferred ``affinity_estimate`` (``[-1, 1]``), ``confidence``
        (``[0, 1]``), ``evidence_count``, and ``distinct_thread_count``.
    """
    config = config or DEFAULT_INFERENCE_CONFIG
    usable = [
        delta
        for observation in observations
        if (delta := _observation_delta(observation, baseline_rating, config))
        is not None
    ]
    if not usable:
        return InferredSignal(
            affinity_estimate=0.0,
            confidence=0.0,
            evidence_count=0,
            distinct_thread_count=0,
        )

    mean_delta = fmean(usable)
    affinity_estimate = max(-1.0, min(1.0, mean_delta / config.affinity_normalization))

    evidence_factor = min(len(usable) / config.evidence_ceil, 1.0)
    distinct_threads = {o.thread_id for o in observations if o.thread_id is not None}
    diversity_factor = min(len(distinct_threads) / config.diversity_ceil, 1.0)

    if len(usable) == 1:
        consistency_factor = 0.5
    else:
        std = pstdev(usable)
        consistency_factor = max(0.0, 1.0 - std / config.consistency_std_ceil)
        nonzero = [delta for delta in usable if delta != 0.0]
        if nonzero and mean_delta != 0.0:
            same_sign = sum(
                1 for delta in nonzero if (delta > 0) == (mean_delta > 0)
            ) / len(nonzero)
            # Mixed-direction evidence must not look perfectly consistent.
            consistency_factor *= 0.5 + 0.5 * same_sign

    # Apply distinct thread multiplier to penalize single-thread evidence
    base_confidence = max(
        0.0,
        min(
            1.0,
            config.weight_evidence * evidence_factor
            + config.weight_diversity * diversity_factor
            + config.weight_consistency * consistency_factor,
        ),
    )
    distinct_multiplier = 1.0 if len(distinct_threads) >= 2 else 0.5
    confidence = base_confidence * distinct_multiplier

    return InferredSignal(
        affinity_estimate=affinity_estimate,
        confidence=confidence,
        evidence_count=len(usable),
        distinct_thread_count=len(distinct_threads),
    )


def _iter_features(features: dict[str, object]) -> list[tuple[str, str, str]]:
    """Yield ``(signal_type, external_key, display_name)`` for extracted features.

    Args:
        features: Output of :func:`app.services.comicvine_taste.extract_taste_features`.

    Returns:
        One tuple per distinct normalized feature (creators, characters,
        teams, publisher, and publication era).
    """
    emitted: list[tuple[str, str, str]] = []

    creators = features.get("creators")
    if isinstance(creators, list):
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            creator_id = creator.get("id")
            name = creator.get("name")
            if creator_id is None or not name:
                continue
            role = creator.get("role")
            key = f"creator:{role}:{creator_id}" if role else f"creator:{creator_id}"
            emitted.append(("creator", key, str(name)))

    characters = features.get("characters")
    if isinstance(characters, list):
        for character in characters:
            if not isinstance(character, dict):
                continue
            character_id = character.get("id")
            name = character.get("name")
            if character_id is None or not name:
                continue
            emitted.append(("character", f"character:{character_id}", str(name)))

    teams = features.get("teams")
    if isinstance(teams, list):
        for team in teams:
            if not isinstance(team, dict):
                continue
            team_id = team.get("id")
            name = team.get("name")
            if team_id is None or not name:
                continue
            emitted.append(("team", f"team:{team_id}", str(name)))

    publisher = features.get("publisher")
    if isinstance(publisher, dict):
        publisher_id = publisher.get("id")
        name = publisher.get("name")
        if publisher_id is not None and name:
            emitted.append(("publisher", f"publisher:{publisher_id}", str(name)))

    era = features.get("publication_era")
    if era:
        emitted.append(("era", f"era:{era}", str(era)))

    return emitted


def recompute_from_reading_history(
    baseline_rating: float,
    rated_items: list[dict[str, object]],
    config: InferenceConfig | None = None,
) -> list[FeatureResult]:
    """Compute inferred signals for every feature in a reader's history.

    Each rated item is one read issue. Features are extracted from its
    confirmed ComicVine metadata and de-duplicated per ``(feature, thread,
    issue)`` so highly correlated metadata from one issue cannot double-count
    the same evidence.

    Args:
        baseline_rating: The reader's mean rating across all reads.
        rated_items: List of dicts with keys ``thread_id`` (int | None),
            ``issue_id`` (int | None), ``rating`` (float | None),
            ``accepted`` (bool | None), ``issue_metadata`` (dict), and
            ``volume_metadata`` (dict | None).
        config: Tuning constants; defaults to :data:`DEFAULT_INFERENCE_CONFIG`.

    Returns:
        One :class:`FeatureResult` per feature that appeared in the history,
        sorted by signal type then external key for determinism.
    """
    config = config or DEFAULT_INFERENCE_CONFIG
    grouped: dict[tuple[str, str], FeatureEvidence] = {}
    seen: set[tuple[str, str, object, object]] = set()

    for item in rated_items:
        issue_value = item.get("issue_metadata")
        if not isinstance(issue_value, dict):
            issue_value = {}
        volume_value = item.get("volume_metadata")
        if not isinstance(volume_value, dict):
            volume_value = None
        features = extract_taste_features(issue_value, volume_value)

        thread_id = item.get("thread_id")
        if not isinstance(thread_id, int):
            thread_id = None
        issue_id = item.get("issue_id")
        if not isinstance(issue_id, int):
            issue_id = None
        rating = item.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, (int, float)):
            rating = None
        elif isinstance(rating, int):
            rating = float(rating)
        accepted = item.get("accepted")
        if not isinstance(accepted, bool):
            accepted = None
        observation = TasteObservation(
            thread_id=thread_id,
            rating=rating,
            accepted=accepted,
        )

        for signal_type, external_key, display_name in _iter_features(features):
            dedupe = (signal_type, external_key, thread_id, issue_id)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            evidence = grouped.setdefault(
                (signal_type, external_key),
                FeatureEvidence(display_name=display_name, observations=[]),
            )
            evidence.observations.append(observation)

    results: list[FeatureResult] = []
    for (signal_type, external_key), evidence in grouped.items():
        inferred = compute_inferred_signal(evidence.observations, baseline_rating, config)
        results.append(
            FeatureResult(
                signal_type=signal_type,
                external_key=external_key,
                display_name=evidence.display_name,
                inferred=inferred,
            )
        )

    results.sort(key=lambda result: (result.signal_type, result.external_key))
    return results


__all__ = [
    "DEFAULT_INFERENCE_CONFIG",
    "FeatureEvidence",
    "FeatureResult",
    "InferenceConfig",
    "InferredSignal",
    "TasteObservation",
    "compute_inferred_signal",
    "recompute_from_reading_history",
]
