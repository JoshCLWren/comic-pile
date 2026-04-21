-- After deleting circular dependencies, refresh all blocked flags
-- This will unblock threads that are no longer blocked by dependencies
WITH actual_blocked AS (
    SELECT DISTINCT target_thread.id
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
UPDATE threads
SET is_blocked = CASE WHEN ab.id IS NOT NULL THEN TRUE ELSE FALSE END
FROM (SELECT id FROM actual_blocked) AS ab
WHERE threads.user_id = 25
  AND threads.id = ab.id;

-- Set all other threads to unblocked
UPDATE threads
SET is_blocked = FALSE
WHERE user_id = 25
  AND id NOT IN (SELECT id FROM actual_blocked);
