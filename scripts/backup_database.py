#!/usr/bin/env python3
"""Automated database backup with timestamp and rotation."""

import glob
import hashlib
import json
import os
import sys
from datetime import datetime

from app.database import SessionLocal
from app.models import Event, Session, Thread, User


def datetime_converter(obj):
    """Convert datetime objects to ISO format strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def compute_hash(data: dict) -> str:
    """Compute SHA256 hash of data dictionary."""
    data_str = json.dumps(data, sort_keys=True, default=datetime_converter)
    return hashlib.sha256(data_str.encode()).hexdigest()


def backup_database(backup_dir="backups", max_backups=10, skip_if_unchanged=True):
    """Create timestamped backup and rotate old backups."""
    os.makedirs(backup_dir, exist_ok=True)

    db = SessionLocal()
    try:
        data = {}

        users = db.query(User).all()
        data["users"] = [
            {"id": u.id, "username": u.username, "created_at": u.created_at} for u in users
        ]

        threads = db.query(Thread).all()
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

        sessions = db.query(Session).all()
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

        events = db.query(Event).all()
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

        data_hash = compute_hash(data)

        if skip_if_unchanged:
            all_backups = sorted(
                glob.glob(os.path.join(backup_dir, "db_export_*.json")),
                key=os.path.getmtime,
            )

            if all_backups:
                latest_backup = all_backups[-1]
                try:
                    with open(latest_backup) as f:
                        latest_data = json.load(f)
                    latest_hash = compute_hash(latest_data)

                    if data_hash == latest_hash:
                        print("Database unchanged - skipping backup")
                        print(
                            f"Latest backup: {os.path.basename(latest_backup)} "
                            f"({os.path.getsize(latest_backup)} bytes)"
                        )
                        return True
                except Exception as e:
                    print(f"Warning: Could not verify latest backup hash: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(backup_dir, f"db_export_{timestamp}.json")

        with open(filename, "w") as f:
            json.dump(data, f, default=datetime_converter, indent=2)

        backup_size = os.path.getsize(filename)
        print(f"Backup created: {filename} ({backup_size} bytes)")
        print(f"Data hash: {data_hash[:16]}...")

        all_backups = sorted(
            glob.glob(os.path.join(backup_dir, "db_export_*.json")),
            key=os.path.getmtime,
        )

        if len(all_backups) > max_backups:
            old_backups = all_backups[:-max_backups]
            for old_backup in old_backups:
                os.remove(old_backup)
                print(f"Removed old backup: {old_backup}")

        print(f"Total backups: {len(all_backups)} (max: {max_backups})")
        print(
            f"Users: {len(data['users'])}, Threads: {len(data['threads'])}, "
            f"Sessions: {len(data['sessions'])}, Events: {len(data['events'])}"
        )

    except Exception as e:
        print(f"Backup failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        db.close()

    return True


if __name__ == "__main__":
    backup_dir = os.getenv("BACKUP_DIR", "backups")
    max_backups = int(os.getenv("MAX_BACKUPS", "10"))
    skip_if_unchanged = os.getenv("SKIP_IF_UNCHANGED", "true").lower() == "true"

    success = backup_database(backup_dir, max_backups, skip_if_unchanged)
    sys.exit(0 if success else 1)
