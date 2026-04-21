-- Find all circular dependency chains
\copy (
    WITH blocking_chains AS (
        SELECT
            target_thread.id as thread_id,
            target_thread.title as thread_title,
            source_thread.id as blocked_by_thread_id,
            source_thread.title as blocked_by_thread_title,
            CASE 
                WHEN target_thread.title ILIKE 'Absolute %' THEN 'Absolute'
                WHEN target_thread.title ILIKE 'Ultimate %' THEN 'Ultimate'
                WHEN target_thread.title ~ '^[A-Za-z]+:' THEN SUBSTRING(target_thread.title FROM '^(.*?):')
                ELSE SUBSTRING(target_thread.title FROM '^(.*?) ')
            END as target_series,
            CASE 
                WHEN source_thread.title ~ '^[A-Za-z]+:' THEN SUBSTRING(source_thread.title FROM '^(.*?):')
                ELSE SUBSTRING(source_thread.title FROM '^(.*?) ')
            END as source_series,
            COUNT(*) as dependency_count
        FROM threads target_thread
        JOIN issues target_next_unread ON target_thread.next_unread_issue_id = target_next_unread.id
        JOIN issues dep_target_issue ON dep_target_issue.thread_id = target_thread.id 
            AND dep_target_issue.position >= target_next_unread.position
        JOIN dependencies d ON d.target_issue_id = dep_target_issue.id
        JOIN issues source_issue ON d.source_issue_id = source_issue.id
        JOIN threads source_thread ON source_issue.thread_id = source_thread.id
        WHERE target_thread.user_id = 25
          AND source_thread.user_id = 25
          AND source_issue.status != 'read'
          AND target_thread.next_unread_issue_id IS NOT NULL
        GROUP BY 
            target_thread.id, target_thread.title,
            source_thread.id, source_thread.title
    )
    SELECT 
        thread_id,
        thread_title,
        blocked_by_thread_id,
        blocked_by_thread_title,
        target_series,
        source_series,
        dependency_count,
        CASE WHEN target_series = source_series THEN 'SAME SERIES - CIRCULAR' ELSE 'CROSS SERIES' END as chain_type
    FROM blocking_chains
    WHERE target_series = source_series
    ORDER BY thread_title, blocked_by_thread_title
) TO '/mnt/extra/josh/code/comic-pile/debug_circular_dependencies.csv' WITH CSV HEADER
