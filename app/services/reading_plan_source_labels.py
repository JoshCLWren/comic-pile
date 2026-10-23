"""Readable owner-scoped labels for retained Reading Plan source references."""

import re
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reading_list_authoring_repository import owned_reading_list_names

_CUSTOM_SOURCE = re.compile(r"custom-cbl:([0-9]{1,10})")


async def load_reading_plan_source_names(
    db: AsyncSession,
    *,
    user_id: int,
    source_paths: Iterable[str],
) -> dict[str, str]:
    """Resolve owned custom-list source references without exposing foreign names.

    Args:
        db: Current read transaction.
        user_id: Reader whose source labels are requested.
        source_paths: Retained source reference strings, not display labels.

    Returns:
        Readable names keyed by the original reference; missing/foreign references
        are omitted so the UI can use a generic Reading List label.
    """
    references: dict[str, int] = {}
    for path in set(source_paths):
        match = _CUSTOM_SOURCE.fullmatch(path.strip())
        if match is not None and 0 < (list_id := int(match.group(1))) <= 2**31 - 1:
            references[path] = list_id
    names = await owned_reading_list_names(db, user_id, set(references.values()))
    return {path: names[list_id] for path, list_id in references.items() if list_id in names}
