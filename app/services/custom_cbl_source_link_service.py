"""First-add source-link scaffolding for CBL adoption into Option E lists (#4021).

The reader-owned destination for adopting a shared CBL source is a stable
per-reader, per-source mapping row (:class:`CustomCBLSourceLink`) whose
``custom_cbl_list_id`` is the reader's editable Option E Reading List. This
module implements the first-add side of that contract:

- the link is keyed by the external source identity, never by title matching,
  and its destination is always an owned custom CBL list -- never a legacy
  ``ContinuityPlan`` receipt;
- the shared source catalog never gains a ``user_id``: two readers share the
  same source facts while keeping fully separate owned lists and link rows;
- the first-add is transactional and idempotent: the same user/source always
  converges on one owned list, even when a lost response, retry, or concurrent
  commit races the insert (the ``uq_custom_cbl_source_link_user_source``
  constraint plus a reader lock is the durable guarantee);
- the source's revision and content hash are captured on the link at
  first-add time so later source changes are compared and reviewed, not
  automatically applied;
- an unrelated manually named owned list is never searched for or replaced.

Entry materialization, update-after-preview semantics, and stale-source
rejection live in the separately scoped Option E upsert transaction
(#4022); this scaffolding stops at the durable link without UI cutover.
Production CBL backfill or reader repair is not part of this work.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLList
from app.models.custom_cbl_source_link import CustomCBLSourceLink
from app.repositories import cbl_source_repository
from app.repositories.custom_cbl_source_link_repository import (
    find_link_for_list,
    find_link_for_user_source,
    get_owned_list,
    insert_link,
)
from app.repositories.reading_list_authoring_repository import lock_reader

_LIST_NAME_MAX = 200


@dataclass(frozen=True, slots=True)
class FirstAddSourceLinkResult:
    """Outcome of one first-add source-link call.

    Attributes:
        link: The durable per-reader, per-source link row.
        owned_list: The reader-owned Option E destination list.
    """

    link: CustomCBLSourceLink
    owned_list: CustomCBLList


async def get_owned_destination(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
) -> FirstAddSourceLinkResult:
    """Return the reader's linked Option E list for one CBL source, read-only.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        cbl_source_list_id: Shared CBL source list ID.

    Returns:
        The link and its owned destination list.

    Raises:
        HTTPException: 404 when this reader has never linked the source.
    """
    link = await find_link_for_user_source(
        db, user_id=user_id, cbl_source_list_id=cbl_source_list_id
    )
    if link is None:
        raise HTTPException(
            status_code=404,
            detail=f"No linked Reading List for CBL source {cbl_source_list_id}",
        )
    owned_list = await get_owned_list(db, custom_cbl_list_id=link.custom_cbl_list_id)
    if owned_list is None or owned_list.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Linked Reading List no longer exists",
        )
    return FirstAddSourceLinkResult(link=link, owned_list=owned_list)


async def ensure_first_add_link(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
    list_name: str | None = None,
) -> FirstAddSourceLinkResult:
    """Create or return the reader's durable source link for one CBL source.

    First add for a reader and an external CBL source creates exactly one new
    owned Option E list and its link; every subsequent call -- including
    retries and concurrent commits -- returns the existing link and owned
    list without creating a second one. The owned list is always newly
    created here; an existing same-named owned list is never adopted from or
    replaced by title matching.

    Args:
        db: Async database session inside the caller's transaction.
        user_id: Owner user ID.
        cbl_source_list_id: Shared CBL source list ID.
        list_name: Optional custom destination list name; defaults to the
            source list name truncated to the owned-list name limit.

    Returns:
        The link and its owned destination list.

    Raises:
        HTTPException: 404 when the source list ID is unknown, or 409 when
            the source list is inactive.
    """
    await lock_reader(db, user_id)
    existing_link = await find_link_for_user_source(
        db, user_id=user_id, cbl_source_list_id=cbl_source_list_id
    )
    if existing_link is not None:
        owned_list = await get_owned_list(
            db, custom_cbl_list_id=existing_link.custom_cbl_list_id
        )
        if owned_list is None:
            raise HTTPException(
                status_code=409,
                detail="Linked Reading List no longer exists",
            )
        return FirstAddSourceLinkResult(link=existing_link, owned_list=owned_list)

    source_row = await cbl_source_repository.get_source_list(
        db, cbl_source_list_id=cbl_source_list_id
    )
    if source_row is None:
        raise HTTPException(status_code=404, detail=f"CBL source {cbl_source_list_id} not found")
    source_list, _repository = source_row
    if not source_list.active:
        raise HTTPException(
            status_code=409,
            detail=f"CBL source {cbl_source_list_id} is no longer active",
        )

    destination_name = (list_name or source_list.name)[:_LIST_NAME_MAX]
    savepoint = await db.begin_nested()
    try:
        new_list = CustomCBLList(
            user_id=user_id,
            name=destination_name,
            mode="loose",
        )
        db.add(new_list)
        await db.flush()
        link = await insert_link(
            db,
            user_id=user_id,
            cbl_source_list_id=cbl_source_list_id,
            custom_cbl_list_id=new_list.id,
            source_revision_sha=source_list.revision_sha,
            source_content_hash=source_list.content_hash,
        )
        await savepoint.commit()
    except IntegrityError:
        await savepoint.rollback()
        # A concurrent first add for the same reader and source won the
        # unique claim. Converge on its link instead of creating a second
        # owned list.
        winner = await find_link_for_user_source(
            db, user_id=user_id, cbl_source_list_id=cbl_source_list_id
        )
        if winner is None:
            raise
        owned_list = await get_owned_list(db, custom_cbl_list_id=winner.custom_cbl_list_id)
        if owned_list is None:
            raise HTTPException(
                status_code=409,
                detail="Linked Reading List no longer exists",
            ) from None
        return FirstAddSourceLinkResult(link=winner, owned_list=owned_list)
    return FirstAddSourceLinkResult(link=link, owned_list=new_list)


async def require_owned_linked_source(
    db: AsyncSession,
    *,
    user_id: int,
    custom_cbl_list_id: int,
) -> FirstAddSourceLinkResult:
    """Resolve the source link that claims an owned custom CBL list.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        custom_cbl_list_id: Reader-owned custom CBL list ID.

    Returns:
        The claiming link and the owned list.

    Raises:
        HTTPException: 404 when the list does not belong to this reader, or
            409 when no source link claims it (for example a manually
            authored list).
    """
    link = await find_link_for_list(db, custom_cbl_list_id=custom_cbl_list_id)
    owned_list = await get_owned_list(db, custom_cbl_list_id=custom_cbl_list_id)
    if owned_list is None or owned_list.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail=f"Custom CBL {custom_cbl_list_id} not found",
        )
    if link is None:
        raise HTTPException(
            status_code=409,
            detail=f"Custom CBL {custom_cbl_list_id} is not linked to a CBL source",
        )
    return FirstAddSourceLinkResult(link=link, owned_list=owned_list)
