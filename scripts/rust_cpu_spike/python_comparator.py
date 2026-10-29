"""Local-only Python comparator for the Rust last-read projection subset.

Not ComicPile's complete /api/v2/roll/bootstrap endpoint.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.auth import get_current_user
from app.models.user import User

raw = os.environ["LOCAL_PROFILE_DATABASE_URL"]
parsed = urlsplit(raw.replace("+asyncpg", ""))
if parsed.hostname != "127.0.0.1" or parsed.port != 55435 or parsed.scheme not in ("postgres", "postgresql"):
    raise RuntimeError("Comparator accepts disposable loopback PostgreSQL only")

engine = create_async_engine(raw, pool_size=1, max_overflow=0)
sessions = async_sessionmaker(engine)
app = FastAPI()

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/spike/sessions/{session_id}/last-read")
async def last_read(session_id: int, user: User = Depends(get_current_user)):
    # Reuses ComicPile production auth dependency for the Python comparator.
    async with sessions() as db:
        owned = await db.execute(text(
            "SELECT id FROM sessions WHERE id=:sid AND user_id=:uid"
        ), {"sid": session_id, "uid": user.id})
        if owned.first() is None:
            raise HTTPException(404)
        result = await db.execute(text(
            """SELECT e.issue_id, COALESCE(i.issue_number, e.issue_number) AS issue_number,
                      e.thread_id, t.title AS thread_title, e.timestamp AS read_at
               FROM events e
               LEFT JOIN issues i ON i.id=e.issue_id
               LEFT JOIN threads t ON t.id=e.thread_id AND t.user_id=:uid
               WHERE e.session_id=:sid AND e.type='rate'
               ORDER BY e.timestamp DESC, e.id DESC LIMIT 1"""
        ), {"sid": session_id, "uid": user.id})
        row = result.mappings().first()
        if row is None:
            return None
        return {**dict(row), "read_at": row["read_at"].isoformat() if row["read_at"] else None}
