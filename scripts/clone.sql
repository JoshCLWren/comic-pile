-- Clone Josh user to Josh_Test
WITH source_user AS (
    SELECT id, email, password_hash, is_admin FROM users WHERE username = 'Josh' LIMIT 1
),
new_user AS (
    INSERT INTO users (username, email, password_hash, is_admin, created_at)
    SELECT 'Josh_Test', split_part(email, '@', 1) || '_test@test.com', password_hash, is_admin, NOW() FROM source_user
    RETURNING id
)
INSERT INTO threads (title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, review_url, last_review_at, notes, is_test, user_id, created_at)
SELECT t.title, t.format, t.issues_remaining, t.queue_position, t.status, t.last_rating, t.last_activity_at, t.review_url, t.last_review_at, t.notes, True, (SELECT id FROM new_user), NOW()
FROM threads t WHERE t.user_id = (SELECT id FROM source_user);
