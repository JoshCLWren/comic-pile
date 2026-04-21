-- Find what's blocking each Absolute/Ultimate thread
\copy (
    SELECT
        target_thread.id as thread_id,
        target_thread.title as thread_title,
        source_thread.title as blocked_by,
        source_issue.issue_number as blocked_by_issue,
        source_issue.status as blocking_issue_status,
        dep_target_issue.issue_number as blocked_issue_number,
        target_issue.position as blocked_issue_position,
        target_next_unread.position as next_unread_position,
        d.note as dependency_note
    FROM threads target_thread
    JOIN issues target_next_unread ON target_thread.next_unread_issue_id = target_next_unread.id
    JOIN issues dep_target_issue ON dep_target_issue.thread_id = target_thread.id 
        AND dep_target_issue.position >= target_next_unread.position
    JOIN dependencies d ON d.target_issue_id = dep_target_issue.id
    JOIN issues source_issue ON d.source_issue_id = source_issue.id
    JOIN threads source_thread ON source_issue.thread_id = source_thread.id
    WHERE target_thread.user_id = 25
      AND (target_thread.title ILIKE '%Absolute%' OR target_thread.title ILIKE '%Ultimate%')
      AND source_issue.status != 'read'
    ORDER BY target_thread.title, blocked_issue_position
) TO '/mnt/extra/josh/code/comic-pile/debug_blocking_sources.csv' WITH CSV HEADER;
