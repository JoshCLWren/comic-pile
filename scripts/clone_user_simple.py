#!/usr/bin/env python3
"""Simple script to clone user data."""

import asyncio

from sqlalchemy import text

from app.database import AsyncSessionLocal


async def clone_user():
    """Clone user data."""
    async with AsyncSessionLocal() as db:
        try:
            r = await db.execute(text("SELECT id FROM users WHERE username = 'Josh'"))
            src = r.fetchone()
            if not src:
                print("Josh not found")
                exit(1)
            assert src is not None
            sid = src[0]

            await db.execute(
                text(
                    "INSERT INTO users (username, email, password_hash, is_admin, created_at) SELECT 'Josh_Test', split_part(email, '@', 1) || '_test@test.com', password_hash, is_admin, NOW() FROM users WHERE username = 'Josh'"
                )
            )
            await db.commit()

            r = await db.execute(text("SELECT id FROM users WHERE username = 'Josh_Test'"))
            result = r.fetchone()
            assert result is not None
            new_id = result[0]
            print(f"Created Josh_Test: {new_id}")

            await db.execute(
                text(
                    "INSERT INTO threads (title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, is_test, user_id, created_at) SELECT title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, True, :uid, NOW() FROM threads WHERE user_id = :sid"
                ),
                {"uid": new_id, "sid": sid},
            )
            await db.commit()
            r = await db.execute(
                text("SELECT COUNT(*) FROM threads WHERE user_id = :uid"), {"uid": new_id}
            )
            count_result = r.fetchone()
            assert count_result is not None
            print(f"Cloned {count_result[0]} threads")

            print("Done!")
        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(clone_user())
