"""Private subprocess fixture data for browser password-reset lifecycle tests.

The caller captures stdout as an IPC pipe; token-bearing fixture data must never
be forwarded to logs. Operations are restricted to disposable test accounts.
"""

import asyncio
import hashlib
import json
import os
import secrets
import sys

import asyncpg
from dotenv import dotenv_values


async def fixture_data(operation: str, username: str) -> dict[str, object]:
    """Prepare, inspect, or clean up data owned by one disposable browser test.

    Args:
        operation: One of prepare, inspect, or cleanup.
        username: Disposable account with the cp-reset-e2e- prefix.

    Returns:
        Fixture data carried through the private parent-process pipe.
    """
    if not username.startswith("cp-reset-e2e-") or operation not in {"prepare", "inspect", "cleanup"}:
        raise ValueError("Only disposable password-reset test accounts are supported")
    local = dotenv_values(".env.test")
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or local.get("DATABASE_URL")
    if not url:
        raise ValueError("A database connection is required")
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        user_id = await conn.fetchval("SELECT id FROM users WHERE username=$1", username)
        if not isinstance(user_id, int):
            raise ValueError("Disposable test account was not found")
        async with conn.transaction():
            if operation == "prepare":
                session_id = await conn.fetchval(
                    "INSERT INTO sessions (user_id, started_at, start_die, reading_mode_suggested) "
                    "VALUES ($1, now(), 6, false) RETURNING id", user_id,
                )
                event_id = await conn.fetchval(
                    "INSERT INTO events (session_id, type, timestamp, die, result) "
                    "VALUES ($1, 'roll', now(), 6, 1) RETURNING id", session_id,
                )
                await conn.execute(
                    "INSERT INTO snapshots (session_id, event_id, thread_states, created_at) "
                    "VALUES ($1, $2, '{}'::json, now())", session_id, event_id,
                )
                token = secrets.token_urlsafe(32)
                await conn.execute(
                    "INSERT INTO password_reset_tokens (user_id, token_digest, expires_at, created_at) "
                    "VALUES ($1, $2, now() + interval '30 minutes', now())",
                    user_id, hashlib.sha256(token.encode()).hexdigest(),
                )
                return {"token": token}
            if operation == "inspect":
                row = await conn.fetchrow(
                    "SELECT (SELECT count(*) FROM sessions WHERE user_id=$1) AS sessions, "
                    "(SELECT count(*) FROM events WHERE session_id IN "
                    "(SELECT id FROM sessions WHERE user_id=$1)) AS events, "
                    "(SELECT count(*) FROM snapshots WHERE session_id IN "
                    "(SELECT id FROM sessions WHERE user_id=$1)) AS snapshots, "
                    "(SELECT count(*) FROM password_reset_tokens WHERE user_id=$1 "
                    "AND used_at IS NOT NULL) AS used_tokens", user_id,
                )
                return dict(row) if row else {}
            await conn.execute(
                "DELETE FROM snapshots WHERE session_id IN (SELECT id FROM sessions WHERE user_id=$1)", user_id,
            )
            await conn.execute(
                "DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE user_id=$1)", user_id,
            )
            await conn.execute("DELETE FROM password_reset_tokens WHERE user_id=$1", user_id)
            await conn.execute("DELETE FROM revoked_tokens WHERE user_id=$1", user_id)
            await conn.execute("DELETE FROM sessions WHERE user_id=$1", user_id)
            await conn.execute("DELETE FROM failed_login_attempts WHERE username=$1", username)
            await conn.execute("DELETE FROM users WHERE id=$1", user_id)
            return {"cleaned": True}
    finally:
        await conn.close()


if __name__ == "__main__":
    # stdout is a private IPC channel to the TypeScript browser test, not a log.
    sys.stdout.write(json.dumps(asyncio.run(fixture_data(sys.argv[1], sys.argv[2]))))
