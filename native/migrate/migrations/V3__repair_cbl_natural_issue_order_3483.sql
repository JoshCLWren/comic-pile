-- Migration 0003: repair the two production threads corrupted by CBL adoption
-- before the shared #3029 natural-order insertion routine was used (#3483).
--
-- Keep this repair limited to the reported all-ordinary-number threads. A broad
-- rewrite could destroy an intentional manual order on an unrelated thread.
-- Digit-string length then lexical order is numeric order for canonical
-- positive integers and cannot overflow, matching the Rust insertion routine.

SET CONSTRAINTS uq_issue_thread_position DEFERRED;

WITH affected_threads AS (
    SELECT thread_id
    FROM public.issues
    WHERE thread_id IN (17977, 17982)
    GROUP BY thread_id
    HAVING bool_and(issue_number ~ '^[1-9][0-9]*$')
), ranked AS (
    SELECT
        i.id,
        row_number() OVER (
            PARTITION BY i.thread_id
            ORDER BY length(i.issue_number), i.issue_number, i.id
        )::integer AS new_position
    FROM public.issues AS i
    JOIN affected_threads AS a ON a.thread_id = i.thread_id
)
UPDATE public.issues AS i
SET position = ranked.new_position
FROM ranked
WHERE i.id = ranked.id
  AND i.position <> ranked.new_position;

-- Reordering also changes which unread issue the reader must offer first.
WITH affected_threads AS (
    SELECT thread_id
    FROM public.issues
    WHERE thread_id IN (17977, 17982)
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
    FROM affected_threads AS a
)
UPDATE public.threads AS t
SET next_unread_issue_id = next_unread.issue_id
FROM next_unread
WHERE t.id = next_unread.thread_id;
