-- Delete all same-series dependencies (circular blocking chains)
-- This will unblock your Absolute/Ultimate/Annihilation/DC K.O. threads
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
              -- Same series detection
              (source_thread.title ILIKE 'Absolute %' AND target_thread.title ILIKE 'Absolute %')
              OR (source_thread.title ILIKE 'Ultimate %' AND target_thread.title ILIKE 'Ultimate %')
              OR (source_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)' 
                  AND target_thread.title ~ '^(Annihilation|DC K\.O\.|Drax|Justice League|Stormwatch|The Ultimates)')
              OR SUBSTRING(source_thread.title FROM '^(.*?):') = SUBSTRING(target_thread.title FROM '^(.*?):')
          )
    )
    SELECT id FROM same_series_deps
);
