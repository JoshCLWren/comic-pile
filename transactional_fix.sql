-- SAFE TRANSACTIONAL APPROACH FOR PRODUCTION
-- Step 1: Start transaction and verify what will be deleted

BEGIN;

-- Step 2: See exactly what dependencies will be deleted
SELECT 
    d.id as dependency_id,
    source_thread.title as source_thread,
    source_issue.issue_number as source_issue,
    target_thread.title as target_thread,
    target_issue.issue_number as target_issue,
    d.note
FROM dependencies d
JOIN issues source_issue ON d.source_issue_id = source_issue.id
JOIN issues target_issue ON d.target_issue_id = target_issue.id
JOIN threads source_thread ON source_issue.thread_id = source_thread.id
JOIN threads target_thread ON target_issue.thread_id = target_thread.id
WHERE source_thread.user_id = 25
  AND target_thread.user_id = 25
  AND (
      -- Same series detection
      (source_thread.title ILIKE 'Absolute %' AND target_thread.title ILIKE 'Absolute %')
      OR (source_thread.title ILIKE 'Ultimate %' AND target_thread.title ILIKE 'Ultimate %')
      OR (source_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)' 
          AND target_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)')
      OR SUBSTRING(source_thread.title FROM '^(.*?):') = SUBSTRING(target_thread.title FROM '^(.*?):')
  )
ORDER BY source_thread.title, target_thread.title;

-- Step 3: Count what will be deleted
SELECT COUNT(*) as dependencies_to_delete FROM dependencies
WHERE id IN (
    WITH same_series_deps AS (
        SELECT d.id
        FROM dependencies d
        JOIN issues source_issue ON d.source_issue_id = source_issue.id
        JOIN issues target_issue ON d.target_issue_id = target_issue.id
        JOIN threads source_thread ON source_issue.thread_id = source_thread.id
        JOIN threads target_thread ON target_issue.thread_id = target_thread.id
        WHERE source_thread.user_id = 25
          AND target_thread.user_id = 25
          AND (
              (source_thread.title ILIKE 'Absolute %' AND target_thread.title ILIKE 'Absolute %')
              OR (source_thread.title ILIKE 'Ultimate %' AND target_thread.title ILIKE 'Ultimate %')
              OR (source_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)' 
                  AND target_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)')
              OR SUBSTRING(source_thread.title FROM '^(.*?):') = SUBSTRING(target_thread.title FROM '^(.*?):')
          )
    )
    SELECT id FROM same_series_deps
);

-- Step 4: Delete the dependencies (only if you approve above results)
DELETE FROM dependencies
WHERE id IN (
    WITH same_series_deps AS (
        SELECT d.id
        FROM dependencies d
        JOIN issues source_issue ON d.source_issue_id = source_issue.id
        JOIN issues target_issue ON d.target_issue_id = target_issue.id
        JOIN threads source_thread ON source_issue.thread_id = source_thread.id
        JOIN threads target_thread ON target_issue.thread_id = target_thread.id
        WHERE source_thread.user_id = 25
          AND target_thread.user_id = 25
          AND (
              (source_thread.title ILIKE 'Absolute %' AND target_thread.title ILIKE 'Absolute %')
              OR (source_thread.title ILIKE 'Ultimate %' AND target_thread.title ILIKE 'Ultimate %')
              OR (source_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)' 
                  AND target_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)')
              OR SUBSTRING(source_thread.title FROM '^(.*?):') = SUBSTRING(target_thread.title FROM '^(.*?):')
          )
    )
    SELECT id FROM same_series_deps
);

-- Step 5: Recalculate blocked flags
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

UPDATE threads
SET is_blocked = FALSE
WHERE user_id = 25
  AND id NOT IN (SELECT id FROM actual_blocked);

-- Step 6: Verify results before committing
SELECT title, is_blocked FROM threads WHERE user_id = 25 AND (title ILIKE '%Absolute%' OR title ILIKE '%Ultimate%') ORDER BY title;

-- Review the results above, then run: COMMIT;
-- Or if something looks wrong, run: ROLLBACK;
