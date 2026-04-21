-- Check for stale is_blocked flags
-- This compares the denormalized is_blocked column with what SHOULD be blocked based on dependencies

WITH actual_blocked AS (
    SELECT DISTINCT target_thread.id as thread_id
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
)
SELECT
    t.id,
    t.title,
    t.is_blocked as current_flag,
    CASE WHEN ab.thread_id IS NOT NULL THEN TRUE ELSE FALSE END as should_be_blocked,
    CASE 
        WHEN t.is_blocked = TRUE AND ab.thread_id IS NULL THEN 'FALSE POSITIVE - should be UNBLOCKED'
        WHEN t.is_blocked = FALSE AND ab.thread_id IS NOT NULL THEN 'FALSE NEGATIVE - should be BLOCKED'
        ELSE 'CORRECT'
    END as flag_status
FROM threads t
LEFT JOIN actual_blocked ab ON t.id = ab.thread_id
WHERE t.user_id = 25
  AND t.status = 'active'
  AND t.queue_position >= 1
ORDER BY flag_status DESC, t.title;
