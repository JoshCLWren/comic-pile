"""Pure projection from persisted recommendation reason codes to human-readable explanations.

This module translates stable decision-time context factors recorded during roll
selection into concise, user-facing explanation strings. It is intentionally
decoupled from selection logic and mutable runtime state — every explanation is
derived from the exact context persisted at decision time, never recomputed.

Graceful degradation:
- Unknown/legacy reason codes fall back to a single generic explanation.
- Missing expected keys in the context dict are silently skipped.
- Non-dict or absent `recommendation_context` yields an empty explanation list
  rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_BANDWIDTH_EXPLANATIONS: dict[str, tuple[str, str | None]] = {
    "band_light": ("Quick read", "~11-minute read"),
    "band_balanced": ("Medium read", None),
    "band_deep": ("Deep read", "Settling in for an extended session"),
}

_INTENT_EXPLANATIONS: dict[str, tuple[str, str | None]] = {
    "intent_balanced": ("Balanced pick", None),
    "intent_momentum": ("Recent series momentum", None),
    "intent_familiar": ("Creator you confirmed you like", None),
    "intent_explore": ("Novel but connected to your tastes", None),
    "intent_random": ("No weighting applied", "Pure random selection"),
}

_SELECTION_EXPLANATIONS: dict[str, tuple[str, str | None]] = {
    "random": ("Pure random", "Weighting was bypassed"),
    "override": ("Manual pick", "Directly chosen"),
}

_TASTE_BANK_EXPLANATIONS: dict[str, tuple[str, str | None]] = {
    "taste_high_affinity": ("Strong affinity", None),
    "taste_confirmed_creator": ("Creator you confirmed you like", None),
    "taste_confirmed_character": ("Character profile confirmed", None),
    "taste_confirmed_team": ("Team profile confirmed", None),
    "taste_confirmed_era": ("Era preference confirmed", None),
    "taste_novel_adjacent": ("Novel but connected to your tastes", None),
    "taste_series_momentum": ("Recent series momentum", None),
    "taste_near_completion": ("Near completion — finish strong", None),
}

_PRIMARY_SCORE_EXPLANATIONS: dict[str, tuple[str, str | None]] = {
    "score_affinity_strong": ("Strong affinity", None),
    "score_affinity_moderate": ("Matches your history", None),
    "score_recency_boost": ("Recently updated", None),
    "score_staleness_penalty": ("Less active lately", None),
    "score_familiar_component": ("Familiar component", None),
    "score_explore_component": ("Explore component", None),
}


@dataclass(frozen=True, slots=True)
class ExplainableFactor:
    """One human-readable explanation element derived from a persisted reason code.

    Attributes:
        code: Stable machine-readable code for the factor family.
        label: Short user-facing description (e.g., "Strong affinity").
        detail: Optional extended context (e.g., "Fits Light mode").
    """

    code: str
    label: str
    detail: str | None = None


def _bandwidth_label(bandwidth_code: str) -> ExplainableFactor | None:
    """Translate a persisted bandwidth band code into a human-readable factor.

    Args:
        bandwidth_code: One of the stable bandwidth band codes stored at
            decision time (e.g., "band_light", "band_balanced", "band_deep").
            Unknown codes are silently ignored.

    Returns:
        An ExplainableFactor with label and optional detail, or ``None`` for
        unrecognized codes.
    """
    entry = _BANDWIDTH_EXPLANATIONS.get(bandwidth_code)
    if entry is None:
        return None
    label, detail = entry
    return ExplainableFactor(code=bandwidth_code, label=label, detail=detail)


def _intent_label(intent_code: str) -> ExplainableFactor | None:
    """Translate a persisted intent code into a human-readable factor.

    Args:
        intent_code: One of the stable intent codes stored at decision time
            (e.g., "intent_momentum", "intent_random"). Unknown codes are
            silently ignored.

    Returns:
        An ExplainableFactor for recognized codes, or ``None`` otherwise.
    """
    entry = _INTENT_EXPLANATIONS.get(intent_code)
    if entry is None:
        return None
    label, detail = entry
    return ExplainableFactor(code=intent_code, label=label, detail=detail)


def _selection_label(selection_method: str) -> ExplainableFactor | None:
    """Translate a persisted selection-method value into an explanation factor.

    Args:
        selection_method: The ``selection_method`` value stored on the Event
            record at roll time (e.g., "random", "override"). Unknown values
            are silently ignored — they are not scored/reason-code data.

    Returns:
        An ExplainableFactor for recognized selection methods, or ``None``
        otherwise.
    """
    entry = _SELECTION_EXPLANATIONS.get(selection_method)
    if entry is None:
        return None
    label, detail = entry
    return ExplainableFactor(code=selection_method, label=label, detail=detail)


def _taste_bank_label(tb_factor: dict[str, Any]) -> ExplainableFactor | None:
    """Translate a persisted Taste Bank factor dict into a human-readable factor.

    The Taste Bank context entry is expected to carry a stable ``code`` key
    identifying the factor family (e.g., "taste_high_affinity",
    "taste_confirmed_creator").

    Args:
        tb_factor: One element of the ``taste_bank_factors`` list from the
            persisted recommendation context. Must be a dict with a ``code``
            key; missing or non-dict values are silently skipped.

    Returns:
        An ExplainableFactor drawn from the Taste Bank explanation map, or
        ``None`` when the code is not recognized.
    """
    if not isinstance(tb_factor, dict):
        return None
    code = tb_factor.get("code")
    if not isinstance(code, str) or not code:
        return None

    entry = _TASTE_BANK_EXPLANATIONS.get(code)
    if entry is None:
        return None
    label, detail = entry
    detail = tb_factor.get("detail") if detail is None else detail
    return ExplainableFactor(code=code, label=label, detail=detail)


def _primary_score_label(primary_score: dict[str, Any]) -> ExplainableFactor | None:
    """Translate a persisted primary-score block into a human-readable factor.

    The primary-score entry is expected to carry a stable ``code`` key. Values
    are opaque (never leaked) — only the code is inspected.

    Args:
        primary_score: The ``primary_score`` dict from the persisted
            recommendation context. Non-dict values are silently skipped.

    Returns:
        An ExplainableFactor for recognized codes, or ``None`` otherwise.
    """
    if not isinstance(primary_score, dict):
        return None
    code = primary_score.get("code")
    if not isinstance(code, str) or not code:
        return None

    entry = _PRIMARY_SCORE_EXPLANATIONS.get(code)
    if entry is None:
        return None
    label, detail = entry
    return ExplainableFactor(code=code, label=label, detail=detail)


MAX_EXPLANATIONS = 5


class RecommendationExplanationProjection:
    """Pure projection from persisted recommendation context to explanations.

    All methods are stateless and side-effect free, making this class suitable
    for direct unit testing without any database or application runtime.

    Usage::

        projection = RecommendationExplanationProjection()
        factors = projection.project_recommendation_context({
            "bandwidth": "band_light",
            "intent": "intent_momentum",
        })
        for f in factors:
            print(f.label, f.detail)
    """

    @staticmethod
    def translate_bandwidth(bandwidth_code: str) -> ExplainableFactor | None:
        """Translate a single bandwidth band code into an explanation.

        Args:
            bandwidth_code: Stable bandwidth band code (e.g., ``"band_light"``).

        Returns:
            ExplainableFactor for recognized codes, ``None`` otherwise.
        """
        return _bandwidth_label(bandwidth_code)

    @staticmethod
    def translate_intent(intent_code: str) -> ExplainableFactor | None:
        """Translate a single intent code into an explanation.

        Args:
            intent_code: Stable intent code (e.g., ``"intent_momentum"``).

        Returns:
            ExplainableFactor for recognized codes, ``None`` otherwise.
        """
        return _intent_label(intent_code)

    @staticmethod
    def translate_selection_method(selection_method: str) -> ExplainableFactor | None:
        """Translate a single selection-method value into an explanation.

        Args:
            selection_method: ``Event.selection_method`` value at roll time
                (e.g., ``"random"``).

        Returns:
            ExplainableFactor for recognized methods, ``None`` otherwise.
        """
        return _selection_label(selection_method)

    @staticmethod
    def translate_taste_bank_factor(
        tb_factor: dict[str, Any],
    ) -> ExplainableFactor | None:
        """Translate a single Taste Bank factor dict into an explanation.

        Args:
            tb_factor: One element of ``taste_bank_factors``. Must carry a
                ``"code"`` string key.

        Returns:
            ExplainableFactor for recognized codes, ``None`` otherwise.
        """
        return _taste_bank_label(tb_factor)

    @staticmethod
    def translate_primary_score(
        primary_score: dict[str, Any],
    ) -> ExplainableFactor | None:
        """Translate a primary-score block into an explanation.

        Args:
            primary_score: The ``primary_score`` dict from recommendation
                context. Only the ``"code"`` key is inspected; raw numeric
                scores are never exposed.

        Returns:
            ExplainableFactor for recognized codes, ``None`` otherwise.
        """
        return _primary_score_label(primary_score)

    @staticmethod
    def project_recommendation_context(
        context: dict[str, Any] | None,
        *,
        selection_method: str | None = None,
        max_factors: int = MAX_EXPLANATIONS,
    ) -> list[ExplainableFactor]:
        """Transform a persisted recommendation context into ordered explanations.

        Derives explanations from the ``bandwidth``, ``intent``,
        ``taste_bank_factors``, ``primary_score``, and ``affinity_notes``
        keys of the supplied context dict. A ``selection_method`` override is
        used to determine the random-selection explanation when the selection
        path does not derive a contextual reason.

        Factor ordering is deterministic:
        1. Bandwidth explanation (at most one).
        2. Intent explanation (at most one).
        3. Taste Bank explanations (up to two, in provided order).
        4. Primary-score explanation (at most one).
        5. Affinity-notes explanations (in provided order).
        6. Selection-method explanation (at most one, appended when other
           factors are present or when context is absent altogether). Legacy
           contexts that record ``intent_random`` without an explicit
           selection method still receive the random-bypass explanation.

        Unknown codes in any factor list are silently skipped.

        Args:
            context: Persisted recommendation context recorded at decision time.
                Typically deserialized from the JSON column on the Event
                record. A ``None`` value or non-dict value is treated as empty
                context.
            selection_method: The ``Event.selection_method`` value to use as a
                fallback/selection explanation. Defaults to ``None``.
            max_factors: Maximum number of explanation factors to return.
                Defaults to 5.

        Returns:
            Ordered list of ``ExplainableFactor`` values, each carrying a
            stable ``code``, a user-facing ``label``, and an optional
            ``detail``. The list is never ``None``; it is empty when the
            context has no recognized factor codes.
        """
        if not isinstance(context, dict):
            context = {}

        factors: list[ExplainableFactor] = []

        bandwidth_code = context.get("bandwidth")
        if isinstance(bandwidth_code, str) and bandwidth_code:
            factor = _bandwidth_label(bandwidth_code)
            if factor is not None:
                factors.append(factor)

        intent_code = context.get("intent")
        if isinstance(intent_code, str) and intent_code:
            factor = _intent_label(intent_code)
            if factor is not None:
                factors.append(factor)

        tb_factors = context.get("taste_bank_factors")
        if isinstance(tb_factors, list):
            count = 0
            for tb_entry in tb_factors:
                if count >= 2:
                    break
                factor = _taste_bank_label(tb_entry)
                if factor is not None:
                    factors.append(factor)
                    count += 1

        primary_score = context.get("primary_score")
        if isinstance(primary_score, dict):
            factor = _primary_score_label(primary_score)
            if factor is not None:
                factors.append(factor)

        affinity_notes = context.get("affinity_notes")
        if isinstance(affinity_notes, list):
            for note_code in affinity_notes:
                if isinstance(note_code, str) and note_code:
                    factor = _taste_bank_label({"code": note_code})
                    if factor is not None:
                        factors.append(factor)

        raw_method: Any = (
            selection_method
            if selection_method is not None
            else context.get("selection_method", "")
        )
        if raw_method == "" and intent_code == "intent_random":
            # Legacy control rolls recorded intent_random without an explicit
            # selection method; the weighting-bypass explanation still applies.
            raw_method = "random"
        selection_factor = _selection_label(raw_method)
        if selection_factor is not None:
            factors.append(selection_factor)

        if len(factors) > max_factors:
            factors = factors[:max_factors]

        return factors