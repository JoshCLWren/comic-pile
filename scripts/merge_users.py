#!/usr/bin/env python3
r"""Merge two production users into a new user with separate collections.

Usage:
    python scripts/merge_users.py --new-user Plutar --password-env MERGE_PASSWORD \\
        --old-users Josh Josh_Digital_Comics \\
        --collection-names Josh "Digital Comics"
    python scripts/merge_users.py --dry-run ...   # Preview without changes

Set the password via environment variable (default: MERGE_PASSWORD).
"""

import argparse
import asyncio
import os
import sys

import bcrypt
from sqlalchemy import text

from app.database import AsyncSessionLocal


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: Plain-text password to hash.

    Returns:
        Bcrypt-hashed password string for storage.
    """
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def safe_rowcount(result: object) -> int:
    """Return rowcount when available, otherwise 0.

    Args:
        result: SQLAlchemy execute result or similar object.

    Returns:
        Integer row count when available; otherwise 0.
    """
    count = getattr(result, "rowcount", None)
    return count if isinstance(count, int) else 0


async def merge_users(
    *,
    new_username: str,
    password: str,
    old_users: list[str],
    collection_names: dict[str, str],
    dry_run: bool = False,
) -> None:
    """Merge old users into a single new user with separate collections.

    Args:
        new_username: Username for the new merged account.
        password: Plain-text password for the new account.
        old_users: Two existing usernames to merge.
        collection_names: Mapping of old username to destination collection name.
        dry_run: Whether to only print planned actions without persisting changes.

    Returns:
        None.
    """
    async with AsyncSessionLocal() as db:
        try:
            if len(old_users) != 2:
                raise ValueError("Exactly two old users are required.")
            first_old_name, second_old_name = old_users

            # 1. Verify old users exist
            old_user_ids: dict[str, int] = {}
            for username in old_users:
                r = await db.execute(
                    text("SELECT id FROM users WHERE username = :u"), {"u": username}
                )
                row = r.fetchone()
                if not row:
                    print(f"ERROR: User '{username}' not found")
                    return
                old_user_ids[username] = row[0]
                print(f"Found user '{username}' (id={row[0]})")

            # Check new user doesn't already exist
            r = await db.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": new_username}
            )
            if r.fetchone():
                print(f"ERROR: User '{new_username}' already exists")
                return

            # 2. Show current state
            for username, uid in old_user_ids.items():
                r = await db.execute(
                    text("SELECT COUNT(*) FROM threads WHERE user_id = :uid"), {"uid": uid}
                )
                row = r.fetchone()
                if row is None:
                    raise RuntimeError(f"Expected thread count row for user_id={uid} not found")
                print(f"  {username}: {row[0]} threads")

                r = await db.execute(
                    text("SELECT COUNT(*) FROM sessions WHERE user_id = :uid"), {"uid": uid}
                )
                row = r.fetchone()
                if row is None:
                    raise RuntimeError(f"Expected session count row for user_id={uid} not found")
                print(f"  {username}: {row[0]} sessions")

                r = await db.execute(
                    text("SELECT id, name, is_default FROM collections WHERE user_id = :uid"),
                    {"uid": uid},
                )
                cols = r.fetchall()
                print(f"  {username}: {len(cols)} collections: {cols}")

            if dry_run:
                print("\n--- DRY RUN: No changes made ---")
                return

            # 3. Create new user
            hashed = hash_password(password)
            await db.execute(
                text(
                    "INSERT INTO users (username, password_hash, is_admin, created_at) "
                    "VALUES (:username, :pw, false, NOW())"
                ),
                {"username": new_username, "pw": hashed},
            )
            await db.flush()

            r = await db.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": new_username}
            )
            row = r.fetchone()
            if row is None:
                raise RuntimeError(f"Expected newly created user '{new_username}' not found")
            new_user_id = row[0]
            print(f"\nCreated user '{new_username}' (id={new_user_id})")

            # 4. Create collections for each old user under new user
            collection_ids: dict[str, int] = {}
            for position, (username, col_name) in enumerate(collection_names.items()):
                is_default = position == 0
                await db.execute(
                    text(
                        "INSERT INTO collections (name, user_id, is_default, position, created_at) "
                        "VALUES (:name, :uid, :is_default, :pos, NOW())"
                    ),
                    {
                        "name": col_name,
                        "uid": new_user_id,
                        "is_default": is_default,
                        "pos": position,
                    },
                )
                await db.flush()
                r = await db.execute(
                    text(
                        "SELECT id FROM collections WHERE user_id = :uid AND name = :name"
                    ),
                    {"uid": new_user_id, "name": col_name},
                )
                row = r.fetchone()
                if row is None:
                    raise RuntimeError(
                        f"Expected collection '{col_name}' for user_id={new_user_id} not found"
                    )
                collection_ids[username] = row[0]
                print(f"Created collection '{col_name}' (id={row[0]}, default={is_default})")

            # 5. Reassign threads: update user_id and collection_id
            # First, get the max queue_position from the first user so we can offset the second
            r = await db.execute(
                text(
                    "SELECT COALESCE(MAX(queue_position), 0) FROM threads WHERE user_id = :uid"
                ),
                {"uid": old_user_ids[first_old_name]},
            )
            row = r.fetchone()
            if row is None:
                raise RuntimeError(
                    f"Expected max queue position row for user '{first_old_name}' not found"
                )
            max_pos_first = row[0]

            # Move first user's threads (keep their queue positions)
            r = await db.execute(
                text(
                    "UPDATE threads SET user_id = :new_uid, collection_id = :col_id "
                    "WHERE user_id = :old_uid"
                ),
                {
                    "new_uid": new_user_id,
                    "col_id": collection_ids[first_old_name],
                    "old_uid": old_user_ids[first_old_name],
                },
            )
            print(f"Moved {safe_rowcount(r)} threads from {first_old_name}")

            # Move second user's threads (offset queue positions)
            r = await db.execute(
                text(
                    "UPDATE threads SET user_id = :new_uid, collection_id = :col_id, "
                    "queue_position = queue_position + :offset "
                    "WHERE user_id = :old_uid"
                ),
                {
                    "new_uid": new_user_id,
                    "col_id": collection_ids[second_old_name],
                    "old_uid": old_user_ids[second_old_name],
                    "offset": max_pos_first,
                },
            )
            print(
                "Moved "
                f"{safe_rowcount(r)} threads from {second_old_name} (offset by {max_pos_first})"
            )

            # 6. Reassign sessions
            for username, uid in old_user_ids.items():
                r = await db.execute(
                    text("UPDATE sessions SET user_id = :new_uid WHERE user_id = :old_uid"),
                    {"new_uid": new_user_id, "old_uid": uid},
                )
                print(f"Moved {safe_rowcount(r)} sessions from {username}")

            # 7. Delete old users' revoked tokens (not needed for new user)
            for username, uid in old_user_ids.items():
                r = await db.execute(
                    text("DELETE FROM revoked_tokens WHERE user_id = :uid"), {"uid": uid}
                )
                print(f"Deleted {safe_rowcount(r)} revoked tokens from {username}")

            # 8. Delete old users' now-empty collections
            for username, uid in old_user_ids.items():
                r = await db.execute(
                    text("DELETE FROM collections WHERE user_id = :uid"), {"uid": uid}
                )
                print(f"Deleted {safe_rowcount(r)} old collections from {username}")

            # 9. Delete old users
            for username, uid in old_user_ids.items():
                r = await db.execute(
                    text("DELETE FROM users WHERE id = :uid"), {"uid": uid}
                )
                print(f"Deleted user '{username}' (id={uid})")

            await db.commit()
            print(f"\nDone! Log in as '{new_username}'")

        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge two users into a new combined user")
    parser.add_argument("--new-user", required=True, help="Username for the new combined user")
    parser.add_argument(
        "--password-env",
        default="MERGE_PASSWORD",
        help="Environment variable containing the password (default: MERGE_PASSWORD)",
    )
    parser.add_argument(
        "--old-users", nargs=2, required=True, help="Two usernames to merge"
    )
    parser.add_argument(
        "--collection-names",
        nargs=2,
        required=True,
        help="Collection names for each old user's threads (same order as --old-users)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    pw = os.environ.get(args.password_env)
    if not pw:
        print(f"ERROR: Set {args.password_env} environment variable with the password")
        sys.exit(1)

    col_map = dict(zip(args.old_users, args.collection_names, strict=True))
    asyncio.run(
        merge_users(
            new_username=args.new_user,
            password=pw,
            old_users=args.old_users,
            collection_names=col_map,
            dry_run=args.dry_run,
        )
    )
