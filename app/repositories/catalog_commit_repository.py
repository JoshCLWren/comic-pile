"""Query construction and persistence for catalog series-mapping commits.

All SQLAlchemy access for :class:`~app.models.catalog_commit_receipt.CatalogCommitReceipt`
lives here, along with the commit-time revalidation reads (owned issues and confirmed issue
identities) that must happen before any identity write. Functions return ORM models or plain
tuples; the service layer owns transaction boundaries.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog_commit_receipt import CatalogCommitReceipt
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread


async def find_commit_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
) -> CatalogCommitReceipt | None:
    """Return the durable receipt for one user's idempotency key, if it exists.

    Args:
        db: Async database session.
        user_id: Owner user ID the receipt must belong to.
        idempotency_key: Caller-supplied idempotency key.

    Returns:
        The stored receipt, or ``None`` when the key has never committed.
    """
    result = await db.execute(
        select(CatalogCommitReceipt).where(
            CatalogCommitReceipt.user_id == user_id,
            CatalogCommitReceipt.idempotency_key == idempotency_key,
        )
    )
    return result.scalars().first()


async def insert_commit_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    endpoint: str,
    request_fingerprint: str,
    response_json: dict[str, object],
) -> CatalogCommitReceipt:
    """Insert one idempotency receipt inside the caller's transaction.

    The flush is what surfaces the unique-constraint race: the caller commits on success and
    converges on the winning receipt when the flush raises ``IntegrityError``.

    Args:
        db: Async database session inside the identity transaction.
        user_id: Owner user ID.
        idempotency_key: Caller-supplied idempotency key.
        endpoint: Logical endpoint name recorded with the receipt.
        request_fingerprint: Digest of the complete material commit request.
        response_json: Logical result replayed for an identical retry.

    Returns:
        The persisted receipt.
    """
    receipt = CatalogCommitReceipt(
        user_id=user_id,
        idempotency_key=idempotency_key,
        endpoint=endpoint,
        request_fingerprint=request_fingerprint,
        response_json=response_json,
    )
    db.add(receipt)
    await db.flush()
    return receipt


async def list_owned_issue_ids(
    db: AsyncSession,
    *,
    user_id: int,
    issue_ids: Sequence[int],
) -> set[int]:
    """Return which of the requested issues belong to the user's threads.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_ids: Candidate ComicPile issue IDs from a preview row.

    Returns:
        The subset of ``issue_ids`` owned by this user.
    """
    if not issue_ids:
        return set()
    result = await db.execute(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(issue_ids), Thread.user_id == user_id)
    )
    return set(result.scalars().all())


async def list_confirmed_issue_identities(
    db: AsyncSession,
    *,
    issue_ids: Sequence[int],
) -> dict[int, set[tuple[str, str]]]:
    """Return every confirmed provider identity currently bound to each issue.

    Args:
        db: Async database session.
        issue_ids: Issues about to be confirmed by a bulk commit.

    Returns:
        Mapping of issue ID to the set of ``(provider, external_id)`` pairs that are already
        confirmed for that issue.
    """
    if not issue_ids:
        return {}
    result = await db.execute(
        select(
            IssueExternalIdentityMapping.issue_id,
            ExternalIdentity.provider,
            ExternalIdentity.external_id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id.in_(issue_ids),
            IssueExternalIdentityMapping.status == "confirmed",
        )
    )
    confirmed: dict[int, set[tuple[str, str]]] = {}
    for issue_id, provider, external_id in result:
        confirmed.setdefault(issue_id, set()).add((provider, external_id))
    return confirmed


async def list_thread_ids_for_series_issue_rows(
    db: AsyncSession,
    *,
    user_id: int,
    issue_ids: Iterable[int],
) -> set[int]:
    """Return the user's thread IDs that own the supplied issues.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        issue_ids: Issues confirmed by a bulk commit.

    Returns:
        The distinct thread IDs owned by this user for those issues.
    """
    issue_id_list = list(issue_ids)
    if not issue_id_list:
        return set()
    result = await db.execute(
        select(Thread.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(issue_id_list), Thread.user_id == user_id)
        .distinct()
    )
    return set(result.scalars().all())