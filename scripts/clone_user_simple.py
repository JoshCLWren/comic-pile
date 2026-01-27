"""Simple script to clone user data."""

from sqlalchemy import text
from app.database import SessionLocal

db = SessionLocal()

try:
    r = db.execute(text("SELECT id FROM users WHERE username = 'Josh'"))
    src = r.fetchone()
    if not src:
        print("Josh not found")
        exit(1)
    assert src is not None
    sid = src[0]

    db.execute(
        text(
            "INSERT INTO users (username, email, password_hash, is_admin, created_at) SELECT 'Josh_Test', split_part(email, '@', 1) || '_test@test.com', password_hash, is_admin, NOW() FROM users WHERE username = 'Josh'"
        )
    )
    db.commit()

    r = db.execute(text("SELECT id FROM users WHERE username = 'Josh_Test'"))
    result = r.fetchone()
    assert result is not None
    new_id = result[0]
    print(f"Created Josh_Test: {new_id}")

    db.execute(
        text(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, is_test, user_id, created_at) SELECT title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, True, :uid, NOW() FROM threads WHERE user_id = :sid"
        ),
        {"uid": new_id, "sid": sid},
    )
    db.commit()
    r = db.execute(text("SELECT COUNT(*) FROM threads WHERE user_id = :uid"), {"uid": new_id})
    count_result = r.fetchone()
    assert count_result is not None
    print(f"Cloned {count_result[0]} threads")

    print("Done!")
finally:
    db.close()
