-- Migration 0003: repair production thread 17977 after CBL adoption appended
-- missing low issues instead of using the shared #3029 natural order (#3483).
--
-- Keep this repair limited to the reported thread and to canonical positive
-- integer issue numbers. Digit-string length then lexical order is numeric
-- order for those labels and cannot overflow, matching the Rust routine.

SET CONSTRAINTS public.uq_issue_thread_position DEFERRED;

WITH affected_thread AS (
    SELECT thread_id
    FROM public.issues
    WHERE thread_id = 17977
    GROUP BY thread_id
    HAVING bool_and(issue_number ~ '^[1-9][0-9]*$')
), ranked AS (
    SELECT
        i.id,
        row_number() OVER (
            ORDER BY length(i.issue_number), i.issue_number, i.id
        )::integer AS new_position
    FROM public.issues AS i
    JOIN affected_thread AS a ON a.thread_id = i.thread_id
)
UPDATE public.issues AS i
SET position = ranked.new_position
FROM ranked
WHERE i.id = ranked.id
  AND i.position <> ranked.new_position;

-- Reordering also changes which unread issue the reader must be offered first.
WITH affected_thread AS (
    SELECT thread_id
    FROM public.issues
    WHERE thread_id = 17977
    GROUP BY thread_id
    HAVING bool_and(issue_number ~ '^[1-9][0-9]*$')
), next_unread AS (
    SELECT
        a.thread_id,
        (
            SELECT i.id
            FROM public.issues AS i
            WHERE i.thread_id = a.thread_id
              AND i.status <> 'read'
            ORDER BY i.position, i.id
            LIMIT 1
        ) AS issue_id
    FROM affected_thread AS a
)
UPDATE public.threads AS t
SET next_unread_issue_id = next_unread.issue_id
FROM next_unread
WHERE t.id = next_unread.thread_id;
