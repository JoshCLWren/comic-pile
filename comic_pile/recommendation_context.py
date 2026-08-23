"""Versioned recommendation-context snapshots recorded on roll events.

Every contextually weighted roll persists a decision-time snapshot of what
weights were applied to which bounded candidates and why, so any roll can be
explained later from its recorded context. Pure-random and neutral control
rolls persist an explicit bypass snapshot instead of nothing, keeping the
event history self-describing.

Schema contract (``RECOMMENDATION_CONTEXT_VERSION``):

- ``version``: integer schema version of the payload.
- ``mode``: ``contextual_weighted`` when weights shaped the draw, otherwise
  ``bypassed``.
- ``bandwidth`` / ``intent``: the active reading-mode vocabulary.
- ``bandwidth_source`` / ``bandwidth_confidence``: provenance of the active
  bandwidth value so later inferred-bandwidth phases can replace it without a
  schema break.
- ``pool_size`` / ``die_size``: bounded candidate pool the weights apply to.
- ``selected_index`` / ``selected_thread_id`` / ``selected_weight``: the
  winning candidate and its exact final weight.
- ``candidates``: one compact entry per bounded candidate in pool order with
  ``thread_id``, final ``weight``, and short reason codes. Never carries full
  thread metadata; the payload stays bounded by the die pool.

Older payloads (including unversioned legacy snapshots) remain readable
through :func:`read_recommendation_context`, which normalizes whatever fields
it recognizes instead of rejecting unknown shapes.

This module is pure: no database, network, or framework dependencies.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

RECOMMENDATION_CONTEXT_VERSION = 1

Bandwidth = Literal["light", "balanced", "deep"]
Intent = Literal["balanced", "momentum", "familiar", "explore", "random"]

VALID_BANDWIDTHS: tuple[Bandwidth, ...] = ("light", "balanced", "deep")
VALID_INTENTS: tuple[Intent, ...] = ("balanced", "momentum", "familiar", "explore", "random")

DEFAULT_BANDWIDTH: Bandwidth = "balanced"
DEFAULT_INTENT: Intent = "balanced"

WEIGHTING_MODE_WEIGHTED = "contextual_weighted"
WEIGHTING_MODE_BYPASSED = "bypassed"

BANDWIDTH_SOURCE_REQUEST = "request"
BANDWIDTH_SOURCE_DEFAULT = "default"

#: Confidence recorded when the reader explicitly supplied the bandwidth.
REQUESTED_BANDWIDTH_CONFIDENCE = 1.0

EFFORT_LOW = "low"
EFFORT_MEDIUM = "medium"
EFFORT_HIGH = "high"
EFFORT_UNKNOWN = "unknown"

#: Unread-issue-count bands used as the current effort proxy until observed
#: per-title reading times replace them (roadmap #1685).
EFFORT_LOW_MAX_UNREAD = 3
EFFORT_MEDIUM_MAX_UNREAD = 10

NEUTRAL_WEIGHT = 1.0

#: Final candidate weight per (bandwidth, effort band). Balanced is neutral by
#: contract; light favors low-effort candidates; deep favors high-effort ones.
#: Unknown effort always stays neutral because it cannot justify a nudge.
BANDWIDTH_EFFORT_WEIGHTS: dict[str, dict[str, float]] = {
    "light": {EFFORT_LOW: 3.0, EFFORT_MEDIUM: 1.5, EFFORT_HIGH: 0.5, EFFORT_UNKNOWN: NEUTRAL_WEIGHT},
    "balanced": {
        EFFORT_LOW: NEUTRAL_WEIGHT,
        EFFORT_MEDIUM: NEUTRAL_WEIGHT,
        EFFORT_HIGH: NEUTRAL_WEIGHT,
        EFFORT_UNKNOWN: NEUTRAL_WEIGHT,
    },
    "deep": {EFFORT_LOW: 0.5, EFFORT_MEDIUM: 1.5, EFFORT_HIGH: 3.0, EFFORT_UNKNOWN: NEUTRAL_WEIGHT},
}

BYPASS_RANDOM_INTENT = "random_intent"
BYPASS_BALANCED_NEUTRAL = "balanced_neutral"
BYPASS_INVALID_WEIGHTS = "invalid_weights"
BYPASS_UNIFORM_POOL = "uniform_pool"


def classify_effort(unread_count: int | None) -> str:
    """Classify one candidate's reading effort from its unread-issue count.

    Args:
        unread_count: Number of unread issues for the candidate, or ``None``
            when the count could not be determined.

    Returns:
        One of ``"low"``, ``"medium"``, ``"high"``, or ``"unknown"``.
    """
    if unread_count is None:
        return EFFORT_UNKNOWN
    if unread_count <= EFFORT_LOW_MAX_UNREAD:
        return EFFORT_LOW
    if unread_count <= EFFORT_MEDIUM_MAX_UNREAD:
        return EFFORT_MEDIUM
    return EFFORT_HIGH


def normalize_bandwidth(value: str | None) -> Bandwidth:
    """Normalize a raw bandwidth value to the canonical defaulting form.

    Args:
        value: Raw bandwidth, or ``None`` for the balanced default.

    Returns:
        The canonical bandwidth string.

    Raises:
        ValueError: If the value is not a known bandwidth.
    """
    if value is None:
        return DEFAULT_BANDWIDTH
    for bandwidth in VALID_BANDWIDTHS:
        if value == bandwidth:
            return bandwidth
    raise ValueError(f"Unknown bandwidth: {value!r}")


def normalize_intent(value: str | None) -> Intent:
    """Normalize a raw intent value to the canonical defaulting form.

    Args:
        value: Raw intent, or ``None`` for the balanced default.

    Returns:
        The canonical intent string.

    Raises:
        ValueError: If the value is not a known intent.
    """
    if value is None:
        return DEFAULT_INTENT
    for intent in VALID_INTENTS:
        if value == intent:
            return intent
    raise ValueError(f"Unknown intent: {value!r}")


@dataclass(frozen=True)
class SelectionPlan:
    """Resolved decision for one bounded-pool selection.

    Attributes:
        index: Zero-based index of the selected candidate in pool order.
        weights: Exact final per-candidate weights used for the draw. Neutral
            weights are recorded for control paths so persisted context always
            shows explicit neutral weighting rather than an absence.
        weighting_applied: Whether these weights actually shaped the draw.
        mode: ``contextual_weighted`` or ``bypassed``.
        bypass_reason: Compact reason code when ``weighting_applied`` is false,
            else ``None``.
        effort_bands: Per-candidate effort classification in pool order.
    """

    index: int
    weights: tuple[float, ...]
    weighting_applied: bool
    mode: str
    bypass_reason: str | None
    effort_bands: tuple[str, ...]


def _uniform_draw(pool_size: int, rng: random.Random | None) -> int:
    """Draw one uniform index exactly like the legacy roll endpoint."""
    source = rng if rng is not None else random
    return source.randint(0, pool_size - 1)


def _weighted_draw(
    pool_size: int, weights: Sequence[float], rng: random.Random | None
) -> int:
    """Draw one index proportionally to the validated positive weights."""
    source = rng if rng is not None else random
    return source.choices(range(pool_size), weights=list(weights), k=1)[0]


def resolve_selection_plan(
    efforts: Sequence[int],
    *,
    bandwidth: str | None = None,
    intent: str | None = None,
    rng: random.Random | None = None,
) -> SelectionPlan:
    """Resolve the selection path and final weights for one bounded pool.

    Path rules:

    1. The ``random`` intent bypasses contextual weighting completely and
       reproduces the legacy uniform draw inside the bounded pool.
    2. ``balanced`` bandwidth stays neutral until a phase explicitly adds a
       factor; the draw remains uniform but records neutral weights.
    3. Any other bandwidth applies its documented per-effort weights. If those
       weights are unusable, or they turn out uniform because every candidate
       shares one effort band, the selection falls back safely to uniform and
       records the matching bypass reason.

    Args:
        efforts: Unread-issue counts aligned with the bounded pool order.
        bandwidth: Active bandwidth, or ``None`` for balanced.
        intent: Active intent, or ``None`` for balanced.
        rng: Optional seeded ``random.Random`` for deterministic tests;
            defaults to the shared stdlib ``random`` module.

    Returns:
        A :class:`SelectionPlan` whose ``weights`` are the exact values passed
        to the selection draw.

    Raises:
        ValueError: If the pool is empty or bandwidth/intent are unknown.
    """
    if not efforts:
        raise ValueError("efforts must contain at least one candidate")

    resolved_bandwidth = normalize_bandwidth(bandwidth)
    resolved_intent = normalize_intent(intent)
    pool_size = len(efforts)
    effort_bands = tuple(classify_effort(effort) for effort in efforts)

    if resolved_intent == "random":
        return SelectionPlan(
            index=_uniform_draw(pool_size, rng),
            weights=tuple(NEUTRAL_WEIGHT for _ in efforts),
            weighting_applied=False,
            mode=WEIGHTING_MODE_BYPASSED,
            bypass_reason=BYPASS_RANDOM_INTENT,
            effort_bands=effort_bands,
        )

    if resolved_bandwidth == "balanced":
        return SelectionPlan(
            index=_uniform_draw(pool_size, rng),
            weights=tuple(NEUTRAL_WEIGHT for _ in efforts),
            weighting_applied=False,
            mode=WEIGHTING_MODE_BYPASSED,
            bypass_reason=BYPASS_BALANCED_NEUTRAL,
            effort_bands=effort_bands,
        )

    band_weights = BANDWIDTH_EFFORT_WEIGHTS[resolved_bandwidth]
    weights = tuple(band_weights[band] for band in effort_bands)

    if not all(math.isfinite(weight) and weight > 0.0 for weight in weights):
        return SelectionPlan(
            index=_uniform_draw(pool_size, rng),
            weights=tuple(NEUTRAL_WEIGHT for _ in efforts),
            weighting_applied=False,
            mode=WEIGHTING_MODE_BYPASSED,
            bypass_reason=BYPASS_INVALID_WEIGHTS,
            effort_bands=effort_bands,
        )

    if len(set(weights)) == 1:
        return SelectionPlan(
            index=_uniform_draw(pool_size, rng),
            weights=weights,
            weighting_applied=False,
            mode=WEIGHTING_MODE_BYPASSED,
            bypass_reason=BYPASS_UNIFORM_POOL,
            effort_bands=effort_bands,
        )

    return SelectionPlan(
        index=_weighted_draw(pool_size, weights, rng),
        weights=weights,
        weighting_applied=True,
        mode=WEIGHTING_MODE_WEIGHTED,
        bypass_reason=None,
        effort_bands=effort_bands,
    )


def candidate_reason_codes(plan: SelectionPlan, position: int) -> tuple[str, ...]:
    """Return the compact reason codes explaining one candidate's weight.

    Args:
        plan: The resolved selection plan.
        position: Zero-based candidate position in pool order.

    Returns:
        Short codes such as ``("effort:low", "w:up")`` for weighted rolls or
        ``("effort:medium", "bypass:random_intent")`` for control rolls.
    """
    effort_code = f"effort:{plan.effort_bands[position]}"
    if plan.weighting_applied:
        weight = plan.weights[position]
        if weight > NEUTRAL_WEIGHT:
            direction = "up"
        elif weight < NEUTRAL_WEIGHT:
            direction = "down"
        else:
            direction = "flat"
        return (effort_code, f"w:{direction}")
    return (effort_code, f"bypass:{plan.bypass_reason}")


def build_recommendation_context(
    *,
    thread_ids: Sequence[int],
    die_size: int,
    bandwidth: str | None,
    intent: str | None,
    plan: SelectionPlan,
    bandwidth_source: str = BANDWIDTH_SOURCE_DEFAULT,
    bandwidth_confidence: float | None = None,
) -> dict[str, object]:
    """Build the versioned recommendation-context payload for one roll.

    The payload stays bounded to the die pool: one compact entry per bounded
    candidate, never full thread metadata.

    Args:
        thread_ids: Candidate thread IDs in bounded pool order.
        die_size: Die size that bounded the pool.
        bandwidth: Raw active bandwidth (normalized here).
        intent: Raw active intent (normalized here).
        plan: Resolved selection plan carrying the exact final weights.
        bandwidth_source: Provenance of the bandwidth value.
        bandwidth_confidence: Optional confidence in the bandwidth value.

    Returns:
        A JSON-serializable snapshot dict tagged with the current schema
        version.

    Raises:
        ValueError: If thread_ids and plan weights disagree in length.
    """
    if len(thread_ids) != len(plan.weights):
        raise ValueError("thread_ids must align with the selection plan weights")

    candidates: list[dict[str, object]] = []
    for position, thread_id in enumerate(thread_ids):
        candidates.append(
            {
                "thread_id": thread_id,
                "weight": round(float(plan.weights[position]), 6),
                "reasons": list(candidate_reason_codes(plan, position)),
            }
        )

    return {
        "version": RECOMMENDATION_CONTEXT_VERSION,
        "mode": plan.mode,
        "bandwidth": normalize_bandwidth(bandwidth),
        "intent": normalize_intent(intent),
        "bandwidth_source": bandwidth_source,
        "bandwidth_confidence": bandwidth_confidence,
        "die_size": die_size,
        "pool_size": len(candidates),
        "selected_index": plan.index,
        "selected_thread_id": thread_ids[plan.index],
        "selected_weight": round(float(plan.weights[plan.index]), 6),
        "candidates": candidates,
    }


@dataclass(frozen=True)
class RecommendationContextView:
    """Normalized read model over any stored recommendation-context version.

    Attributes:
        version: Schema version of the stored payload; ``0`` for unversioned
            legacy snapshots.
        readable: True when the payload yielded at least the selected-weight
            explanation, False for unrecognized payloads.
        mode: Weighting mode, when present.
        bandwidth: Active bandwidth, when present.
        intent: Active intent, when present.
        selected_thread_id: Winning thread ID, when determinable.
        selected_index: Winning zero-based pool index, when determinable.
        selected_weight: Winning final weight, when determinable.
        weighting_applied: Whether weights shaped the draw, when determinable.
        candidate_weights: Per-candidate ``(thread_id, weight)`` pairs.
        candidate_reason_codes: Per-candidate reason-code tuples keyed in pool
            order alongside :attr:`candidate_weights`.
    """

    version: int
    readable: bool
    mode: str | None = None
    bandwidth: str | None = None
    intent: str | None = None
    selected_thread_id: int | None = None
    selected_index: int | None = None
    selected_weight: float | None = None
    weighting_applied: bool | None = None
    candidate_weights: tuple[tuple[int | None, float], ...] = ()
    candidate_reason_codes: tuple[tuple[str, ...], ...] = ()


def _coerce_positive_float(value: object) -> float | None:
    """Coerce a stored weight to a finite positive float, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight) or weight <= 0.0:
        return None
    return weight


def _coerce_int(value: object) -> int | None:
    """Coerce a stored identifier/index to an int, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def read_recommendation_context(payload: object) -> RecommendationContextView:
    """Read any stored recommendation-context payload tolerantly.

    Current-version payloads are fully explained. Unversioned legacy payloads
    are treated as version 0 and read best-effort. Newer or partially malformed
    payloads still yield every field that can be recognized, so historical
    context versions never become unreadable.

    Args:
        payload: Stored JSON payload (dict-like) from a roll event.

    Returns:
        A :class:`RecommendationContextView`; ``readable`` is False only when
        the payload is not even a mapping.
    """
    if not isinstance(payload, Mapping):
        return RecommendationContextView(version=0, readable=False)

    raw_version = payload.get("version")
    version = _coerce_int(raw_version)
    if version is None:
        version = 0

    mode = payload.get("mode")
    bandwidth = payload.get("bandwidth")
    intent = payload.get("intent")

    weighting_applied: bool | None = None
    if mode == WEIGHTING_MODE_WEIGHTED:
        weighting_applied = True
    elif mode == WEIGHTING_MODE_BYPASSED:
        weighting_applied = False

    selected_weight = _coerce_positive_float(payload.get("selected_weight"))
    candidates = payload.get("candidates")
    candidate_weights: list[tuple[int | None, float]] = []
    candidate_reasons: list[tuple[str, ...]] = []
    if isinstance(candidates, list):
        for entry in candidates:
            if not isinstance(entry, Mapping):
                continue
            weight = _coerce_positive_float(entry.get("weight"))
            if weight is None:
                continue
            candidate_weights.append((_coerce_int(entry.get("thread_id")), weight))
            reasons = entry.get("reasons")
            if isinstance(reasons, list):
                candidate_reasons.append(
                    tuple(code for code in reasons if isinstance(code, str))
                )
            else:
                candidate_reasons.append(())

    return RecommendationContextView(
        version=version,
        readable=True,
        mode=mode if isinstance(mode, str) else None,
        bandwidth=bandwidth if isinstance(bandwidth, str) else None,
        intent=intent if isinstance(intent, str) else None,
        selected_thread_id=_coerce_int(payload.get("selected_thread_id")),
        selected_index=_coerce_int(payload.get("selected_index")),
        selected_weight=selected_weight,
        weighting_applied=weighting_applied,
        candidate_weights=tuple(candidate_weights),
        candidate_reason_codes=tuple(candidate_reasons),
    )
