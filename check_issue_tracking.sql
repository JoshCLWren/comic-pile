-- Check next_unread_issue_id and issue tracking setup for Absolute/Ultimate threads
\copy (
    SELECT
        t.id,
        t.title,
        t.status,
        t.is_blocked,
        t.issues_remaining,
        t.total_issues,
        t.next_unread_issue_id,
        t.reading_progress,
        COUNT(i.id) as actual_issue_count,
        COUNT(CASE WHEN i.status = 'unread' THEN 1 END) as unread_count,
        COUNT(CASE WHEN i.status = 'read' THEN 1 END) as read_count
    FROM threads t
    LEFT JOIN issues i ON t.id = i.thread_id
    WHERE t.user_id = 25
      AND (t.title ILIKE '%Absolute%' OR t.title ILIKE '%Ultimate%')
    GROUP BY t.id, t.title, t.status, t.is_blocked, t.issues_remaining, t.total_issues, t.next_unread_issue_id, t.reading_progress
    ORDER BY t.title
) TO '/mnt/extra/josh/code/comic-pile/debug_issue_tracking.csv' WITH CSV HEADER;
