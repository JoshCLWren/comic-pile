"""Import reading orders from Google Sheets data."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import Thread, User

# Data from Google Sheets
READING_ORDERS = [
    ("Hellboy", "Omnibus", "Trade", "5", "10", "being human"),
    ("Superman", "All Star Superman", "Trade", "4.5", "10", "2"),
    ("Daredevil", "Born again", "Trade", "5", "6", "227"),
    ("Doom patrol", "Doom patrol pre grant morrison volume 1", "floppies", "2.5", "7", "3"),
    ("X-factor", "Declustered X-men reading order", "", "1", "5", "141"),
    (
        "silver surfer",
        "Marz / Lim era tapering off post infinity gauntlet ending at 60",
        "floppies",
        "2.5",
        "2",
        "58",
    ),
    ("avengers", "Starlin Cosmic avengers tie ins from Bronze Age", "floppies", "3", "1", "219"),
    ("Cable", "Declustered X-men reading order", "floppies", "3.5", "24", "49"),
    ("Dial h", "China Miéville run", "floppies", "3.5", "13", "1"),
    ("Wolverine -1", "One off ", "floppies", "", "", ""),
    ("Fantastic four masterworks", "First ten", "Hardcover", "1.5", "6", "4"),
    ("black panther", "Christopher priest black panther volume 1", "Omnibus", "3", "23", "9"),
    ("Earth 2", "James Robison earth 2", "floppies", "4", "9", "7"),
    ("animal man", "Jeff Lemire run", "graphic novel", "3.5", "7", "11"),
    ("starman", "James Robison and Starman related comics", "floppies", "3", "5", "22"),
    ("clandestine", "Clandestine series", "floppies", "3.5", "10", "8"),
    ("Generation X", "Declustered X-men reading order", "floppies", "2.5", "10", "35"),
    ("Micronauts", "Michael golden run", "special edition", "3.5", "2", "3"),
    ("wolverine", "Larry Hama run", "floppies", "4", "32", "48"),
    ("squadron supreme", "Mark Gruenwald Squadron Supreme stuff", "floppies", "3", "2", "10"),
    ("justice league", "Bwahaha", "floppies", "4.5", "28", "jli 13"),
    ("wildcats", "Wildcats and related titles", "floppies", "2", "11", "30"),
    ("Power man and iron fist 47", "Random", "floppies", "", "", ""),
    ("What if", "Various what ifs", "floppies", "", "7", "33"),
    ("Pint sized x-babies", "Declustered X-men reading order", "", "", "1", ""),
    ("X-men unlimited", "Declustered X-men reading order", "", "1.5", "5", "18"),
    (
        "conan saga",
        "Conan readthrough going through my Conan saga issues then on to Buscema and Thomas issues",
        "magazine",
        "4",
        "4",
        "savage tales 5",
    ),
    ("X-men Alpha Flight", "Declustered X-men reading order", "", "", "1", "1"),
    ("Xman", "Declustered X-men reading order", "floppies", "2.5", "9", "annual 97"),
    (
        "saga",
        "Saga trade paperbacks transitioning to single issues",
        "graphic novel",
        "2",
        "9",
        "22",
    ),
    ("X-men (both series)", "1998 sorted by release", "floppies", "3", "108", "uxm 352"),
    ("Far sector", "Dc compact", "Trade", "3", "11", "1"),
    ("Excalibur", "Declustered X-men reading order", "floppies", "2.5", "7", "117"),
    (
        "Warlock",
        "Starlin Cosmic Readthrough lead up to infinity war",
        "floppies",
        "3",
        "7",
        "marz two-in-one 63",
    ),
    ("Xforce", "Declustered X-men reading order", "floppies", "3.5", "30", "73"),
    ("Rom", "rom vlol 1", "floppies", "3.5", "6", "8"),
    ("exiles", "Exiles volume 1", "floppies", "5", "17", "26"),
    ("Dr strange", "epic collection volume 10", "epic collection", "4", "15", "35"),
]


async def import_reading_orders() -> None:
    """Clear existing threads and import reading orders from Google Sheets."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(User).where(User.id == 1))
            user = result.scalar_one_or_none()

            if user is None:
                user = User(id=1, username="demo_user")
                db.add(user)
                await db.commit()
                await db.refresh(user)
                print(f"Created user: {user.username}")

            user_id = user.id

            await db.execute(delete(Thread).where(Thread.user_id == user_id))
            await db.commit()
            print(f"Deleted all existing threads for user {user_id}")

            imported_count = 0
            skipped_count = 0

            for queue_position, entry in enumerate(READING_ORDERS, start=1):
                title, description, format_val, last_rating_str, issues_remaining_str, _ = entry

                if not title.strip():
                    skipped_count += 1
                    continue

                last_rating = None
                if last_rating_str.strip():
                    try:
                        last_rating = float(last_rating_str)
                    except ValueError:
                        pass

                issues_remaining = 0
                if issues_remaining_str.strip():
                    try:
                        issues_remaining = int(issues_remaining_str)
                    except ValueError:
                        pass

                full_title = f"{title.strip()}"
                if description and description.strip():
                    full_title = f"{title.strip()}: {description.strip()}"

                thread = Thread(
                    title=full_title[:200],
                    format=format_val.strip() if format_val.strip() else "Unknown",
                    issues_remaining=issues_remaining,
                    queue_position=queue_position,
                    status="active",
                    last_rating=last_rating,
                    user_id=user_id,
                    last_activity_at=datetime.now(UTC),
                )
                db.add(thread)
                imported_count += 1

            await db.commit()

            result = await db.execute(
                select(Thread).where(Thread.user_id == user_id).order_by(Thread.queue_position)
            )
            final_threads = result.scalars().all()

            print("\n=== Import Complete ===")
            print(f"Imported: {imported_count} threads")
            print(f"Skipped: {skipped_count} threads (missing title)")
            print(f"Total threads in DB: {len(final_threads)}")

            print("\n=== Imported Threads ===")
            for thread in final_threads:
                print(
                    f"{thread.queue_position:2d}. {thread.title[:50]:50s} | {thread.format:15s} | {thread.issues_remaining:3d} | {thread.last_rating}"
                )

        except Exception as e:
            await db.rollback()
            print(f"Error importing data: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(import_reading_orders())
