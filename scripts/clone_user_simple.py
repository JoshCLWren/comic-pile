"""Simple script to clone user data."""

from sqlalchemy import text
from app.database import SessionLocal

db = SessionLocal()

r = db.execute(text("SELECT id FROM users WHERE username = 'Josh'"))
src = r.fetchone()
if not src:
    print("Josh not found")
    exit(1)
sid = src[0]

db.execute(
    text(
        "INSERT INTO users (username, email, password_hash, is_admin, created_at) SELECT 'Josh_Test', email || '_test@test.com', password_hash, is_admin, NOW() FROM users WHERE username = 'Josh'"
    )
)
db.commit()

r = db.execute(text("SELECT id FROM users WHERE username = 'Josh_Test'"))
new_id = r.fetchone()[0]
print(f"Created Josh_Test: {new_id}")

db.execute(
    text(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, is_test, user_id, created_at) SELECT title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, True, :uid, NOW() FROM threads WHERE user_id = :sid"
    ),
    {"uid": new_id, "sid": sid},
)
db.commit()
r = db.execute(text("SELECT COUNT(*) FROM threads WHERE user_id = :uid"), {"uid": new_id})
print(f"Cloned {r.fetchone()[0]} threads")

print("Done!")
