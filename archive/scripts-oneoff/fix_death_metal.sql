-- Fix Dark Knights: Death Metal stale thread state
-- Thread id=352, user id=25 (Josh_Digital_Comics)
--
-- Diagnosis: all 7 issues have read_at populated and status='read',
-- but thread still shows issues_remaining=1, next_unread_issue_id=10619,
-- status='active'. Stale denormalized data.
--
-- Guard: the WHERE clause includes a subquery confirming zero unread issues
-- exist. If our diagnosis is wrong this UPDATE matches 0 rows and is a no-op.

BEGIN;

UPDATE threads
SET
    status               = 'completed',
    issues_remaining     = 0,
    next_unread_issue_id = NULL,
    reading_progress     = 'completed'
WHERE id = 352
  AND user_id = 25
  AND (
      SELECT COUNT(*)
      FROM issues
      WHERE thread_id = 352
        AND status = 'unread'
  ) = 0;

-- Show result so we can confirm 1 row was updated
SELECT
    id,
    title,
    status,
    issues_remaining,
    next_unread_issue_id,
    reading_progress
FROM threads
WHERE id = 352;

COMMIT;
