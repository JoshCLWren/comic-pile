"""Pure Familiar-intent weighting from confirmed Taste Bank signals.

This module implements the Phase 8 Familiar intent factor (issue #1757). It is a
pure calculation layer: it maps confirmed Taste Bank preferences onto the
candidates that are already inside the bounded die pool and never expands,
reorders, or filters that pool by itself.

Contract:

- Explicit ``confirmed`` verdicts contribute the strongest per-signal bonus.
- Explicit ``sometimes`` (qualified) verdicts contribute a strictly weaker bonus.
- ``rejected`` signals never boost a candidate; they are excluded entirely.
- Inferred-but-unconfirmed signals contribute nothing unless the architecture
  explicitly permits their very small capped effect. Until that gate opens, an
  explicit verdict is always the authority.
- Every effect is capped so Taste Bank metadata can never overwhelm the existing
  affinity/die boundary. The returned multiplier is bounded to
  ``1.0 + MAX_FAMILIAR_BONUS`` regardless of how many signals match.
- Missing or unconfirmed metadata fails to neutral: no positive match produces a
  neutral multiplier of exactly ``NEUTRAL_MULTIPLIER``.

The output is transparent: each contributing signal is reported with its kind,
normalized key, verdict, and individual contribution so downstream reason-code
recording (#1762) and human-readable explanations (#1764) can project them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

TasteKind = Literal["creator_role", "character", "team", "publisher", "era"]
TasteVerdict = Literal["confirmed", "sometimes", "rejected"]
TasteSource = Literal["explicit", "inferred"]

#: Bonus applied per uniquely matched ``confirmed`` taste signal.
CONFIRMED_MATCH_BONUS = 0.05

#: Bonus applied per uniquely matched ``sometimes`` taste signal. Strictly
#: smaller than :data:`CONFIRMED_MATCH_BONUS` so qualified preferences always
#: rank below explicit confirmations.
SOMETIMES_MATCH_BONUS = 0.02

#: Upper bound on the total familiar bonus for one candidate. Metadata matches
#: may only ever shift selection modestly inside the bounded die pool; they must
#: never overwhelm the affinity/dice boundary.
MAX_FAMILIAR_BONUS = 0.15

#: Multiplier reported when no signal positively contributes.
NEUTRAL_MULTIPLIER = 1.0

#: Architecture gate for inferred-but-unconfirmed signals. The Familiar phase
#: ships with explicit verdicts as the sole authority; flipping this gate later
#: would permit inferred evidence at a deliberately tiny capped contribution.
ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS = False

#: Contribution used for inferred signals while they are not permitted. Kept as
#: a named constant so the "very small capped effect" decision stays auditable.
INFERRED_UNCONFIRMED_CONTRIBUTION = 0.0

_VERDICT_BONUSES: Mapping[str, float] = {
    "confirmed": CONFIRMED_MATCH_BONUS,
    "sometimes": SOMETIMES_MATCH_BONUS,
    "rejected": 0.0,
}

_NON_ALNUM_RUN = re.compile(r"[^a-z0-9]+")
_YEAR_IN_TEXT = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def normalize_key(value: object) -> str:
    """Normalize free-form metadata text into a stable comparison key.

    Keys are case-folded, punctuation-insensitive, and whitespace-collapsed so
    the same creator/character/team/publisher name normalizes identically no
    matter which provider surface produced it.

    Args:
        value: Arbitrary metadata value; non-string input normalizes to empty.

    Returns:
        Normalized key such as ``"x men"`` for ``"X-Men!"``, or an empty string
        when no usable text remains.
    """
    if not isinstance(value, str):
        return ""
    folded = unicodedata.normalize("NFKC", value).casefold()
    return _NON_ALNUM_RUN.sub(" ", folded).strip()


def era_key_from_cover_date(value: object) -> str:
    """Derive a stable decade-bucket era key from a cover date.

    Args:
        value: Cover date such as ``"1987-03-12"``, a bare year ``1987``, or any
            other value (which yields no era key).

    Returns:
        Era key like ``"1980s"``, or an empty string when no year is present.
    """
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        year = value
    elif isinstance(value, str):
        match = _YEAR_IN_TEXT.search(value)
        if match is None:
            return ""
        year = int(match.group(1))
    else:
        return ""
    if not 1900 <= year <= 2099:
        return ""
    start = year - (year % 10)
    return f"{start}s"


@dataclass(frozen=True)
class CreatorCreditKey:
    """One normalized creator credit together with its normalized roles."""

    key: str
    roles: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CandidateFamiliarKeys:
    """Normalized taste-relevant keys extracted from one candidate's metadata.

    Empty collections mean the corresponding metadata was missing or unusable;
    scoring then fails to neutral for those signal kinds.
    """

    creator_roles: tuple[CreatorCreditKey, ...] = ()
    characters: frozenset[str] = frozenset()
    teams: frozenset[str] = frozenset()
    publishers: frozenset[str] = frozenset()
    eras: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TasteSignal:
    """One Taste Bank preference used to score familiar candidates.

    Attributes:
        kind: Signal family being matched against candidate metadata.
        key: Signal label such as a creator/character/team/publisher name or an
            era bucket. It is normalized with :func:`normalize_key` before
            matching, so raw provider-style text is accepted.
        verdict: Explicit user verdict for this pattern.
        source: Whether the verdict is explicit or merely inferred from
            repeated reading evidence. Inferred signals contribute nothing while
            :data:`ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS` is false.
        roles: Optional role narrowing for ``creator_role`` signals; empty means
            the creator matches in any credited role. Roles are normalized the
            same way as candidate credit roles before comparison.
    """

    kind: TasteKind
    key: str
    verdict: TasteVerdict
    source: TasteSource = "explicit"
    roles: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class FamiliarMatch:
    """One positively contributing taste match on a single candidate."""

    kind: TasteKind
    key: str
    verdict: TasteVerdict
    contribution: float


@dataclass(frozen=True)
class FamiliarFactor:
    """Transparent familiar-intent factor for one candidate.

    Attributes:
        candidate_id: Candidate the factor belongs to. The factor set never
            contains IDs outside the caller-supplied bounded pool.
        bonus: Total capped familiar bonus in ``[0, MAX_FAMILIAR_BONUS]``.
        multiplier: Selection weight multiplier, ``1.0 + bonus``. Neutral when
            no signal contributed.
        capped: True when raw contributions exceeded the cap.
        matches: Contributing signals with per-signal transparency.
    """

    candidate_id: int
    bonus: float
    multiplier: float
    capped: bool
    matches: tuple[FamiliarMatch, ...]


def _credit_keys(metadata: Mapping[str, object], *names: str) -> list[CreatorCreditKey]:
    """Extract normalized creator credits from any accepted provider shape.

    Args:
        metadata: Candidate metadata mapping.
        names: Metadata fields that may hold credit lists, tried in order.

    Returns:
        Deduplicated creator credits preserving first-seen order.
    """
    credits: list[CreatorCreditKey] = []
    seen: set[str] = set()
    for name in names:
        raw_credits = metadata.get(name)
        if not isinstance(raw_credits, list):
            continue
        for entry in raw_credits:
            if not isinstance(entry, Mapping):
                continue
            key = normalize_key(entry.get("name"))
            if not key or key in seen:
                continue
            seen.add(key)
            roles_raw = entry.get("role")
            roles: frozenset[str]
            if isinstance(roles_raw, str):
                roles = frozenset(
                    normalized
                    for part in roles_raw.split(",")
                    if (normalized := normalize_key(part))
                )
            else:
                roles = frozenset()
            credits.append(CreatorCreditKey(key=key, roles=roles))
    return credits


def _name_keys(metadata: Mapping[str, object], field_name: str) -> frozenset[str]:
    """Extract normalized names from a list-shaped metadata field.

    Args:
        metadata: Candidate metadata mapping.
        field_name: Field holding entries shaped like ``{"name": ...}``.

    Returns:
        Set of normalized names; empty when the field is missing or malformed.
    """
    raw_entries = metadata.get(field_name)
    if not isinstance(raw_entries, list):
        return frozenset()
    keys: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, Mapping):
            continue
        key = normalize_key(entry.get("name"))
        if key:
            keys.add(key)
    return frozenset(keys)


def _publisher_names(metadata: Mapping[str, object]) -> frozenset[str]:
    """Extract normalized publisher names from flat or volume-nested shapes.

    Args:
        metadata: Candidate metadata mapping.

    Returns:
        Set of normalized publisher names; empty when absent or malformed.
    """
    names: set[str] = set()
    candidates: list[object] = [metadata.get("publisher")]
    volume = metadata.get("volume")
    if isinstance(volume, Mapping):
        candidates.append(volume.get("publisher"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            name_value = candidate.get("name")
        else:
            name_value = candidate
        key = normalize_key(name_value)
        if key:
            names.add(key)
    return frozenset(names)


def _era_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    """Extract decade-bucket era keys from cover-date style fields.

    Args:
        metadata: Candidate metadata mapping.

    Returns:
        Set of era keys such as ``"1980s"``; empty when no date is usable.
    """
    eras: set[str] = set()
    for field_name in ("cover_date", "store_date"):
        era = era_key_from_cover_date(metadata.get(field_name))
        if era:
            eras.add(era)
    return frozenset(eras)


def extract_candidate_familiar_keys(metadata: Mapping[str, object]) -> CandidateFamiliarKeys:
    """Extract all taste-relevant normalized keys from candidate metadata.

    Tolerates missing or malformed ComicVine shapes: unusable fields simply
    yield empty key sets so scoring fails to neutral instead of raising.

    Args:
        metadata: Provider metadata for the candidate's next unread issue,
            including creator/character/team credits, publisher, and dates.

    Returns:
        Normalized keys grouped by taste signal family.
    """
    return CandidateFamiliarKeys(
        creator_roles=tuple(_credit_keys(metadata, "creator_credits", "person_credits")),
        characters=_name_keys(metadata, "character_credits"),
        teams=_name_keys(metadata, "team_credits"),
        publishers=_publisher_names(metadata),
        eras=_era_keys(metadata),
    )


def _signal_contribution(signal: TasteSignal) -> float | None:
    """Resolve the positive contribution of an eligible signal, if any.

    Rejected signals never contribute positive weight. Inferred signals use
    their dedicated tiny contribution and stay silent while the architecture
    has not explicitly permitted them.

    Args:
        signal: Taste Bank signal under evaluation.

    Returns:
        The positive contribution value, or ``None`` when the signal must not
        contribute.
    """
    if signal.verdict == "rejected":
        return None
    if signal.source == "inferred":
        if not ALLOW_INFERRED_SIGNAL_CONTRIBUTIONS:
            return None
        return INFERRED_UNCONFIRMED_CONTRIBUTION or None
    bonus = _VERDICT_BONUSES[signal.verdict]
    return bonus if bonus > 0.0 else None


def _signal_matches(signal: TasteSignal, key: str, keys: CandidateFamiliarKeys) -> bool:
    """Check whether one eligible signal matches a candidate's metadata keys.

    Args:
        signal: Eligible Taste Bank signal.
        key: Normalized signal key used for the family lookup.
        keys: Normalized candidate metadata keys.

    Returns:
        True when the signal's normalized key appears in the matching family.
    """
    if signal.kind == "creator_role":
        roles = frozenset(
            normalized
            for role in signal.roles
            if (normalized := normalize_key(role))
        )
        return any(
            credit.key == key and (not roles or roles & credit.roles)
            for credit in keys.creator_roles
        )
    family: frozenset[str]
    if signal.kind == "character":
        family = keys.characters
    elif signal.kind == "team":
        family = keys.teams
    elif signal.kind == "publisher":
        family = keys.publishers
    else:
        family = keys.eras
    return key in family


def compute_familiar_factor(
    candidate_id: int,
    keys: CandidateFamiliarKeys,
    signals: Iterable[TasteSignal],
) -> FamiliarFactor:
    """Compute the capped familiar-intent factor for one bounded-pool candidate.

    Duplicate signals on the same normalized key count once at their strongest
    eligible verdict strength, then all unique matches sum toward the cap.

    Args:
        candidate_id: ID of the candidate being scored.
        keys: Normalized metadata keys extracted for the candidate.
        signals: The reader's Taste Bank signals.

    Returns:
        Transparent factor whose multiplier lies within
        ``[1.0, 1.0 + MAX_FAMILIAR_BONUS]``.
    """
    best_by_identity: dict[tuple[TasteKind, str], FamiliarMatch] = {}
    for signal in signals:
        contribution = _signal_contribution(signal)
        if contribution is None:
            continue
        key = normalize_key(signal.key)
        if not key or not _signal_matches(signal, key, keys):
            continue
        identity = (signal.kind, key)
        existing = best_by_identity.get(identity)
        if existing is None or contribution > existing.contribution:
            best_by_identity[identity] = FamiliarMatch(
                kind=signal.kind,
                key=key,
                verdict=signal.verdict,
                contribution=contribution,
            )

    ordered_matches = tuple(
        sorted(
            best_by_identity.values(),
            key=lambda match: (-match.contribution, match.kind, match.key),
        )
    )
    raw_bonus = sum(match.contribution for match in ordered_matches)
    capped = raw_bonus > MAX_FAMILIAR_BONUS
    bonus = min(raw_bonus, MAX_FAMILIAR_BONUS)

    return FamiliarFactor(
        candidate_id=candidate_id,
        bonus=bonus,
        multiplier=round(NEUTRAL_MULTIPLIER + bonus, 6),
        capped=capped,
        matches=ordered_matches,
    )


def compute_familiar_factors(
    candidates: Mapping[int, CandidateFamiliarKeys],
    signals: Iterable[TasteSignal],
) -> dict[int, FamiliarFactor]:
    """Score every candidate already inside the bounded die pool.

    No candidate is introduced outside the provided pool: exactly one factor is
    returned per supplied candidate ID, never more.

    Args:
        candidates: Bounded-pool candidate IDs mapped to their normalized keys.
        signals: The reader's Taste Bank signals.

    Returns:
        Familiar factors keyed by the same candidate IDs that were supplied.
    """
    return {
        candidate_id: compute_familiar_factor(candidate_id, keys, signals)
        for candidate_id, keys in candidates.items()
    }
