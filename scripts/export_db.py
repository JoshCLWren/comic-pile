#!/usr/bin/env python3
"""Export database to JSON file."""

import asyncio
import json
from datetime import datetime

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Event, Session, Thread, User


def datetime_converter(obj):
    """Convert datetime objects to ISO format strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


async def export_database():
    """Export all database tables to JSON file."""
    async with AsyncSessionLocal() as db:
        try:
            data = {}

            result = await db.execute(select(User))
            users = result.scalars().all()
            data["users"] = [
                {
                    "id": u.id,
                    "username": u.username,
                    "created_at": u.created_at,
                }
                for u in users
            ]

            result = await db.execute(select(Thread))
            threads = result.scalars().all()
            data["threads"] = [
                {
                    "id": t.id,
                    "title": t.title,
                    "format": t.format,
                    "issues_remaining": t.issues_remaining,
                    "queue_position": t.queue_position,
                    "status": t.status,
                    "last_rating": t.last_rating,
                    "last_activity_at": t.last_activity_at,
                    "review_url": t.review_url,
                    "last_review_at": t.last_review_at,
                    "created_at": t.created_at,
                    "user_id": t.user_id,
                }
                for t in threads
            ]

            result = await db.execute(select(Session))
            sessions = result.scalars().all()
            data["sessions"] = [
                {
                    "id": s.id,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "start_die": s.start_die,
                    "user_id": s.user_id,
                    "pending_thread_id": s.pending_thread_id,
                    "pending_thread_updated_at": s.pending_thread_updated_at,
                }
                for s in sessions
            ]

            result = await db.execute(select(Event))
            events = result.scalars().all()
            data["events"] = [
                {
                    "id": e.id,
                    "type": e.type,
                    "timestamp": e.timestamp,
                    "die": e.die,
                    "result": e.result,
                    "selected_thread_id": e.selected_thread_id,
                    "selection_method": e.selection_method,
                    "rating": e.rating,
                    "issues_read": e.issues_read,
                    "queue_move": e.queue_move,
                    "die_after": e.die_after,
                    "session_id": e.session_id,
                    "thread_id": e.thread_id,
                }
                for e in events
            ]

            filename = "db_export.json"
            with open(filename, "w") as f:
                json.dump(data, f, default=datetime_converter, indent=2)

            print(f"Exported database to {filename}")
            print(f"Users: {len(data['users'])}")
            print(f"Threads: {len(data['threads'])}")
            print(f"Sessions: {len(data['sessions'])}")
            print(f"Events: {len(data['events'])}")

        finally:
            pass


if __name__ == "__main__":
    asyncio.run(export_database())
