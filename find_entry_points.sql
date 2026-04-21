-- Find entry point threads (not blocked by any dependencies)
\copy (
    WITH entry_points AS (
        SELECT DISTINCT t.id, t.title, t.queue_position, t.is_blocked, t.issues_remaining, t.total_issues
        FROM threads t
        WHERE t.user_id = 25
          AND t.status = 'active'
          AND t.queue_position >= 1
          AND t.is_blocked = FALSE
    )
    SELECT 
        ep.id,
        ep.title,
        ep.queue_position,
        ep.issues_remaining,
        ep.total_issues,
        COUNT(DISTINCT d.id) as dependencies_created_count
    FROM entry_points ep
    LEFT JOIN issues i ON i.thread_id = ep.id AND i.status = 'unread'
    LEFT JOIN dependencies d ON d.source_issue_id = i.id
    GROUP BY ep.id, ep.title, ep.queue_position, ep.issues_remaining, ep.total_issues
    ORDER BY ep.queue_position
) TO '/mnt/extra/josh/code/comic-pile/debug_entry_points.csv' WITH CSV HEADER;
