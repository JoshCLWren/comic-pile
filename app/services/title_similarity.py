"""Title resemblance scoring for advisory duplicate detection.

Comic volumes legitimately share titles (for example *Spider-Man* relaunches or
*Uncanny X-Men* across decades), so a title is never treated as identity. These
helpers only decide whether two titles are close enough that the reader might
want to double-check an existing series, and how confident that resemblance is.
Canonical provider identity remains the strong signal owned by the duplicate
check service.
"""

#: Minimum title resemblance that still counts as a possible existing volume.
MIN_TITLE_SIMILARITY = 0.5

_MIN_SIGNIFICANT_TOKEN_LENGTH = 3
_MAX_SIGNIFICANT_TOKENS = 6


def normalize_title(title: str) -> str:
    """Reduce a display title to comparable lowercase alphanumeric tokens.

    Punctuation, hyphenation, and spacing are not identity: ``"Spider-Man"``
    and ``"spider man"`` normalize to the same value so a hyphenated run is not
    missed by a candidate search.

    Letters and digits from every script are preserved. Comic titles are not
    ASCII-only: a series such as ``"進撃の巨人"`` or ``"Pokémon"`` must keep its
    own characters, otherwise normalization would erase the title and the
    reader would never be warned about an exact duplicate.

    Args:
        title: Reader- or provider-supplied display title.

    Returns:
        The normalized title with single-space separated lowercase tokens, or an
        empty string when the title has no alphanumeric content.
    """
    cleaned = "".join(character if character.isalnum() else " " for character in title.casefold())
    return " ".join(cleaned.split())


def significant_title_tokens(
    normalized_title: str,
    *,
    min_length: int = _MIN_SIGNIFICANT_TOKEN_LENGTH,
    limit: int = _MAX_SIGNIFICANT_TOKENS,
) -> tuple[str, ...]:
    """Select the tokens worth using as a coarse candidate-search filter.

    Candidate search runs in SQL so it cannot normalize stored titles the same
    way Python does. Single-token fragments are still usable, but very short
    tokens (``"x"``, ``"of"``) would match almost the whole library, so they are
    dropped when longer tokens exist.

    Args:
        normalized_title: Output of :func:`normalize_title`.
        min_length: Shortest token length considered significant.
        limit: Maximum number of tokens returned.

    Returns:
        Up to ``limit`` distinct tokens, longest first, in input order for equal
        lengths. Empty when the normalized title is blank.
    """
    tokens = list(dict.fromkeys(normalized_title.split()))
    significant = [token for token in tokens if len(token) >= min_length]
    if not significant:
        return tuple(tokens[:limit])
    ordered = sorted(significant, key=len, reverse=True)
    return tuple(ordered[:limit])


def title_similarity(proposed: str, existing: str) -> float:
    """Score how closely two titles resemble each other.

    Args:
        proposed: Title the reader is creating or renaming to.
        existing: Title of a series the reader already owns.

    Returns:
        ``1.0`` for the same normalized title, ``0.8`` when one title is a
        whole-token phrase inside the other, otherwise the Jaccard overlap of
        the two token sets. ``0.0`` when either title has no usable content.
    """
    proposed_normalized = normalize_title(proposed)
    existing_normalized = normalize_title(existing)
    if not proposed_normalized or not existing_normalized:
        return 0.0
    if proposed_normalized == existing_normalized:
        return 1.0
    if (
        f" {proposed_normalized} " in f" {existing_normalized} "
        or f" {existing_normalized} " in f" {proposed_normalized} "
    ):
        return 0.8
    proposed_tokens = set(proposed_normalized.split())
    existing_tokens = set(existing_normalized.split())
    union = proposed_tokens | existing_tokens
    if not union:
        return 0.0
    return len(proposed_tokens & existing_tokens) / len(union)
