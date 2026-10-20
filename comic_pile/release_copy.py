"""Deterministic reader-facing copy rules for the What's New release ledger.

The public read path repairs historical copy with these rules, while
``app/schemas/release.py`` enforces the reader-facing artifact gate when new
releases are written. The module is intentionally dependency-free so it can be
inspected or reused from a standard-library-only Python runtime.

Historical entries may still contain copy that predates the publication gate.
The public read path repairs that copy deterministically instead of mutating
stored rows, and a small reviewed map restores canonical titles for records
whose stored title was itself malformed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")

_TICKET_REFERENCE_PATTERN = re.compile(r"(?<![\w&])#\d{1,7}\b")
_SCHEMA_IDENTIFIER_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PHASE_NUMBER = r"(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)"
_PHASE_TERMINOLOGY_PATTERN = re.compile(
    rf"\bphases?\s+{_PHASE_NUMBER}(?:\s+(?:and|or)\s+{_PHASE_NUMBER})?\b",
    re.IGNORECASE,
)
_PHASE_PREFIX_PATTERN = re.compile(
    rf"^\s*phases?\s+{_PHASE_NUMBER}(?:\s+(?:and|or)\s+{_PHASE_NUMBER})?\s*[:\-–—]\s*",
    re.IGNORECASE,
)
_PHASE_INLINE_PATTERN = re.compile(
    rf"\bphases?\s+{_PHASE_NUMBER}(?:\s+(?:and|or)\s+{_PHASE_NUMBER})?\s+(?:of\s+)?",
    re.IGNORECASE,
)
_UNFINISHED_WORK_PATTERN = re.compile(
    r"\b(?:incomplete|unfinished|todo|wip|not yet implemented)\b",
    re.IGNORECASE,
)

_INTERNAL_PATH_PATTERN = re.compile(
    r"(?<![\w/])(?:app|comic_pile|frontend|static|scripts|tests|alembic)(?:/[\w.-]+)+"
    r"|\b[\w-]+(?:/[\w-]+)*\.(?:py|ts|tsx|js|jsx|json|toml|ya?ml|css|md|sh|sql)\b"
)
_TEST_NARRATIVE_PATTERN = re.compile(
    r"\b\d[\d,]*\s+(?:new\s+)?assertions?\b"
    r"|\b(?:unit|integration|regression|playwright|vitest|pytest)\s+(?:tests?|specs?|coverage|suite)\b"
    r"|\btests?\s+(?:suite|coverage)\b"
    r"|\b[\w-]+\.(?:spec|test)\.(?:ts|tsx|js|jsx)\b",
    re.IGNORECASE,
)
_LEADING_SEPARATOR_PATTERN = re.compile(r"^\s*[:;,\-–—|]+\s*")
_MALFORMED_PUNCTUATION_PATTERN = re.compile(
    r"\s+[.,;:!?](?:\s|$)|[,;:]\s*[,;:]|\.\s*\.(?![.])|\(\s*\)|\[\s*\]"
)
_PARENTHETICAL_PATTERN = re.compile(r"\s*\([^()]*\)")
_ARTIFACT_CLAUSE_PATTERN = re.compile(
    r",\s*(?:closing|resolving|resolves|fixes|with|including|via|using|tracked in"
    r"|covered by|backed by)\b[^.;!?]*(?=[.;!?]|$)",
    re.IGNORECASE,
)
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
_DANGLING_HEAD_PATTERN = re.compile(
    r"^(?:of|for|to|with|and|or|in|on|at|by|from|that|which|whose|where|when"
    r"|while|as)\b",
)
_ENGINEERING_ONLY_PATTERN = re.compile(
    r"\b(?:api|backend|frontend|schema|repository|service|migration|endpoint|hook"
    r"|component|module|refactor|implementation)\b",
    re.IGNORECASE,
)
_READER_CUE_PATTERN = re.compile(r"\b(?:you|your|reader|readers)\b", re.IGNORECASE)
# A single engineering word does not make a sentence internal: release notes
# legitimately mention "the API" or "the frontend" when describing a reader
# change. Only sentences that accumulate several distinct implementation terms
# are treated as engineering-only narrative and omitted.
_MIN_ENGINEERING_TERMS = 2

_KNOWN_TYPOS: dict[str, str] = {
    "appearnence": "appearance",
    "appearence": "appearance",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "seperated": "separated",
    "occured": "occurred",
    "untill": "until",
    "definately": "definitely",
    "accross": "across",
    "existance": "existence",
    "persistant": "persistent",
    "successfull": "successful",
    "compatability": "compatibility",
    "roling": "rolling",
    "ont he": "on the",
}

# Reader capability claims must be backed by a named shipped reader path.
_CAPABILITY_CLAIM_PATTERN = re.compile(
    r"\b(?:you can now|can now|now\s+(?:supports|includes|lets\s+you|handles)"
    r"|(?:is|are)\s+now\s+available)\b",
    re.IGNORECASE,
)
# Kept in sync with the public schema's minimum visible content lengths.
MIN_PUBLIC_CONTENT: dict[str, int] = {"category": 2, "title": 4, "summary": 12}
READER_FACING_FIELDS = ("category", "title", "summary")


@dataclass(frozen=True)
class CuratedCopyRepair:
    """One canonical title repair verified against the merged source.

    Attributes:
        original_title: The stored title that must be present before the repair applies.
        title: Canonical reader-facing title verified from the merged change.
        summary: Optional canonical summary; None keeps the deterministic repair.
        evidence: Why the replacement is canonical.
    """

    original_title: str
    title: str
    summary: str | None = None
    evidence: str = ""


# Each entry is keyed by (source repository, merged pull request number). A
# repair only applies while the stored title still matches ``original_title``,
# so a later corrected publication is never overwritten by stale history.
CURATED_COPY_REPAIRS: dict[tuple[str, int], CuratedCopyRepair] = {
    ("JoshCLWren/comic-pile", 1881): CuratedCopyRepair(
        original_title="time on what’s new",
        title="Show relative and absolute timestamps on What's New",
        summary=(
            "The What's New page now shows when each release was published, "
            "using your local time zone."
        ),
        evidence=(
            "PR #1881 added relative and absolute publish times to the What's New "
            "cards for issue #1678."
        ),
    ),
    ("JoshCLWren/comic-pile", 1889): CuratedCopyRepair(
        original_title="errors when changing themes",
        title="Theme changes now save your preference",
        summary=(
            "Choosing a different theme now saves your preference instead of leaving "
            "the selection unsaved."
        ),
        evidence=(
            "PR #1889 repaired theme preference persistence after issue #1872 "
            "reported that saving the preference failed."
        ),
    ),
    ("JoshCLWren/comic-pile", 2394): CuratedCopyRepair(
        original_title="Commit reviewed material into a Reading Plan",
        title="Add reviewed material to an existing Reading Plan",
        evidence=(
            "PR #2394 restored the Add material UI for targeted Reading Plan adoption, "
            "distinct from the preview commit work in PR #2387."
        ),
    ),
    ("JoshCLWren/comic-pile", 2493): CuratedCopyRepair(
        original_title="Roling should not move the user to anywhere ont he screen",
        title="Keep the Roll page at the cover art when reading boundaries load",
        evidence=(
            "PR #2493 changed the Roll viewport hook to re-anchor the rating start "
            "when asynchronous reading-boundary content arrives for issue #2492."
        ),
    ),
}


def visible_release_text(value: object) -> str:
    """Return release copy as readers see it after stripping Markdown formatting.

    Args:
        value: Raw release copy that may contain Markdown links or backticks.

    Returns:
        The visible text with link syntax resolved and backticks unwrapped.
    """
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", str(value))
    return _BACKTICK_PATTERN.sub(r"\1", text)


def find_internal_artifact(
    field_name: str,
    value: object,
    *,
    title: str | None = None,
) -> str | None:
    """Describe the first internal engineering artifact in reader-facing copy.

    Args:
        field_name: Name of the release field being inspected.
        value: Raw release copy that may hide internal artifacts behind Markdown.
        title: Title of the same release, used to detect a summary that repeats it.

    Returns:
        A human-readable description of the offending fragment, or None when the
        copy reads as ordinary reader-facing product language.
    """
    text = visible_release_text(value)

    def _reason(kind: str, match: re.Match[str]) -> str:
        fragment = match.group(0).strip()
        return (
            f"{field_name} must use reader-facing product language: "
            f"{kind} '{fragment}'"
        )

    for pattern, kind in (
        (_TICKET_REFERENCE_PATTERN, "internal ticket reference"),
        (_SCHEMA_IDENTIFIER_PATTERN, "database/schema identifier"),
        (_PHASE_TERMINOLOGY_PATTERN, "implementation phase terminology"),
        (_UNFINISHED_WORK_PATTERN, "unfinished-work commentary"),
        (_INTERNAL_PATH_PATTERN, "internal file path"),
        (_TEST_NARRATIVE_PATTERN, "test-suite narrative"),
    ):
        if match := pattern.search(text):
            return _reason(kind, match)

    if match := _LEADING_SEPARATOR_PATTERN.search(text):
        return _reason("leading separator", match)

    if match := _MALFORMED_PUNCTUATION_PATTERN.search(text):
        return _reason("malformed punctuation", match)

    if field_name == "summary" and title and _repeats_title(text, title):
        return (
            "summary must not repeat the release title before adding new content"
        )

    lowered = text.lower()
    for wrong, right in _KNOWN_TYPOS.items():
        if re.search(rf"\b{re.escape(wrong)}\b", lowered):
            return (
                f"{field_name} must be spell-checked before publication: "
                f"'{wrong}' (did you mean '{right}'?)"
            )
    return None


def normalize_title(title: str) -> str:
    """Return a reader-facing title with historical prefixes and artifacts removed.

    Historical titles may carry internal ticket references, schema/database
    identifiers, implementation-phase prefixes, or dangling separators left
    behind by the writer's prefix stripping. Each is removed so internal
    engineering names never reach readers.

    Args:
        title: Stored release title.

    Returns:
        The normalized title. A title whose only content was an internal artifact
        becomes an empty string so the public card can be hidden.
    """
    text = visible_release_text(title)
    text = _PHASE_PREFIX_PATTERN.sub("", text)
    text = _LEADING_SEPARATOR_PATTERN.sub("", text)
    text = _remove_artifact_parentheticals(text)
    text = _TICKET_REFERENCE_PATTERN.sub("", text)
    text = _SCHEMA_IDENTIFIER_PATTERN.sub("", text)
    text = _PHASE_INLINE_PATTERN.sub("", text)
    text = _clean_punctuation(text).strip(" \t,;:-–—")
    if text and text[0].islower():
        text = f"{text[0].upper()}{text[1:]}"
    return text


def repair_summary(summary: str, *, title: str) -> str:
    """Return a reader-facing summary without mid-sentence holes.

    Historical copy sometimes embedded ticket references, schema identifiers,
    implementation phases, or internal file paths in the middle of a sentence.
    Token-level stripping leaves fragments behind, so artifact-bearing clauses
    and sentences are removed whole instead. A summary that only repeats the
    title becomes empty; the reader then sees the title once.

    Args:
        summary: Stored release summary.
        title: Normalized reader-facing title for the same release.

    Returns:
        The repaired summary, or an empty string when nothing reader-facing
        remains.
    """
    text = visible_release_text(summary)
    text = _strip_repeated_title(text, title)
    text = _remove_artifact_parentheticals(text)
    text = _remove_artifact_clauses(text)

    kept: list[str] = []
    for sentence in _SENTENCE_PATTERN.split(text):
        cleaned = _clean_punctuation(_LEADING_SEPARATOR_PATTERN.sub("", sentence.strip()))
        if not cleaned:
            continue
        # A lower-case connector at the start means the original head was
        # stripped from the stored copy. Dropping the fragment avoids serving
        # a sentence that begins mid-thought.
        if _DANGLING_HEAD_PATTERN.match(cleaned):
            continue
        if _contains_artifact(cleaned):
            if not _only_reference_artifacts(cleaned):
                continue
            cleaned = _clean_punctuation(
                _PHASE_INLINE_PATTERN.sub(
                    "",
                    _TICKET_REFERENCE_PATTERN.sub("", cleaned),
                )
            )
            if not cleaned:
                continue
        if _is_engineering_only(cleaned):
            continue
        kept.append(cleaned)

    result = " ".join(kept)
    if result == title:
        return ""
    return _clean_punctuation(result)


def repair_release_copy(
    *,
    source_repository: str,
    source_pr_number: int | None,
    title: str,
    summary: str,
) -> tuple[str, str]:
    """Return the reader-facing title and summary for one public release.

    PR-backed releases receive deterministic repair plus any reviewed canonical
    override. PR-less historical imports are returned unchanged because they are
    covered by the separate backfill cleanup tracked in #3646.

    Args:
        source_repository: Repository that owns the merged source pull request.
        source_pr_number: Merged source pull request number, or None for imports.
        title: Stored release title.
        summary: Stored release summary.

    Returns:
        The repaired title and summary.
    """
    if source_pr_number is None:
        return title, summary

    repair = CURATED_COPY_REPAIRS.get((source_repository, source_pr_number))
    if repair is not None and title.strip() == repair.original_title:
        repaired_title = normalize_title(repair.title)
        repaired_summary = (
            repair.summary
            if repair.summary is not None
            else repair_summary(summary, title=repaired_title)
        )
        return repaired_title, repaired_summary

    repaired_title = normalize_title(title)
    return repaired_title, repair_summary(summary, title=repaired_title)


def capability_claim_present(*values: object) -> bool:
    """Return whether any supplied copy makes a reader capability claim.

    Args:
        *values: Reader-facing fields to inspect.

    Returns:
        True when at least one field promises a new reader capability.
    """
    return any(_CAPABILITY_CLAIM_PATTERN.search(str(value)) for value in values)


def display_length(value: object) -> int:
    """Return the visible length of release copy after stripping Markdown.

    Args:
        value: Raw release copy that may contain Markdown links or backticks.

    Returns:
        The number of visible characters in the stripped text.
    """
    return len(visible_release_text(value).strip())


def _repeats_title(summary: str, title: str) -> bool:
    normalized_title = " ".join(visible_release_text(title).split()).strip(" .:;,!?–—-")
    if not normalized_title:
        return False
    normalized_summary = " ".join(visible_release_text(summary).lower().split())
    normalized_title = normalized_title.lower()
    if not normalized_summary.startswith(normalized_title):
        return False
    remainder = normalized_summary[len(normalized_title) :].lstrip(" .:;,!?–—-")
    return bool(remainder)


def _strip_repeated_title(summary: str, title: str) -> str:
    normalized_title = " ".join(visible_release_text(title).split()).strip(" .:;,!?–—-")
    if not normalized_title:
        return summary
    pattern = re.compile(
        rf"^{re.escape(normalized_title)}(?:\s*[.:;,!?–—-]\s*|\s+)",
        re.IGNORECASE,
    )
    match = pattern.match(summary)
    if match is None or not summary[match.end() :].strip():
        return summary
    return summary[match.end() :]


def _contains_artifact(text: str) -> bool:
    return any(
        pattern.search(text)
        for pattern in (
            _TICKET_REFERENCE_PATTERN,
            _SCHEMA_IDENTIFIER_PATTERN,
            _PHASE_TERMINOLOGY_PATTERN,
            _INTERNAL_PATH_PATTERN,
            _TEST_NARRATIVE_PATTERN,
        )
    )


def _only_reference_artifacts(text: str) -> bool:
    return not (
        _SCHEMA_IDENTIFIER_PATTERN.search(text)
        or _INTERNAL_PATH_PATTERN.search(text)
        or _TEST_NARRATIVE_PATTERN.search(text)
    )


def _remove_artifact_parentheticals(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return "" if _contains_artifact(match.group(0)) else match.group(0)

    return _PARENTHETICAL_PATTERN.sub(_replace, text)


def _remove_artifact_clauses(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return "" if _contains_artifact(match.group(0)) else match.group(0)

    return _ARTIFACT_CLAUSE_PATTERN.sub(_replace, text)


def _is_engineering_only(text: str) -> bool:
    if _READER_CUE_PATTERN.search(text):
        return False
    terms = {match.group(0).lower() for match in _ENGINEERING_ONLY_PATTERN.finditer(text)}
    return len(terms) >= _MIN_ENGINEERING_TERMS


def _clean_punctuation(text: str) -> str:
    text = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)
    text = re.sub(r"\.\s*\.(?![.])", ".", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" \t")
