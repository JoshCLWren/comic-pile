-- Fantastic Four series-thread reattach (user 1).
-- HELD. Josh approves before this runs against production. No Neon clones.
-- Production read-only preflight first; this file is the reviewed transaction.
--
-- Goal: one series thread. SQL: one guarded transaction, no backup tables.
-- Rollback data is the recorded change set in
-- 001_ff_series_thread_merge_rollback.sql (deterministic issue-id mapping).
--
-- Proven by source data (Neon 2026-10-12, single SELECTs):
--   threads 3166 and 18560 both map to ComicVine series 2045
--   3166 holds #1-102 (positions 1-102); 18560 holds #103-231 (positions 1-125)
--   issue_number overlap = 0
--   18560 issue ids 115395-115519 consecutive, position = id - 115394, all unread
-- Issue rows are UPDATEd, never deleted or recreated. Ids, status, read_at stay.
-- Annuals / Giant-Size threads 18545, 18565, 18666 are not in this script.
--
-- Before:
--   3166 Fantastic Four (1961): 102 issues, 19 read / 83 unread, next 23029 = #16
--        issues_remaining column is stale 87 (actual unread 83)
--   18560 Fantastic Four (1970): 125 unread, next 115395 = #103
--        queue_position 208, mapping 378 → identity 12970 conf 0.95
-- After:
--   3166 owns 227 issues, positions 1-227, next unread stays 23029 = #16
--   issues_remaining = 208 (83+125); do not add 125 to stale 87
--   18560 deleted (zero issues)
--   mapping 378 dropped (same ComicVine series 2045 as mapping 67)

BEGIN;

DO $$
DECLARE
    rec RECORD;
    n bigint;
    json_n bigint;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM threads
        WHERE id = 3166 AND user_id = 1 AND title = 'Fantastic Four (1961)'
    ) THEN
        RAISE EXCEPTION 'canonical thread 3166 title/owner guard failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM threads
        WHERE id = 18560 AND user_id = 1 AND title = 'Fantastic Four (1970)'
          AND queue_position = 208
          AND total_issues = 125
          AND next_unread_issue_id = 115395
    ) THEN
        RAISE EXCEPTION 'split thread 18560 title/owner/frontier guard failed';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 3166) <> 102 THEN
        RAISE EXCEPTION 'canonical thread 3166 expected 102 issues';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 18560) <> 125 THEN
        RAISE EXCEPTION 'split thread 18560 expected 125 issues';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 3166 AND status = 'read') <> 19 THEN
        RAISE EXCEPTION 'canonical thread 3166 expected 19 read issues';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issues WHERE thread_id = 18560 AND (status <> 'unread' OR read_at IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'split issues must all be unread with null read_at';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM issues a
        JOIN issues b ON a.issue_number = b.issue_number
        WHERE a.thread_id = 3166 AND b.thread_id = 18560
    ) THEN
        RAISE EXCEPTION 'issue_number overlap between 3166 and 18560';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issues
        WHERE thread_id = 18560
          AND (id < 115395 OR id > 115519 OR position <> id - 115394)
    ) THEN
        RAISE EXCEPTION 'split issue ids/positions drifted from 115395-115519 / id-115394';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE id BETWEEN 115395 AND 115519) <> 125 THEN
        RAISE EXCEPTION 'expected 125 consecutive split issue ids 115395-115519';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM thread_external_series_mappings
        WHERE id = 378 AND thread_id = 18560 AND external_identity_id = 12970
          AND status = 'confirmed' AND confidence = 0.95
    ) THEN
        RAISE EXCEPTION 'mapping 378 guard failed';
    END IF;

    -- Every FK to threads.id. Expected: issues=125, mapping=1, all others 0.
    FOR rec IN
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND ccu.table_name = 'threads'
          AND ccu.column_name = 'id'
        ORDER BY tc.table_name, kcu.column_name
    LOOP
        EXECUTE format(
            'SELECT COUNT(*) FROM %I WHERE %I = 18560',
            rec.table_name,
            rec.column_name
        ) INTO n;
        IF rec.table_name = 'issues' AND rec.column_name = 'thread_id' THEN
            IF n <> 125 THEN
                RAISE EXCEPTION 'issues.thread_id expected 125, found %', n;
            END IF;
        ELSIF rec.table_name = 'thread_external_series_mappings'
           AND rec.column_name = 'thread_id' THEN
            IF n <> 1 THEN
                RAISE EXCEPTION 'thread_external_series_mappings expected 1, found %', n;
            END IF;
        ELSIF n <> 0 THEN
            RAISE EXCEPTION 'unexpected FK %.% = % rows pointing at thread 18560',
                rec.table_name, rec.column_name, n;
        END IF;
    END LOOP;

    IF (SELECT COUNT(*) FROM events WHERE selected_thread_id = 18560) <> 0 THEN
        RAISE EXCEPTION 'unexpected events.selected_thread_id references to 18560';
    END IF;

    SELECT COUNT(*) INTO json_n
    FROM sessions s,
         LATERAL json_array_elements_text(COALESCE(s.snoozed_thread_ids, '[]'::json)) AS elem
    WHERE elem = '18560';
    IF json_n <> 0 THEN
        RAISE EXCEPTION 'unexpected snoozed_thread_ids references to 18560';
    END IF;
    SELECT COUNT(*) INTO json_n
    FROM sessions s,
         LATERAL json_array_elements_text(COALESCE(s.skipped_thread_ids, '[]'::json)) AS elem
    WHERE elem = '18560';
    IF json_n <> 0 THEN
        RAISE EXCEPTION 'unexpected skipped_thread_ids references to 18560';
    END IF;
    SELECT COUNT(*) INTO json_n
    FROM threads t,
         LATERAL json_array_elements_text(COALESCE(t.blocked_by_thread_ids, '[]'::json)) AS elem
    WHERE elem = '18560';
    IF json_n <> 0 THEN
        RAISE EXCEPTION 'unexpected blocked_by_thread_ids references to 18560';
    END IF;
    IF EXISTS (
        SELECT 1 FROM continuity_plans WHERE nodes_json::text LIKE '%18560%'
    ) THEN
        RAISE EXCEPTION 'unexpected continuity_plans.nodes_json references to 18560';
    END IF;
END $$;

UPDATE threads SET next_unread_issue_id = NULL WHERE id = 18560;

UPDATE issues
SET
    thread_id = 3166,
    position = position + 102
WHERE thread_id = 18560
  AND id BETWEEN 115395 AND 115519;

DELETE FROM thread_external_series_mappings
WHERE id = 378
  AND thread_id = 18560
  AND external_identity_id = 12970;

UPDATE threads
SET
    total_issues = 227,
    issues_remaining = (
        SELECT COUNT(*) FROM issues WHERE thread_id = 3166 AND status <> 'read'
    ),
    next_unread_issue_id = 23029,
    reading_progress = 'in_progress'
WHERE id = 3166;

DELETE FROM threads WHERE id = 18560 AND user_id = 1;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 3166) <> 227 THEN
        RAISE EXCEPTION 'canonical thread did not receive 227 issues';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE id BETWEEN 115395 AND 115519 AND thread_id = 3166) <> 125 THEN
        RAISE EXCEPTION 'split issue ids did not all move onto 3166';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issues
        WHERE id BETWEEN 115395 AND 115519
          AND (status <> 'unread' OR read_at IS NOT NULL OR position <> id - 115394 + 102)
    ) THEN
        RAISE EXCEPTION 'split issue status/history/position drifted during merge';
    END IF;
    IF EXISTS (SELECT 1 FROM threads WHERE id = 18560) THEN
        RAISE EXCEPTION 'split thread 18560 still exists';
    END IF;
    IF (SELECT next_unread_issue_id FROM threads WHERE id = 3166) <> 23029 THEN
        RAISE EXCEPTION 'next unread must remain issue 23029 (#16)';
    END IF;
    IF (SELECT issues_remaining FROM threads WHERE id = 3166) <> 208 THEN
        RAISE EXCEPTION 'issues_remaining must be 208 (83+125), not stale 87+125';
    END IF;
    IF EXISTS (SELECT 1 FROM thread_external_series_mappings WHERE id = 378) THEN
        RAISE EXCEPTION 'mapping 378 should have been dropped';
    END IF;
END $$;

COMMIT;
