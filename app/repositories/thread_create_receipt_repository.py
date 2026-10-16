"""Query construction and persistence for thread creation idempotency receipts.

All SQLAlchemy access for :class:`~app.models.thread_create_receipt.ThreadCreateReceipt`
lives here. Functions return ORM models; the service layer owns transactions.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread_create_receipt import ThreadCreateReceipt


async def find_create_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
) -> ThreadCreateReceipt | None:
    """Return the durable receipt for one user's idempotency key, if it exists.

    Args:
        db: Async database session.
        user_id: Owner user ID the receipt must belong to.
        idempotency_key: Caller-supplied idempotency key.

    Returns:
        The stored receipt, or ``None`` when the key has never committed.
    """
    result = await db.execute(
        select(ThreadCreateReceipt).where(
            ThreadCreateReceipt.user_id == user_id,
            ThreadCreateReceipt.idempotency_key == idempotency_key,
        )
    )
    return result.scalars().first()


async def insert_create_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    thread_id: int,
    request_fingerprint: str,
) -> ThreadCreateReceipt:
    """Insert one idempotency receipt inside the caller's transaction.

    The flush is what surfaces the unique-constraint race: the caller commits
    on success and converges on the winning receipt when the flush raises
    ``IntegrityError``.

    Args:
        db: Async database session inside the creation transaction.
        user_id: Owner user ID.
        idempotency_key: Caller-supplied idempotency key.
        thread_id: Thread created by this request.
        request_fingerprint: Digest of the creation payload.

    Returns:
        The persisted receipt.
    """
    receipt = ThreadCreateReceipt(
        user_id=user_id,
        idempotency_key=idempotency_key,
        thread_id=thread_id,
        request_fingerprint=request_fingerprint,
    )
    db.add(receipt)
    await db.flush()
    return receipt


async def delete_create_receipt(
    db: AsyncSession, receipt: ThreadCreateReceipt
) -> None:
    """Remove a stale receipt whose thread no longer exists.

    Args:
        db: Async database session.
        receipt: Receipt to delete; the caller owns the commit.
    """
    await db.delete(receipt)
    await db.flush()
