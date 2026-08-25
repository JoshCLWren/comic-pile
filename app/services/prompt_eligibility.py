"""Prompt-eligibility engine for taste-signal discovery (issue #1746).

Evaluates inferred taste signals against conservative threshold, cooldown,
suppression, and creator-role rules to produce a ranked list of prompt
candidates. The engine is stateless and deterministic: identical inputs
always produce identical outputs.

Rules implemented:
    1. **Threshold gates**: Sparse/weak signals are rejected when evidence
       count, confidence, affinity, or diversity falls below configured
       minimums.
    2. **Cooldown suppression**: Recently prompted signals are suppressed
       for a configurable cooldown period.
    3. **Rejection suppression**: Explicitly rejected signals are suppressed
       permanently (or for a configurable period).
    4. **Creator-role preference**: When creator-role evidence is available,
       role-specific prompts are preferred over generic creator prompts.
    5. **Composite ranking**: Eligible signals are scored and ranked by
       affinity, confidence, diversity, and evidence strength.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.taste import (
    PromptCandidate,
    PromptEligibilityConfig,
    PromptEligibilityResult,
    TasteSignal,
    Verdict,
)

# Default configuration matching the acceptance criteria.
DEFAULT_CONFIG = PromptEligibilityConfig()


def _is_below_threshold(signal: TasteSignal, config: PromptEligibilityConfig) -> bool:
    """Check whether a signal fails any threshold gate.

    Args:
        signal: The taste signal to evaluate.
        config: Eligibility thresholds.

    Returns:
        ``True`` when the signal is too sparse or weak to prompt.
    """
    return (
        signal.evidence_count < config.min_evidence_count
        or signal.confidence < config.min_confidence
        or abs(signal.affinity) < config.min_affinity
        or signal.evidence_diversity < config.min_diversity
    )


def _is_cooldown_active(
    signal: TasteSignal,
    config: PromptEligibilityConfig,
    now: datetime,
) -> bool:
    """Check whether a signal is within its cooldown window.

    Args:
        signal: The taste signal to evaluate.
        config: Eligibility thresholds.
        now: Current timestamp for comparison.

    Returns:
        ``True`` when the signal was prompted too recently.
    """
    if signal.last_prompted_at is None:
        return False
    cooldown_end = signal.last_prompted_at + timedelta(days=config.cooldown_days)
    return now < cooldown_end


def _is_rejection_suppressed(
    signal: TasteSignal,
    config: PromptEligibilityConfig,
    now: datetime,
) -> bool:
    """Check whether a signal is suppressed due to user rejection.

    Rejected signals are never re-prompted unless the product adds an
    explicit reset flow. The configurable ``rejection_suppress_days``
    defaults to infinity (permanent suppression).

    Args:
        signal: The taste signal to evaluate.
        config: Eligibility thresholds.
        now: Current timestamp for comparison.

    Returns:
        ``True`` when the signal should not be prompted.
    """
    if signal.verdict == Verdict.REJECTED:
        if config.rejection_suppress_days == float("inf"):
            return True
        if signal.last_rejected_at is not None:
            suppress_end = signal.last_rejected_at + timedelta(
                days=int(config.rejection_suppress_days)
            )
            return now < suppress_end
        return True
    return False


def _compute_score(
    signal: TasteSignal,
    config: PromptEligibilityConfig,
) -> float:
    """Compute a composite ranking score for an eligible signal.

    Higher scores indicate stronger, more diverse patterns that are more
    likely to be genuinely useful prompts.

    The score combines:
        - Normalized affinity (weight: 0.35)
        - Confidence (weight: 0.30)
        - Evidence count normalized against a soft cap (weight: 0.20)
        - Diversity normalized against a soft cap (weight: 0.10)
        - Creator-role bonus (weight: 0.05)

    Args:
        signal: The eligible taste signal.
        config: Eligibility thresholds (used for normalization baselines).

    Returns:
        A non-negative composite score.
    """
    # Normalize affinity: 0 at min_affinity, 1.0 at 2x min_affinity
    affinity_norm = min(
        abs(signal.affinity) / max(config.min_affinity * 2, 0.01), 1.0
    )
    # Confidence is already in [0, 1]
    confidence_norm = signal.confidence
    # Normalize evidence count: 1.0 at 3x min, capped
    evidence_norm = min(
        signal.evidence_count / max(config.min_evidence_count * 3, 1), 1.0
    )
    # Normalize diversity: 1.0 at 3x min, capped
    diversity_norm = min(
        signal.evidence_diversity / max(config.min_diversity * 3, 1), 1.0
    )
    # Creator-role bonus
    role_bonus = 1.0 if signal.is_creator_role else 0.0

    return (
        0.35 * affinity_norm
        + 0.30 * confidence_norm
        + 0.20 * evidence_norm
        + 0.10 * diversity_norm
        + 0.05 * role_bonus
    )


def _prefer_creator_role_specific(
    signals: list[TasteSignal],
) -> list[TasteSignal]:
    """Deduplicate generic creator signals when a role-specific variant exists.

    When both a generic creator signal (e.g. ``creator:alan-moore``) and a
    role-specific signal (e.g. ``creator:writer:alan-moore``) are present
    for the same underlying creator, prefer the role-specific signal.

    Args:
        signals: Eligible signals after threshold and suppression gates.

    Returns:
        Signals with redundant generic creator entries removed.
    """
    role_specific_keys: set[str] = set()
    generic_creator_keys: set[str] = set()

    for signal in signals:
        if signal.signal_type.value == "creator" and signal.is_creator_role:
            # Extract the creator name from the stable_key
            # Role keys look like "creator:writer:alan-moore"
            parts = signal.stable_key.split(":")
            if len(parts) >= 3:
                creator_name = parts[2]
                role_specific_keys.add(creator_name)
        elif signal.signal_type.value == "creator" and not signal.is_creator_role:
            parts = signal.stable_key.split(":")
            if len(parts) >= 2:
                creator_name = parts[1]
                generic_creator_keys.add(creator_name)

    redundant_keys = role_specific_keys & generic_creator_keys
    if not redundant_keys:
        return signals

    filtered: list[TasteSignal] = []
    for signal in signals:
        if signal.signal_type.value == "creator" and not signal.is_creator_role:
            parts = signal.stable_key.split(":")
            if len(parts) >= 2 and parts[1] in redundant_keys:
                continue
        filtered.append(signal)
    return filtered


def evaluate_prompt_eligibility(
    signals: list[TasteSignal],
    config: PromptEligibilityConfig | None = None,
    now: datetime | None = None,
) -> PromptEligibilityResult:
    """Evaluate which taste signals are eligible to become prompts.

    This is the main entry point for the prompt-eligibility engine. It
    applies all rules deterministically and returns a ranked result.

    Args:
        signals: All known taste signals for a single user.
        config: Eligibility thresholds. Uses defaults when ``None``.
        now: Current timestamp. Uses ``datetime.now(UTC)`` when ``None``.

    Returns:
        A result containing ranked candidates, suppressed signals, and
        signals that failed threshold gates.
    """
    if config is None:
        config = DEFAULT_CONFIG
    if now is None:
        now = datetime.now(UTC)

    candidates: list[TasteSignal] = []
    suppressed: list[TasteSignal] = []
    ineligible: list[TasteSignal] = []

    for signal in signals:
        # Gate 1: threshold checks
        if _is_below_threshold(signal, config):
            ineligible.append(signal)
            continue

        # Gate 2: rejection suppression (permanent by default)
        if _is_rejection_suppressed(signal, config, now):
            suppressed.append(signal)
            continue

        # Gate 3: cooldown suppression
        if _is_cooldown_active(signal, config, now):
            suppressed.append(signal)
            continue

        candidates.append(signal)

    # Deduplicate generic creators when role-specific variants exist
    candidates = _prefer_creator_role_specific(candidates)

    # Score and rank
    scored = [
        PromptCandidate(
            signal=signal,
            score=_compute_score(signal, config),
            rank=0,  # assigned below
        )
        for signal in candidates
    ]
    scored.sort(key=lambda c: (-c.score, c.signal.stable_key))

    # Assign ranks and cap at max_candidates
    capped = scored[: config.max_candidates]
    for index, candidate in enumerate(capped, start=1):
        candidate = candidate.model_copy(update={"rank": index})
        # Rebuild with updated rank
        capped[index - 1] = PromptCandidate(
            signal=candidate.signal,
            score=candidate.score,
            rank=index,
        )

    return PromptEligibilityResult(
        candidates=capped,
        suppressed=suppressed,
        ineligible=ineligible,
    )
