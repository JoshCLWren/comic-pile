#!/usr/bin/env python3
"""Import database from JSON file (wipe and restore)."""

import asyncio
import json
from datetime import datetime

from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models import Event, Session, Thread, User


async def import_database():
    """Wipe database and import data from JSON file."""
    async with AsyncSessionLocal() as db:
        try:
            with open("db_export.json") as f:
                data = json.load(f)

            print("=== Wiping database ===")

            await db.execute(delete(Event))
            await db.execute(delete(Session))
            await db.execute(delete(Thread))
            await db.execute(delete(User))
            await db.commit()

            print("Database wiped")

            print("\n=== Importing data ===")

            users_data = data.get("users", [])
            for u in users_data:
                user = User(
                    id=u["id"],
                    username=u["username"],
                    created_at=datetime.fromisoformat(u["created_at"]),
                )
                db.add(user)
            print(f"Imported {len(users_data)} users")

            threads_data = data.get("threads", [])
            for t in threads_data:
                thread = Thread(
                    id=t["id"],
                    title=t["title"],
                    format=t["format"],
                    issues_remaining=t["issues_remaining"],
                    queue_position=t["queue_position"],
                    status=t["status"],
                    last_rating=t["last_rating"],
                    last_activity_at=datetime.fromisoformat(t["last_activity_at"])
                    if t.get("last_activity_at")
                    else None,
                    review_url=t.get("review_url"),
                    last_review_at=datetime.fromisoformat(t["last_review_at"])
                    if t.get("last_review_at")
                    else None,
                    created_at=datetime.fromisoformat(t["created_at"]),
                    user_id=t["user_id"],
                )
                db.add(thread)
            print(f"Imported {len(threads_data)} threads")

            sessions_data = data.get("sessions", [])
            for s in sessions_data:
                session = Session(
                    id=s["id"],
                    started_at=datetime.fromisoformat(s["started_at"]),
                    ended_at=datetime.fromisoformat(s["ended_at"]) if s.get("ended_at") else None,
                    start_die=s["start_die"],
                    user_id=s["user_id"],
                    pending_thread_id=s.get("pending_thread_id"),
                    pending_thread_updated_at=datetime.fromisoformat(s["pending_thread_updated_at"])
                    if s.get("pending_thread_updated_at")
                    else None,
                )
                db.add(session)
            print(f"Imported {len(sessions_data)} sessions")

            events_data = data.get("events", [])
            for e in events_data:
                event = Event(
                    id=e["id"],
                    type=e["type"],
                    timestamp=datetime.fromisoformat(e["timestamp"]),
                    die=e["die"],
                    result=e["result"],
                    selected_thread_id=e.get("selected_thread_id"),
                    selection_method=e.get("selection_method"),
                    rating=e.get("rating"),
                    issues_read=e.get("issues_read"),
                    queue_move=e.get("queue_move"),
                    die_after=e.get("die_after"),
                    session_id=e["session_id"],
                    thread_id=e.get("thread_id"),
                )
                db.add(event)
            print(f"Imported {len(events_data)} events")

            await db.commit()

            print("\n=== Import complete ===")

        except Exception as e:
            await db.rollback()
            print(f"Error importing data: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(import_database())
