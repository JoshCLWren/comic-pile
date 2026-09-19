"""User query construction and persistence.

All SQLAlchemy access for the ``User`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """Find a user by username.

    Args:
        db: Database session.
        username: Username to look up.

    Returns:
        The matching user, or ``None`` when absent.
    """
    result = await db.execute(select(User).where(User.username == username).limit(1))
    return result.scalar_one_or_none()


async def check_username_or_email_exists(
    db: AsyncSession,
    username: str,
    email: str | None,
) -> User | None:
    """Check whether a username or email is already registered.

    Args:
        db: Database session.
        username: Candidate username.
        email: Candidate email, or ``None``.

    Returns:
        The first conflicting user, or ``None`` when neither is taken.
    """
    conditions = [User.username == username]
    if email:
        conditions.append(User.email == email)
    result = await db.execute(select(User).where(or_(*conditions)).limit(1))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    email: str | None,
    password_hash: str,
) -> User:
    """Persist a newly constructed user.

    Args:
        db: Database session.
        username: Unique username.
        email: Optional email address.
        password_hash: Bcrypt-hashed password.

    Returns:
        The created ``User`` instance.
    """
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
    )
    db.add(user)
    return user
