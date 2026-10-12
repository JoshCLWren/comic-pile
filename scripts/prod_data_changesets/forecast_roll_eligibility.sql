-- Harvy-reproducible Roll forecast for user 1 after simulating c25530000001.
-- Production READ-ONLY. Do not wrap in a write transaction. No Neon clones.
--
-- Pair selection matches app.services.canonical_backfill._rule_native_pairs
-- (native item_read + converged, skip self) union existing canonical
-- Dependencies (note IS NULL OR note NOT LIKE 'cbl-order:%').
-- Blocked means the queued thread's next_unread_issue_id is the target of
-- an unread same-user source in that union.
--
-- Expected before FF merge (Neon 2026-10-12):
--   queued 320, eligible_today 34
--   blocked_canonical 50, blocked_item_read_only 189, blocked_converged_only 29
--   blocked_after 268, rollable_after 52
--   newly_available 18, newly_blocked 0

WITH queued AS (
    SELECT t.id, t.title, t.is_blocked, t.next_unread_issue_id
    FROM threads t
    WHERE t.user_id = 1
      AND t.status = 'active'
      AND t.queue_position IS NOT NULL
),
canonical AS (
    SELECT DISTINCT t.id
    FROM queued t
    JOIN dependencies d ON d.target_issue_id = t.next_unread_issue_id
    JOIN issues src ON src.id = d.source_issue_id
    JOIN threads st ON st.id = src.thread_id AND st.user_id = 1
    WHERE src.status <> 'read'
      AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%')
),
item_read AS (
    SELECT DISTINCT t.id
    FROM queued t
    JOIN continuity_rules r
      ON r.target_id = t.next_unread_issue_id
     AND r.legacy_dependency_id IS NULL
     AND r.satisfaction_type = 'item_read'
     AND r.source_type = 'issue' AND r.target_type = 'issue'
     AND r.source_id <> r.target_id
    JOIN issues src ON src.id = r.source_id
    JOIN threads st ON st.id = src.thread_id AND st.user_id = 1
    WHERE src.status <> 'read'
),
converged AS (
    SELECT DISTINCT t.id
    FROM queued t
    JOIN continuity_rules r
      ON r.target_id = t.next_unread_issue_id
     AND r.legacy_dependency_id IS NULL
     AND r.satisfaction_type = 'converged'
    JOIN LATERAL json_array_elements(r.convergence_targets) AS elem ON true
    JOIN issues src ON src.id = (elem->>'id')::int
    JOIN threads st ON st.id = src.thread_id AND st.user_id = 1
    WHERE (elem->>'id')::int <> r.target_id
      AND src.status <> 'read'
),
blocked_after AS (
    SELECT id FROM canonical
    UNION
    SELECT id FROM item_read
    UNION
    SELECT id FROM converged
)
SELECT
    (SELECT COUNT(*) FROM queued) AS queued,
    (SELECT COUNT(*) FROM queued WHERE is_blocked = false) AS eligible_today,
    (SELECT COUNT(*) FROM canonical) AS blocked_canonical,
    (SELECT COUNT(*) FROM item_read ir WHERE NOT EXISTS (
        SELECT 1 FROM canonical c WHERE c.id = ir.id
    )) AS blocked_item_read_only,
    (SELECT COUNT(*) FROM converged cv WHERE NOT EXISTS (
        SELECT 1 FROM canonical c WHERE c.id = cv.id
    ) AND NOT EXISTS (
        SELECT 1 FROM item_read ir WHERE ir.id = cv.id
    )) AS blocked_converged_only,
    (SELECT COUNT(*) FROM blocked_after) AS blocked_after,
    (SELECT COUNT(*) FROM queued) - (SELECT COUNT(*) FROM blocked_after) AS rollable_after,
    (
        SELECT COALESCE(array_agg(q.id ORDER BY q.id), ARRAY[]::int[])
        FROM queued q
        WHERE q.is_blocked = true
          AND NOT EXISTS (SELECT 1 FROM blocked_after b WHERE b.id = q.id)
    ) AS newly_available,
    (
        SELECT COALESCE(array_agg(q.id ORDER BY q.id), ARRAY[]::int[])
        FROM queued q
        WHERE q.is_blocked = false
          AND EXISTS (SELECT 1 FROM blocked_after b WHERE b.id = q.id)
    ) AS newly_blocked;
