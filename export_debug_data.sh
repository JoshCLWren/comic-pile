-- Run these commands in your production psql session
-- Results will be saved to /mnt/extra/josh/code/comic-pile/debug_*.csv

\copy (
    SELECT
        id,
        title,
        format,
        status,
        is_blocked,
        queue_position,
        collection_id,
        issues_remaining,
        total_issues,
        created_at
    FROM threads
    WHERE user_id = 25
    ORDER BY created_at DESC
) TO '/mnt/extra/josh/code/comic-pile/debug_all_threads.csv' WITH CSV HEADER;

\copy (
    SELECT
        id,
        title,
        status,
        is_blocked,
        queue_position,
        issues_remaining,
        total_issues
    FROM threads
    WHERE user_id = 25
      AND (title ILIKE '%Absolute%' OR title ILIKE '%Ultimate%')
    ORDER BY title
) TO '/mnt/extra/josh/code/comic-pile/debug_absolute_ultimate.csv' WITH CSV HEADER;

\copy (
    SELECT
        id,
        title,
        format,
        status,
        is_blocked,
        queue_position,
        issues_remaining
    FROM threads
    WHERE user_id = 25
      AND status = 'active'
      AND is_blocked = FALSE
      AND queue_position >= 1
    ORDER BY queue_position
) TO '/mnt/extra/josh/code/comic-pile/debug_roll_pool.csv' WITH CSV HEADER;

\copy (
    SELECT id, snoozed_thread_ids FROM sessions WHERE user_id = 25
) TO '/mnt/extra/josh/code/comic-pile/debug_snoozed.csv' WITH CSV HEADER;

\copy (
    SELECT id, name, is_default, position FROM collections WHERE user_id = 25 ORDER BY position
) TO '/mnt/extra/josh/code/comic-pile/debug_collections.csv' WITH CSV HEADER;

\copy (
    SELECT status, COUNT(*) as count
    FROM threads
    WHERE user_id = 25
    GROUP BY status
) TO '/mnt/extra/josh/code/comic-pile/debug_status_breakdown.csv' WITH CSV HEADER;

\copy (
    SELECT id, title, is_blocked, queue_position
    FROM threads
    WHERE user_id = 25
      AND is_blocked = TRUE
    ORDER BY title
) TO '/mnt/extra/josh/code/comic-pile/debug_blocked.csv' WITH CSV HEADER;
