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


def public_cbl_source_ref(repository: str, source_path: str) -> str:
    """Return a reader-safe ``repository:path`` identity for public responses.

    Args:
        repository: Stored repository or local mirror path.
        source_path: Stored CBL source path, possibly under the local mirror.

    Returns:
        A colon-joined public repository and relative source path.
    """
    return f"{public_cbl_repository(repository)}:{public_cbl_source_path(source_path)}"


def public_cbl_source_path(source_path: str) -> str:
    """Return a source path without host-directory prefixes.

    Args:
        source_path: Stored CBL source path.

    Returns:
        A relative path or filename when ``source_path`` is a filesystem
        location; otherwise the original value.
    """
    normalized = source_path.strip().replace("\\", "/")
    if not normalized:
        return source_path
    marker = f"{_MIRROR_NAME}/"
    marker_index = normalized.find(marker)
    if marker_index >= 0:
        remainder = normalized[marker_index + len(marker) :]
        return remainder or _MIRROR_NAME
    if _is_filesystem_location(normalized):
        file_name = normalized.rsplit("/", maxsplit=1)[-1]
        return file_name or "CBL source"
    return source_path


def _is_filesystem_location(value: str) -> bool:
    """Return True when ``value`` looks like a local filesystem path."""
    return value.startswith("/") or value.startswith("file:") or value.startswith("mnt/")
