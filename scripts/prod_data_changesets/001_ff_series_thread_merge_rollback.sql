-- Rollback for 001_ff_series_thread_merge.sql.
-- Requires the backup tables created by a successful 001 apply.
-- NOT APPLIED. Josh approves before this runs against production.
--
-- Restores issue ids onto thread 18560 with original positions, mapping 378,
-- and 3166 totals. Issue rows are never deleted or recreated.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.prod_changeset_001_ff_issue_backup') IS NULL
        OR to_regclass('public.prod_changeset_001_ff_thread_backup') IS NULL
        OR to_regclass('public.prod_changeset_001_ff_mapping_backup') IS NULL
        OR to_regclass('public.prod_changeset_001_ff_canonical_backup') IS NULL
    THEN
        RAISE EXCEPTION 'changeset 001 backup tables missing; cannot roll back';
    END IF;
    IF EXISTS (SELECT 1 FROM threads WHERE id = 18560) THEN
        RAISE EXCEPTION 'thread 18560 already exists; refuse rollback';
    END IF;
END $$;

INSERT INTO threads
SELECT *
FROM prod_changeset_001_ff_thread_backup;

UPDATE threads
SET next_unread_issue_id = NULL
WHERE id = 18560;

UPDATE issues AS i
SET
    thread_id = b.thread_id,
    position = b.position
FROM prod_changeset_001_ff_issue_backup AS b
WHERE i.id = b.issue_id;

UPDATE threads AS t
SET next_unread_issue_id = b.next_unread_issue_id
FROM prod_changeset_001_ff_thread_backup AS b
WHERE t.id = 18560
  AND t.id = b.id;

INSERT INTO thread_external_series_mappings
SELECT *
FROM prod_changeset_001_ff_mapping_backup;

UPDATE threads AS t
SET
    total_issues = b.total_issues,
    issues_remaining = b.issues_remaining,
    next_unread_issue_id = b.next_unread_issue_id,
    reading_progress = b.reading_progress
FROM prod_changeset_001_ff_canonical_backup AS b
WHERE t.id = 3166
  AND t.id = b.id;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 18560) <> 125 THEN
        RAISE EXCEPTION 'rollback did not restore 125 issues onto 18560';
    END IF;
    IF (SELECT COUNT(*) FROM issues WHERE thread_id = 3166) <> 102 THEN
        RAISE EXCEPTION 'rollback did not restore 102 issues onto 3166';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM thread_external_series_mappings WHERE id = 378
    ) THEN
        RAISE EXCEPTION 'rollback did not restore mapping 378';
    END IF;
END $$;

DROP TABLE prod_changeset_001_ff_issue_backup;
DROP TABLE prod_changeset_001_ff_thread_backup;
DROP TABLE prod_changeset_001_ff_mapping_backup;
DROP TABLE prod_changeset_001_ff_canonical_backup;

COMMIT;
