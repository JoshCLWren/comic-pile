-- Rollback for 001_ff_series_thread_merge.sql.
-- HELD. Josh approves before this runs against production. No backup tables.
-- Restore from the recorded change set / deterministic mapping:
--   split issue ids 115395-115519
--   original position = id - 115394
--   post-merge position = id - 115394 + 102
--   thread 18560 row constants recorded 2026-10-12
--   mapping 378 → identity 12970, confirmed, 0.95, broad_cbl_volume_representation
--
-- Refuses if intervening writes (reads, position changes, extra issues, or a
-- drifted 3166 frontier) would make restoration overwrite progress.

BEGIN;

DO $$
BEGIN
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
    IF (SELECT next_unread_issue_id FROM threads WHERE id = 3166) IS DISTINCT FROM 23029 THEN
        RAISE EXCEPTION '3166 next_unread drifted from 23029; refuse unsafe restoration';
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
END $$;

INSERT INTO threads (
    id,
    title,
    format,
    issues_remaining,
    queue_position,
    status,
    last_rating,
    last_activity_at,
    created_at,
    user_id,
    notes,
    is_test,
    is_blocked,
    total_issues,
    next_unread_issue_id,
    reading_progress,
    blocked_by_thread_ids,
    blocked_by_issue_ids,
    manual_creator_credits,
    catalog_series_id
) VALUES (
    18560,
    'Fantastic Four (1970)',
    'Comic',
    125,
    208,
    'active',
    NULL,
    NULL,
    TIMESTAMPTZ '2026-08-31 11:26:07.658+00',
    1,
    'Broad saved-CBL representation; ComicVine volume 2045.',
    FALSE,
    TRUE,
    125,
    NULL,
    'not_started',
    NULL,
    NULL,
    '[]'::json,
    NULL
);

UPDATE issues
SET
    thread_id = 18560,
    position = id - 115394
WHERE id BETWEEN 115395 AND 115519
  AND thread_id = 3166
  AND position = id - 115394 + 102
  AND status = 'unread'
  AND read_at IS NULL;

UPDATE threads
SET next_unread_issue_id = 115395
WHERE id = 18560
  AND next_unread_issue_id IS NULL;

INSERT INTO thread_external_series_mappings (
    id,
    thread_id,
    external_identity_id,
    status,
    evidence_source,
    confidence,
    created_at,
    updated_at
) VALUES (
    378,
    18560,
    12970,
    'confirmed',
    'broad_cbl_volume_representation',
    0.95,
    TIMESTAMPTZ '2026-08-31 11:26:07.658+00',
    TIMESTAMPTZ '2026-08-31 11:26:07.658+00'
);

UPDATE threads
SET
    total_issues = 102,
    issues_remaining = (
        SELECT COUNT(*) FROM issues WHERE thread_id = 3166 AND status <> 'read'
    ),
    next_unread_issue_id = 23029,
    reading_progress = 'in_progress'
WHERE id = 3166;

DO $$
BEGIN
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
    IF NOT EXISTS (
        SELECT 1 FROM thread_external_series_mappings
        WHERE id = 378 AND thread_id = 18560 AND external_identity_id = 12970
    ) THEN
        RAISE EXCEPTION 'rollback did not restore mapping 378';
    END IF;
END $$;

COMMIT;
