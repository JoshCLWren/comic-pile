"""Seed database with sample data using Faker."""

import random

from dotenv import load_dotenv

load_dotenv()

from faker import Faker
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Event, Session, Thread, User
from comic_pile import DICE_LADDER

fake = Faker()

FORMATS = ["TPB", "Issue", "Graphic Novel", "OGN"]


def seed_database(num_threads: int = 25, num_sessions: int = 7) -> None:
    import os

    print(f"DATABASE_URL: {os.getenv('DATABASE_URL')}")
    """Seed database with sample threads, sessions, and events.

    Args:
        num_threads: Number of threads to create (default 25).
        num_sessions: Number of sessions to create (default 7).
    """
    db = SessionLocal()

    try:
        user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()

        if user is None:
            user = User(id=1, username="demo_user")
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Created user: {user.username}")

        existing_threads = (
            db.execute(select(Thread).where(Thread.user_id == user.id)).scalars().all()
        )

        for thread in existing_threads:
            thread.queue_position = len(existing_threads) + thread.id

        db.commit()

        for i in range(num_threads):
            title = fake.sentence(nb_words=4).rstrip(".")
            format_val = random.choice(FORMATS)
            issues_remaining = random.randint(1, 50)

            thread = Thread(
                title=title,
                format=format_val,
                issues_remaining=issues_remaining,
                queue_position=i + 1,
                status="active",
                is_test=True,
                user_id=user.id,
                last_rating=random.uniform(0.5, 5.0) if random.random() > 0.3 else None,
            )
            db.add(thread)

        db.commit()

        threads = (
            db.execute(
                select(Thread).where(Thread.user_id == user.id).order_by(Thread.queue_position)
            )
            .scalars()
            .all()
        )

        threads_list = list(threads)
        created_sessions = []

        for _i in range(num_sessions):
            start_time = fake.date_time_between(start_date="-30d", end_date="now")
            end_time = fake.date_time_between(start_date=start_time, end_date="now")
            start_die = random.choice(DICE_LADDER)

            session = Session(
                started_at=start_time,
                ended_at=end_time,
                start_die=start_die,
                user_id=user.id,
            )
            db.add(session)
            db.flush()
            created_sessions.append(session)

            num_events = random.randint(2, 5)
            current_die = start_die

            for _j in range(num_events):
                event_type = random.choice(["roll", "rate"])
                timestamp = fake.date_time_between(start_date=start_time, end_date=end_time)
            db.add(session)
            db.flush()
            created_sessions.append(session)

            num_events = random.randint(2, 5)
            current_die = start_die

            for _j in range(num_events):
                event_type = random.choice(["roll", "rate"])
                timestamp = fake.date_time_between(start_date=start_time, end_date=end_time)

                if event_type == "roll":
                    if threads_list:
                        selected_thread = random.choice(threads_list)
                        result = random.randint(1, current_die)
                        selection_method = random.choice(["dice", "override"])

                        event = Event(
                            type="roll",
                            timestamp=timestamp,
                            die=current_die,
                            result=result,
                            selected_thread_id=selected_thread.id,
                            selection_method=selection_method,
                            session_id=session.id,
                        )
                        db.add(event)

                        if result > 10:
                            current_die = min(current_die + 2, DICE_LADDER[-1])
                        elif result < 5:
                            current_die = max(current_die - 2, DICE_LADDER[0])

                else:
                    if threads_list:
                        selected_thread = random.choice(threads_list)
                        rating = round(random.uniform(0.5, 5.0), 1)
                        issues_read = random.randint(1, 5)
                        queue_move = random.choice(["back", "front", "middle"])
                        die_after = random.choice(DICE_LADDER)

                        event = Event(
                            type="rate",
                            timestamp=timestamp,
                            rating=rating,
                            issues_read=issues_read,
                            queue_move=queue_move,
                            die_after=die_after,
                            thread_id=selected_thread.id,
                            session_id=session.id,
                        )
                        db.add(event)

        db.commit()

        final_threads = db.execute(select(Thread).where(Thread.user_id == user.id)).scalars().all()
        final_sessions = (
            db.execute(select(Session).where(Session.user_id == user.id)).scalars().all()
        )
        final_events = db.execute(select(Event)).scalars().all()

        print("\n=== Database Seeding Complete ===")
        print(f"User: {user.username} (ID: {user.id})")
        print(f"Threads: {len(final_threads)}")
        print(f"Sessions: {len(final_sessions)}")
        print(f"Events: {len(final_events)}")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
