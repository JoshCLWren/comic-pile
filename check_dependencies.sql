-- Check dependencies for Josh's blocked threads
\copy (
    SELECT
        t.id as thread_id,
        t.title as thread_title,
        t.is_blocked,
        i.id as issue_id,
        i.issue_number,
        i.status as issue_status,
        d.note as dependency_note
    FROM threads t
    LEFT JOIN issues i ON t.id = i.thread_id
    LEFT JOIN dependencies d ON i.id = d.source_issue_id
    WHERE t.user_id = 25
      AND (t.title ILIKE '%Absolute%' OR t.title ILIKE '%Ultimate%')
    ORDER BY t.title, i.issue_number
) TO '/mnt/extra/josh/code/comic-pile/debug_dependencies.csv' WITH CSV HEADER;
