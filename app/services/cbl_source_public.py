"""Reader-safe CBL source identity for public API responses.

Production historically stored the local mirror path
``/mnt/bigdata/CBL-ReadingLists`` as ``cbl_sources.repository``. That path
must never be returned to browsers.
"""

from __future__ import annotations

_MIRROR_NAME = "CBL-ReadingLists"
_PUBLIC_REPOSITORY = "JoshCLWren/CBL-ReadingLists"


def public_cbl_repository(repository: str) -> str:
    """Return a non-filesystem repository identity for public responses.

    Args:
        repository: Stored repository or local mirror path.

    Returns:
        A GitHub-style repository when the stored value is a filesystem path
        for the CBL reading-list mirror; otherwise the original value.
    """
    normalized = repository.strip().replace("\\", "/")
    if not _is_filesystem_location(normalized):
        return repository
    if normalized.rstrip("/").endswith(_MIRROR_NAME) or f"/{_MIRROR_NAME}" in normalized:
        return _PUBLIC_REPOSITORY
    return "CBL source"


def _is_filesystem_location(value: str) -> bool:
    """Return True when ``value`` looks like a local filesystem path."""
    return value.startswith("/") or value.startswith("file:") or value.startswith("mnt/")
