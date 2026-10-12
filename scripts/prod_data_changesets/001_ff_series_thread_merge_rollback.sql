-- Rollback for 001_ff_series_thread_merge.sql.
-- HELD. Josh approves before this runs against production. No backup tables.
-- Restore from the recorded change set in
-- 001_ff_series_thread_merge_recorded.json:
--   split issue ids 115395-115519
--   original position = id - 115394
--   post-merge position = id - 115394 + 102
--   thread 18560 and mapping 378 via jsonb_populate_record (no hard-coded
--   INSERT column lists); restored rows are asserted equal to the receipt
--
-- Refuses if intervening writes (reads, position changes, extra issues, a
-- drifted 3166 frontier, or drifted dependencies / reading_plan_issues /
-- events vs the merge-time receipt) would make restoration overwrite
-- progress. The moved-refs baseline is the locked live fingerprint
-- persisted by 001_ff_series_thread_merge.sql, not the preflight constant.
-- Pre-existing cbl-order dependencies on the moved issue ids are part of
-- that receipt and are not themselves a reason to refuse.

BEGIN;

SET LOCAL TimeZone = 'UTC';

DO $$
DECLARE
    lock_rec RECORD;
    live_deps jsonb;
    live_plan_issues jsonb;
    live_events jsonb;
    live_refs jsonb;
    recorded_refs jsonb;
    recorded_canonical jsonb := $rec_canonical${"id":3166,"title":"Fantastic Four (1961)","format":"Comics","reading_progress":"in_progress","next_unread_issue_id":23029,"total_issues":102,"queue_position":205,"status":"active","user_id":1}$rec_canonical$::jsonb;
BEGIN
    IF to_regclass('public.prod_changeset_001_ff_moved_refs_receipt') IS NULL THEN
        RAISE EXCEPTION 'missing merge-time moved-refs receipt table; refuse rollback';
    END IF;
    SELECT moved_refs INTO recorded_refs
    FROM prod_changeset_001_ff_moved_refs_receipt
    WHERE changeset_id = '001_ff_series_thread_merge';
    IF recorded_refs IS NULL THEN
        RAISE EXCEPTION 'missing merge-time moved-refs receipt; refuse rollback';
    END IF;
    FOR lock_rec IN
        SELECT id FROM threads WHERE id = 3166 ORDER BY id FOR UPDATE
    LOOP
        NULL;
    END LOOP;
    FOR lock_rec IN
        SELECT id
        FROM issues
        WHERE id BETWEEN 115395 AND 115519 OR thread_id = 3166
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT id
        FROM dependencies
        WHERE source_issue_id BETWEEN 115395 AND 115519
           OR target_issue_id BETWEEN 115395 AND 115519
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT plan_id, occurrence_id
        FROM reading_plan_issues
        WHERE issue_id BETWEEN 115395 AND 115519
        ORDER BY plan_id, occurrence_id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    FOR lock_rec IN
        SELECT id
        FROM events
        WHERE issue_id BETWEEN 115395 AND 115519
        ORDER BY id
        FOR UPDATE
    LOOP
        NULL;
    END LOOP;

    IF EXISTS (SELECT 1 FROM threads WHERE id = 18560) THEN
        RAISE EXCEPTION 'thread 18560 already exists; refuse rollback';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE id BETWEEN 115395 AND 115519) <> 125 THEN
        RAISE EXCEPTION 'expected 125 split issue ids 115395-115519';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issues
        WHERE id BETWEEN 115395 AND 115519
          AND (
              thread_id <> 3166
              OR position <> (id - 115394 + 102)
              OR status <> 'unread'
              OR read_at IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION
            'intervening write on split issues (thread/position/status/read_at); refuse unsafe restoration';
    END IF;
    IF (SELECT next_unread_issue_id FROM threads WHERE id = 3166)
       IS DISTINCT FROM (recorded_canonical->>'next_unread_issue_id')::int THEN
        RAISE EXCEPTION '3166 next_unread drifted from recorded 23029; refuse unsafe restoration';
    END IF;
    IF (
        SELECT COUNT(*) FROM issues
        WHERE thread_id = 3166 AND id NOT BETWEEN 115395 AND 115519
    ) <> 102 THEN
        RAISE EXCEPTION '3166 original issue set drifted; refuse unsafe restoration';
    END IF;
    IF EXISTS (SELECT 1 FROM thread_external_series_mappings WHERE id = 378) THEN
        RAISE EXCEPTION 'mapping 378 already exists; refuse rollback';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issues
        WHERE thread_id = 3166
          AND id BETWEEN 115395 AND 115519
          AND issue_number IN (
              SELECT issue_number FROM issues
              WHERE thread_id = 3166 AND id NOT BETWEEN 115395 AND 115519
          )
    ) THEN
        RAISE EXCEPTION 'issue_number overlap appeared after merge; refuse rollback';
    END IF;
    SELECT jsonb_build_object(
        'count', COUNT(*)::bigint,
        'ids_md5', md5(COALESCE(string_agg(id::text, ',' ORDER BY id), '')),
        'fingerprint_md5', md5(COALESCE(string_agg(
            concat_ws(
                CHR(31),
                id::text,
                source_issue_id::text,
                target_issue_id::text,
                COALESCE(note, '')
            ),
            CHR(10) ORDER BY id
        ), ''))
    )
    INTO live_deps
    FROM dependencies
    WHERE source_issue_id BETWEEN 115395 AND 115519
       OR target_issue_id BETWEEN 115395 AND 115519;

    SELECT jsonb_build_object(
        'count', COUNT(*)::bigint,
        'ids_md5', md5(COALESCE(string_agg(
            plan_id::text || ':' || occurrence_id, ',' ORDER BY plan_id, occurrence_id
        ), '')),
        'fingerprint_md5', md5(COALESCE(string_agg(
            concat_ws(
                CHR(31),
                plan_id::text,
                occurrence_id,
                issue_id::text,
                display_position::text
            ),
            CHR(10) ORDER BY plan_id, occurrence_id
        ), ''))
    )
    INTO live_plan_issues
    FROM reading_plan_issues
    WHERE issue_id BETWEEN 115395 AND 115519;

    SELECT jsonb_build_object(
        'count', COUNT(*)::bigint,
        'ids_md5', md5(COALESCE(string_agg(id::text, ',' ORDER BY id), '')),
        'fingerprint_md5', md5(COALESCE(string_agg(
            concat_ws(
                CHR(31),
                id::text,
                type,
                COALESCE(issue_id::text, ''),
                COALESCE(issue_number, '')
            ),
            CHR(10) ORDER BY id
        ), ''))
    )
    INTO live_events
    FROM events
    WHERE issue_id BETWEEN 115395 AND 115519;

    live_refs := jsonb_build_object(
        'dependencies', live_deps,
        'reading_plan_issues', live_plan_issues,
        'events', live_events
    );
    IF live_refs IS DISTINCT FROM recorded_refs THEN
        RAISE EXCEPTION
            'moved-issue references drifted from merge baseline: %',
            live_refs;
    END IF;
END $$;

INSERT INTO threads
SELECT (jsonb_populate_record(
    NULL::threads,
    $rec_split${"id":18560,"title":"Fantastic Four (1970)","format":"Comic","issues_remaining":125,"queue_position":208,"status":"active","last_rating":null,"last_activity_at":null,"created_at":"2026-08-31T11:26:07.658653+00:00","user_id":1,"notes":"Broad saved-CBL representation; ComicVine volume 2045.","is_test":false,"is_blocked":true,"total_issues":125,"next_unread_issue_id":115395,"reading_progress":"not_started","blocked_by_thread_ids":null,"blocked_by_issue_ids":null,"manual_creator_credits":[],"catalog_series_id":null}$rec_split$::jsonb
)).*;

UPDATE issues
SET
    thread_id = 18560,
    position = id - 115394
WHERE id BETWEEN 115395 AND 115519
  AND thread_id = 3166
  AND position = id - 115394 + 102
  AND status = 'unread'
  AND read_at IS NULL;

INSERT INTO thread_external_series_mappings
SELECT (jsonb_populate_record(
    NULL::thread_external_series_mappings,
    $rec_mapping${"id":378,"thread_id":18560,"external_identity_id":12970,"status":"confirmed","evidence_source":"broad_cbl_volume_representation","confidence":0.95,"created_at":"2026-08-31T11:26:07.658653+00:00","updated_at":"2026-08-31T11:26:07.658653+00:00"}$rec_mapping$::jsonb
)).*;

UPDATE threads
SET
    total_issues = (
        $rec_canonical${"id":3166,"title":"Fantastic Four (1961)","format":"Comics","reading_progress":"in_progress","next_unread_issue_id":23029,"total_issues":102,"queue_position":205,"status":"active","user_id":1}$rec_canonical$::jsonb
        ->> 'total_issues'
    )::int,
    issues_remaining = (
        SELECT COUNT(*) FROM issues WHERE thread_id = 3166 AND status <> 'read'
    ),
    next_unread_issue_id = (
        $rec_canonical${"id":3166,"title":"Fantastic Four (1961)","format":"Comics","reading_progress":"in_progress","next_unread_issue_id":23029,"total_issues":102,"queue_position":205,"status":"active","user_id":1}$rec_canonical$::jsonb
        ->> 'next_unread_issue_id'
    )::int,
    reading_progress = (
        $rec_canonical${"id":3166,"title":"Fantastic Four (1961)","format":"Comics","reading_progress":"in_progress","next_unread_issue_id":23029,"total_issues":102,"queue_position":205,"status":"active","user_id":1}$rec_canonical$::jsonb
        ->> 'reading_progress'
    )
WHERE id = 3166;

DO $$
DECLARE
    restored_split jsonb;
    restored_mapping jsonb;
    recorded_split jsonb := $rec_split${"id":18560,"title":"Fantastic Four (1970)","format":"Comic","issues_remaining":125,"queue_position":208,"status":"active","last_rating":null,"last_activity_at":null,"created_at":"2026-08-31T11:26:07.658653+00:00","user_id":1,"notes":"Broad saved-CBL representation; ComicVine volume 2045.","is_test":false,"is_blocked":true,"total_issues":125,"next_unread_issue_id":115395,"reading_progress":"not_started","blocked_by_thread_ids":null,"blocked_by_issue_ids":null,"manual_creator_credits":[],"catalog_series_id":null}$rec_split$::jsonb;
    recorded_mapping jsonb := $rec_mapping${"id":378,"thread_id":18560,"external_identity_id":12970,"status":"confirmed","evidence_source":"broad_cbl_volume_representation","confidence":0.95,"created_at":"2026-08-31T11:26:07.658653+00:00","updated_at":"2026-08-31T11:26:07.658653+00:00"}$rec_mapping$::jsonb;
BEGIN
    SELECT row_to_json(t)::jsonb INTO restored_split FROM threads t WHERE id = 18560;
    SELECT row_to_json(m)::jsonb INTO restored_mapping
    FROM thread_external_series_mappings m WHERE id = 378;

    IF restored_split IS DISTINCT FROM recorded_split THEN
        RAISE EXCEPTION
            'rollback restored thread 18560 does not match recorded row: %',
            restored_split;
    END IF;
    IF restored_mapping IS DISTINCT FROM recorded_mapping THEN
        RAISE EXCEPTION
            'rollback restored mapping 378 does not match recorded row: %',
            restored_mapping;
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 18560) <> 125 THEN
        RAISE EXCEPTION 'rollback did not restore 125 issues onto 18560';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 3166) <> 102 THEN
        RAISE EXCEPTION 'rollback did not restore 102 issues onto 3166';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issues
        WHERE thread_id = 18560 AND (id < 115395 OR id > 115519 OR position <> id - 115394)
    ) THEN
        RAISE EXCEPTION 'rollback positions drifted from id-115394';
    END IF;
    IF (SELECT next_unread_issue_id FROM threads WHERE id = 18560) <> 115395 THEN
        RAISE EXCEPTION 'rollback did not restore next unread 115395';
    END IF;
END $$;

COMMIT;
