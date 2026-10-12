-- Fantastic Four series-thread reattach (user 1).
-- HELD. Josh approves before this runs against production. No Neon clones.
-- Production read-only preflight first; this file is the reviewed transaction.
--
-- Goal: one series thread. SQL: one guarded transaction, no backup tables.
-- Recorded change set: 001_ff_series_thread_merge_recorded.json
-- (live row_to_json of thread 18560, mapping 378, and 3166 restore fields).
-- Rollback restores via jsonb_populate_record from that receipt, not
-- hard-coded INSERT column lists.
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
--
-- Lock order: parent threads, then issues, then FK children, then polymorphic
-- referencing rows. Guards run only after those locks are held.

BEGIN;

DO $$
DECLARE
    rec RECORD;
    lock_rec RECORD;
    n bigint;
    json_n bigint;
    live_split jsonb;
    live_mapping jsonb;
    live_canonical jsonb;
    recorded_split jsonb := $rec_split${"id":18560,"title":"Fantastic Four (1970)","format":"Comic","issues_remaining":125,"queue_position":208,"status":"active","last_rating":null,"last_activity_at":null,"created_at":"2026-08-31T11:26:07.658653+00:00","user_id":1,"notes":"Broad saved-CBL representation; ComicVine volume 2045.","is_test":false,"is_blocked":true,"total_issues":125,"next_unread_issue_id":115395,"reading_progress":"not_started","blocked_by_thread_ids":null,"blocked_by_issue_ids":null,"manual_creator_credits":[],"catalog_series_id":null}$rec_split$::jsonb;
    recorded_mapping jsonb := $rec_mapping${"id":378,"thread_id":18560,"external_identity_id":12970,"status":"confirmed","evidence_source":"broad_cbl_volume_representation","confidence":0.95,"created_at":"2026-08-31T11:26:07.658653+00:00","updated_at":"2026-08-31T11:26:07.658653+00:00"}$rec_mapping$::jsonb;
    recorded_canonical jsonb := $rec_canonical${"id":3166,"title":"Fantastic Four (1961)","format":"Comics","reading_progress":"in_progress","next_unread_issue_id":23029,"total_issues":102,"queue_position":205,"status":"active","user_id":1}$rec_canonical$::jsonb;
BEGIN
    -- (1) Locks before any guard. Parents first, then children, stable id order.
    FOR lock_rec IN
        SELECT id FROM threads WHERE id IN (3166, 18560) ORDER BY id FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT id
        FROM issues
        WHERE thread_id IN (3166, 18560) OR id BETWEEN 115395 AND 115519
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR rec IN
        SELECT rel.relname AS table_name, att.attname AS column_name
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS cols(attnum, ord) ON true
        JOIN pg_attribute att
          ON att.attrelid = rel.oid AND att.attnum = cols.attnum
        JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS refs(attnum, ord)
          ON refs.ord = cols.ord
        JOIN pg_attribute ratt
          ON ratt.attrelid = con.confrelid AND ratt.attnum = refs.attnum
        WHERE con.contype = 'f'
          AND con.confrelid = 'public.threads'::regclass
          AND ratt.attname = 'id'
          AND nsp.nspname = 'public'
        ORDER BY rel.relname, att.attname
    LOOP
        FOR lock_rec IN EXECUTE format(
            'SELECT 1 FROM %I WHERE %I IN (3166, 18560) ORDER BY ctid FOR UPDATE',
            rec.table_name,
            rec.column_name
        )
        LOOP
            NULL;
        END LOOP;
    END LOOP;

    FOR lock_rec IN
        SELECT id
        FROM events
        WHERE selected_thread_id IN (3166, 18560)
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT s.id
        FROM sessions s
        WHERE EXISTS (
            SELECT 1
            FROM json_array_elements_text(COALESCE(s.snoozed_thread_ids, '[]'::json)) AS elem
            WHERE elem IN ('3166', '18560')
        ) OR EXISTS (
            SELECT 1
            FROM json_array_elements_text(COALESCE(s.skipped_thread_ids, '[]'::json)) AS elem
            WHERE elem IN ('3166', '18560')
        )
        ORDER BY s.id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT t.id
        FROM threads t,
             LATERAL json_array_elements_text(
                 COALESCE(t.blocked_by_thread_ids, '[]'::json)
             ) AS elem
        WHERE elem IN ('3166', '18560') AND t.id NOT IN (3166, 18560)
        ORDER BY t.id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT id
        FROM continuity_rules
        WHERE (lower(source_type) = 'thread' AND source_id IN (3166, 18560))
           OR (lower(target_type) = 'thread' AND target_id IN (3166, 18560))
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT id
        FROM tag_assignments
        WHERE lower(target_type) = 'thread' AND target_id IN (3166, 18560)
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT p.id
        FROM continuity_plans p,
             LATERAL json_array_elements(COALESCE(p.nodes_json, '[]'::json)) AS node
        WHERE lower(COALESCE(node->>'node_type', '')) = 'thread'
          AND (node->>'ref_id') ~ '^[0-9]+$'
          AND (node->>'ref_id')::bigint IN (3166, 18560)
        ORDER BY p.id
        FOR UPDATE OF p
    LOOP
        NULL;
    END LOOP;

    -- Record live rows and assert they match the change-set receipt.
    SELECT row_to_json(t)::jsonb INTO live_split FROM threads t WHERE id = 18560;
    SELECT row_to_json(m)::jsonb INTO live_mapping
    FROM thread_external_series_mappings m WHERE id = 378;
    SELECT jsonb_build_object(
        'id', t.id,
        'title', t.title,
        'format', t.format,
        'reading_progress', t.reading_progress,
        'next_unread_issue_id', t.next_unread_issue_id,
        'total_issues', t.total_issues,
        'queue_position', t.queue_position,
        'status', t.status,
        'user_id', t.user_id
    ) INTO live_canonical
    FROM threads t WHERE id = 3166;

    IF live_split IS DISTINCT FROM recorded_split THEN
        RAISE EXCEPTION
            'thread 18560 live row_to_json does not match recorded change set: %',
            live_split;
    END IF;
    IF live_mapping IS DISTINCT FROM recorded_mapping THEN
        RAISE EXCEPTION
            'mapping 378 live row_to_json does not match recorded change set: %',
            live_mapping;
    END IF;
    IF live_canonical IS DISTINCT FROM recorded_canonical THEN
        RAISE EXCEPTION
            'canonical thread 3166 restore fields do not match recorded change set: %',
            live_canonical;
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

    -- Every FK to threads.id. Expected: issues=125, mapping=1, all others 0.
    FOR rec IN
        SELECT rel.relname AS table_name, att.attname AS column_name
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS cols(attnum, ord) ON true
        JOIN pg_attribute att
          ON att.attrelid = rel.oid AND att.attnum = cols.attnum
        JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS refs(attnum, ord)
          ON refs.ord = cols.ord
        JOIN pg_attribute ratt
          ON ratt.attrelid = con.confrelid AND ratt.attnum = refs.attnum
        WHERE con.contype = 'f'
          AND con.confrelid = 'public.threads'::regclass
          AND ratt.attname = 'id'
          AND nsp.nspname = 'public'
        ORDER BY rel.relname, att.attname
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

    -- Polymorphic thread endpoints (no FK): continuity_rules, tag_assignments,
    -- continuity_plans thread nodes.
    IF EXISTS (
        SELECT 1 FROM continuity_rules
        WHERE (lower(source_type) = 'thread' AND source_id = 18560)
           OR (lower(target_type) = 'thread' AND target_id = 18560)
    ) THEN
        RAISE EXCEPTION 'unexpected continuity_rules thread endpoint referencing 18560';
    END IF;
    IF EXISTS (
        SELECT 1 FROM tag_assignments
        WHERE lower(target_type) = 'thread' AND target_id = 18560
    ) THEN
        RAISE EXCEPTION 'unexpected tag_assignments Thread target referencing 18560';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM continuity_plans p,
             LATERAL json_array_elements(COALESCE(p.nodes_json, '[]'::json)) AS node
        WHERE lower(COALESCE(node->>'node_type', '')) = 'thread'
          AND (node->>'ref_id') ~ '^[0-9]+$'
          AND (node->>'ref_id')::bigint = 18560
    ) THEN
        RAISE EXCEPTION 'unexpected continuity_plans thread node referencing 18560';
    END IF;
    IF EXISTS (
        SELECT 1 FROM continuity_rules r,
             LATERAL json_array_elements(COALESCE(r.convergence_targets, '[]'::json)) AS elem
        WHERE lower(COALESCE(elem->>'type', elem->>'node_type', '')) = 'thread'
          AND (elem->>'id') ~ '^[0-9]+$'
          AND (elem->>'id')::bigint = 18560
    ) THEN
        RAISE EXCEPTION 'unexpected continuity_rules convergence thread target 18560';
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
    next_unread_issue_id = 23029
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
