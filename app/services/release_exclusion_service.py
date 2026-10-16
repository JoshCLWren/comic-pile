"""Reader exclusions at confirmed release-volume adoption boundaries."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import collection_exclusion_repository


@dataclass(frozen=True, slots=True)
class ReleaseExclusions:
    """Explicit decisions for one owner; list-local skips are not consulted."""

    volume_ids: frozenset[int] = frozenset()
    thread_ids: frozenset[int] = frozenset()
    issue_ids: frozenset[int] = frozenset()

    def excludes_source(self, thread_id: int, volume_id: int) -> bool:
        """Check the stable, confirmed volume and target Thread before adoption."""
        return thread_id in self.thread_ids or volume_id in self.volume_ids


def comicvine_volume_id(value: str) -> int:
    """Normalize numeric and 4050-prefixed volume IDs without title inference."""
    text = value.strip().removeprefix("4050-")
    if not text.isdecimal():
        raise ValueError("ComicVine volume identity must be numeric")
    return int(text)


async def load_release_exclusions(db: AsyncSession, user_id: int) -> ReleaseExclusions:
    """Read current owner decisions under the caller's reader lock."""
    rows = await collection_exclusion_repository.list_for_owner(db, user_id)
    volumes: set[int] = set()
    for row in rows:
        if row.provider == "comicvine" and row.external_volume_id is not None:
            try:
                volumes.add(comicvine_volume_id(row.external_volume_id))
            except ValueError:
                # A malformed excluded identity cannot safely be ignored by a
                # mutating sync; the source fails closed for owner review.
                raise ValueError(
                    "Collection exclusion has an invalid ComicVine volume identity"
                ) from None
    return ReleaseExclusions(
        frozenset(volumes),
        frozenset(row.thread_id for row in rows if row.thread_id is not None),
        frozenset(row.issue_id for row in rows if row.issue_id is not None),
    )
