-- Fantastic Four series-thread reattach (user 1).
-- NOT APPLIED. Josh approves before this runs against production.
--
-- Proven by source data (Neon 2026-10-12, SET-equivalent single SELECTs):
--   threads 3166 and 18560 both map to ComicVine series 2045
--   3166 holds #1-102 (positions 1-102); 18560 holds #103-231 (positions 1-125)
--   issue_number overlap = 0
-- Issue rows are UPDATEd, never deleted or recreated. Ids, status, read_at stay.
-- Annuals / Giant-Size threads 18545, 18565, 18666 are not in this script.
--
-- Before:
--   3166 Fantastic Four (1961): 102 issues, 19 read / 83 unread, next 23029 = #16
--        issues_remaining column is stale 87 (actual unread 83)
--   18560 Fantastic Four (1970): 125 unread, next 115395 = #103
-- After:
--   3166 owns 227 issues, positions 1-227, next unread stays 23029 = #16
--   issues_remaining = 208 (83+125); do not add 125 to stale 87
--   18560 deleted (zero issues)
--   mapping 378 dropped (same ComicVine series 2045 as mapping 67)
--
-- Backup tables created in this transaction are the rollback source.
-- See 001_ff_series_thread_merge_rollback.sql.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.prod_changeset_001_ff_issue_backup') IS NOT NULL THEN
        RAISE EXCEPTION 'changeset 001 backup tables already exist; refuse double-apply';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM threads
        WHERE id = 3166 AND user_id = 1 AND title = 'Fantastic Four (1961)'
    ) THEN
        RAISE EXCEPTION 'canonical thread 3166 title/owner guard failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM threads
        WHERE id = 18560 AND user_id = 1 AND title = 'Fantastic Four (1970)'
    ) THEN
        RAISE EXCEPTION 'split thread 18560 title/owner guard failed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM issues a
        JOIN issues b ON a.issue_number = b.issue_number
        WHERE a.thread_id = 3166 AND b.thread_id = 18560
    ) THEN
        RAISE EXCEPTION 'issue_number overlap between 3166 and 18560';
    END IF;
END $$;

CREATE TABLE prod_changeset_001_ff_issue_backup AS
SELECT id AS issue_id, thread_id, position
FROM issues
WHERE thread_id = 18560;

ALTER TABLE prod_changeset_001_ff_issue_backup
    ADD PRIMARY KEY (issue_id);

CREATE TABLE prod_changeset_001_ff_thread_backup AS
SELECT *
FROM threads
WHERE id = 18560;

CREATE TABLE prod_changeset_001_ff_mapping_backup AS
SELECT *
FROM thread_external_series_mappings
WHERE id = 378
  AND thread_id = 18560
  AND external_identity_id = 12970;

CREATE TABLE prod_changeset_001_ff_canonical_backup AS
SELECT
    id,
    total_issues,
    issues_remaining,
    next_unread_issue_id,
    reading_progress
FROM threads
WHERE id = 3166;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM prod_changeset_001_ff_issue_backup) <> 125 THEN
        RAISE EXCEPTION 'expected 125 split issues to back up';
    END IF;
    IF (SELECT COUNT(*) FROM prod_changeset_001_ff_thread_backup) <> 1 THEN
        RAISE EXCEPTION 'expected one split thread row to back up';
    END IF;
    IF (SELECT COUNT(*) FROM prod_changeset_001_ff_mapping_backup) <> 1 THEN
        RAISE EXCEPTION 'expected mapping 378 to back up';
    END IF;
END $$;

UPDATE threads SET next_unread_issue_id = NULL WHERE id = 18560;

UPDATE issues
SET
    thread_id = 3166,
    position = position + 102
WHERE thread_id = 18560;

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
    IF EXISTS (SELECT 1 FROM threads WHERE id = 18560) THEN
        RAISE EXCEPTION 'split thread 18560 still exists';
    END IF;
    IF (SELECT next_unread_issue_id FROM threads WHERE id = 3166) <> 23029 THEN
        RAISE EXCEPTION 'next unread must remain issue 23029 (#16)';
    END IF;
    IF (SELECT issues_remaining FROM threads WHERE id = 3166) <> 208 THEN
        RAISE EXCEPTION 'issues_remaining must be 208 (83+125), not stale 87+125';
    END IF;
END $$;

COMMIT;
