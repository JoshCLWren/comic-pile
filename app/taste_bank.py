"""Taste Bank discovery services — Phase 7 (no ranking use)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TypedDict


VALID_FEATURE_TYPES = {"creator", "character", "team", "publisher", "era"}
VALID_VERDICTS = {"inferred", "confirmed", "sometimes", "rejected"}
EXPLICIT_VERDICTS = {"confirmed", "sometimes", "rejected"}

# Thresholds for prompt eligibility
MIN_EVIDENCE_COUNT = 3
MIN_CONFIDENCE = 0.6
MIN_DISTINCT_ISSUES = 2
PROMPT_COOLDOWN_DAYS = 7
REJECTION_SUPPRESSION_DAYS = 365 * 10  # effectively permanent unless explicit reset
DIVERSITY_BONUS_THREADS = 2


class TasteEvidence(TypedDict):
    feature_type: str
    feature_key: str
    display_name: str
    role: str | None


def _era_bucket_from_date(value: object) -> str | None:
    """Derive decade bucket like '2010s' from cover_date/store_date/start_year."""
    if isinstance(value, str) and value:
        # Try ISO date
        try:
            # e.g. "2026-01-01" or "2025"
            year_str = value.strip().split("-")[0]
            year = int(year_str)
            if 1800 <= year <= 2100:
                decade = (year // 10) * 10
                return f"{decade}s"
        except (ValueError, IndexError):
            return None
    elif isinstance(value, int) and 1800 <= value <= 2100:
        decade = (value // 10) * 10
        return f"{decade}s"
    return None


def extract_taste_evidence(
    metadata_json: dict[str, object],
    *,
    confirmed: bool = True,
) -> list[TasteEvidence]:
    """Extract normalized taste evidence from confirmed ComicVine metadata.

    Args:
        metadata_json: Normalized ExternalIdentity.metadata_json (from normalize_issue/volume).
        confirmed: Only confirmed mappings yield evidence.

    Returns:
        Deduplicated list of taste evidence for this issue.
    """
    if not confirmed:
        return []
    if not isinstance(metadata_json, dict):
        return []

    seen: set[tuple[str, str]] = set()
    out: list[TasteEvidence] = []

    def add(ft: str, key: str, display: str, role: str | None = None) -> None:
        dedup = (ft, key)
        if dedup in seen:
            return
        seen.add(dedup)
        out.append({"feature_type": ft, "feature_key": key, "display_name": display, "role": role})

    # Creators: creator_credits = [{"id": 1, "name": "...", "role": "writer"}]
    raw_creators = metadata_json.get("creator_credits")
    if isinstance(raw_creators, list):
        for item in raw_creators:
            if not isinstance(item, dict):
                continue
            cid = item.get("id")
            name = item.get("name")
            role = item.get("role") if isinstance(item.get("role"), str) else None
            if cid is None or not isinstance(name, str) or not name.strip():
                continue
            cid_str = str(cid).strip()
            if not cid_str:
                continue
            role_norm = role.strip().lower() if role and role.strip() else None
            key = f"creator:{cid_str}:{role_norm}" if role_norm else f"creator:{cid_str}"
            add("creator", key, name.strip(), role_norm)

    # Characters
    raw_chars = metadata_json.get("characters")
    if isinstance(raw_chars, list):
        for item in raw_chars:
            if not isinstance(item, dict):
                continue
            cid = item.get("id")
            name = item.get("name")
            if cid is None or not isinstance(name, str) or not name.strip():
                continue
            add("character", f"character:{cid}", name.strip())

    # Teams
    raw_teams = metadata_json.get("teams")
    if isinstance(raw_teams, list):
        for item in raw_teams:
            if not isinstance(item, dict):
                continue
            tid = item.get("id")
            name = item.get("name")
            if tid is None or not isinstance(name, str) or not name.strip():
                continue
            add("team", f"team:{tid}", name.strip())

    # Publisher: from publisher or volume.publisher
    publisher: dict[str, object] | None = None
    raw_pub = metadata_json.get("publisher")
    if isinstance(raw_pub, dict):
        publisher = raw_pub
    else:
        raw_vol = metadata_json.get("volume")
        if isinstance(raw_vol, dict):
            # volume may not contain publisher; check nested if hydrator stored it elsewhere
            # Fallback: check metadata_json directly for publisher inside volume key
            pass
        # Also handle volume.publisher if publisher not at top level but nested under volume
        if publisher is None and isinstance(metadata_json.get("volume"), dict):
            vol = metadata_json["volume"]
            if isinstance(vol, dict) and isinstance(vol.get("publisher"), dict):
                publisher = vol.get("publisher")  # type: ignore[assignment]

    if isinstance(publisher, dict):
        pid = publisher.get("id")
        pname = publisher.get("name")
        if isinstance(pname, str) and pname.strip():
            if pid is not None:
                add("publisher", f"publisher:{pid}", pname.strip())
            else:
                # Stable key from normalized lower name when id missing
                add("publisher", f"publisher:name:{pname.strip().lower()}", pname.strip())
    # Also check volume-level publisher if publisher at top missing but volume dict has publisher reference
    # (legacy hydrator stores publisher inside volume)
    # Already handled above via volume.publisher check; also try top-level publisher alternative location
    # If still none, try to find publisher inside raw_provider_payload volume
    if not any(e["feature_type"] == "publisher" for e in out):
        raw_payload = metadata_json.get("raw_provider_payload")
        if isinstance(raw_payload, dict):
            vol = raw_payload.get("volume")
            if isinstance(vol, dict):
                pub2 = vol.get("publisher") if isinstance(vol.get("publisher"), dict) else None
                if isinstance(pub2, dict) and isinstance(pub2.get("name"), str) and pub2["name"].strip():  # type: ignore[index]
                    pid2 = pub2.get("id")
                    pname2 = pub2["name"]  # type: ignore[index]
                    if pid2 is not None:
                        add("publisher", f"publisher:{pid2}", pname2.strip())  # type: ignore[arg-type]
                    else:
                        add("publisher", f"publisher:name:{pname2.strip().lower()}", pname2.strip())

    # Era: derive from cover_date, store_date, or start_year
    era_val = metadata_json.get("cover_date") or metadata_json.get("store_date") or metadata_json.get("start_year")
    era_bucket = _era_bucket_from_date(era_val)
    # Also check volume start_year if top-level missing
    if era_bucket is None:
        vol2 = metadata_json.get("volume")
        if isinstance(vol2, dict):
            era_bucket = _era_bucket_from_date(vol2.get("start_year"))
    if era_bucket is None:
        # check raw_provider_payload cover_date
        raw_payload2 = metadata_json.get("raw_provider_payload")
        if isinstance(raw_payload2, dict):
            era_bucket = _era_bucket_from_date(
                raw_payload2.get("cover_date") or raw_payload2.get("store_date")
            )
    if era_bucket is not None:
        add("era", f"era:{era_bucket}", era_bucket)

    return out


def compute_confidence(
    evidence_count: int,
    distinct_issue_count: int,
    distinct_thread_count: int,
    affinity: float | None = None,
) -> float:
    """Compute cautious confidence for an inferred signal.

    Sparse evidence stays low; repeated diverse evidence rises above threshold.
    """
    if evidence_count <= 0:
        return 0.0
    # Base confidence by count
    if evidence_count == 1:
        base = 0.2
    elif evidence_count == 2:
        base = 0.35
    elif evidence_count == 3:
        base = 0.70
    elif evidence_count == 4:
        base = 0.85
    else:
        base = 0.95

    # Diversity bonus: distinct threads beyond 1 increase confidence modestly
    if distinct_thread_count >= DIVERSITY_BONUS_THREADS:
        base = min(1.0, base + 0.05)
    if distinct_issue_count >= 3:
        base = min(1.0, base + 0.05)

    # Affinity above baseline boosts; negative affinity reduces (but still calculable)
    if affinity is not None and affinity > 0:
        # Cap affinity boost to avoid single strong rating dominating
        base = min(1.0, base + min(0.05, affinity * 0.02))

    return round(base, 3)


def is_inferred_confident(
    evidence_count: int,
    distinct_issue_count: int,
    confidence: float,
) -> bool:
    """Return True if evidence is strong enough for an inferred signal."""
    return (
        evidence_count >= MIN_EVIDENCE_COUNT
        and distinct_issue_count >= MIN_DISTINCT_ISSUES
        and confidence >= MIN_CONFIDENCE
    )


def is_prompt_eligible(
    *,
    evidence_count: int,
    distinct_issue_count: int,
    confidence: float,
    verdict: str,
    last_prompted_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Centralized deterministic prompt eligibility.

    Respects evidence thresholds, diversity, cooldown, and rejection suppression.
    """
    cur = now or datetime.now(UTC)

    # Verdict suppression: rejected signals never eligible via normal discovery
    if verdict == "rejected":
        return False

    # Already explicitly confirmed/sometimes should not be re-prompted via discovery
    # (they are not inferred); treat as ineligible for new discovery prompt
    if verdict in ("confirmed", "sometimes"):
        return False

    if not is_inferred_confident(evidence_count, distinct_issue_count, confidence):
        return False

    if last_prompted_at is not None:
        # Cooldown
        if cur - last_prompted_at < timedelta(days=PROMPT_COOLDOWN_DAYS):
            return False

    return True


def rank_prompt_candidates(signals: list[dict[str, object]]) -> list[dict[str, object]]:
    """Rank eligible signals by confidence then evidence_count for diversity.

    Gracefully handles heterogeneous prompt ordering without extra UI state.
    """
    return sorted(
        signals,
        key=lambda s: (float(s.get("confidence", 0)), int(s.get("evidence_count", 0))),
        reverse=True,
    )
