-- =============================================================================
-- Production Smoke Test Cleanup Script
-- =============================================================================
--
-- Purpose: Safely remove all test data created by production smoke tests
-- Usage:   psql $DATABASE_URL -f scripts/cleanup_prod_smoke_tests.sql
--
-- Safety features:
--   - Preview mode shows what will be deleted
--   - Runs in a transaction (can rollback)
--   - Counts affected rows before deletion
--   - Deletes in dependency order
--
-- =============================================================================

\echo '=============================================================================='
\echo 'PRODUCTION SMOKE TEST CLEANUP'
\echo '=============================================================================='
\echo ''

-- =============================================================================
-- STEP 1: PREVIEW - Show what will be deleted
-- =============================================================================
\echo '>>> STEP 1: Preview - Counting records that will be deleted...'
\echo ''

DO $$
DECLARE
    v_user_count INT;
    v_thread_count INT;
    v_session_count INT;
    v_snapshot_count INT;
    v_event_count INT;
    v_issue_count INT;
BEGIN
    SELECT COUNT(*) INTO v_user_count FROM users WHERE is_admin = false;
    SELECT COUNT(*) INTO v_thread_count FROM threads WHERE user_id IN (SELECT id FROM users WHERE is_admin = false);
    SELECT COUNT(*) INTO v_session_count FROM sessions WHERE user_id IN (SELECT id FROM users WHERE is_admin = false);
    SELECT COUNT(*) INTO v_snapshot_count FROM snapshots WHERE session_id IN (SELECT id FROM sessions WHERE user_id IN (SELECT id FROM users WHERE is_admin = false));
    SELECT COUNT(*) INTO v_event_count FROM events WHERE session_id IN (SELECT id FROM sessions WHERE user_id IN (SELECT id FROM users WHERE is_admin = false));
    SELECT COUNT(*) INTO v_issue_count FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id IN (SELECT id FROM users WHERE is_admin = false));

    RAISE NOTICE 'Users to delete: %', v_user_count;
    RAISE NOTICE 'Threads to delete: %', v_thread_count;
    RAISE NOTICE 'Sessions to delete: %', v_session_count;
    RAISE NOTICE 'Snapshots to delete: %', v_snapshot_count;
    RAISE NOTICE 'Events to delete: %', v_event_count;
    RAISE NOTICE 'Issues to delete (cascade): %', v_issue_count;
END $$;

\echo ''
\echo '>>> Sample users (first 10):'
\echo ''

SELECT id, username, email, created_at
FROM users
WHERE is_admin = false
ORDER BY created_at DESC
LIMIT 10;

\echo ''
\echo '=============================================================================='
\echo 'PRESS Ctrl+C TO ABORT, OR WAIT 5 SECONDS TO CONTINUE...'
\echo '=============================================================================='
\echo ''

-- pg_sleep for safety pause
SELECT pg_sleep(5);

-- =============================================================================
-- STEP 2: DELETE TEST DATA
-- =============================================================================
\echo '>>> STEP 2: Deleting test data...'
\echo ''

BEGIN;

-- Delete snapshots first (before deleting their sessions)
\echo 'Deleting snapshots...'
DO $$
DECLARE
    v_snapshot_count INT;
BEGIN
    DELETE FROM snapshots
    WHERE session_id IN (
        SELECT id FROM sessions WHERE user_id IN (
            SELECT id FROM users WHERE is_admin = false
        )
    );
    GET DIAGNOSTICS v_snapshot_count = ROW_COUNT;
    RAISE NOTICE 'Deleted % snapshots', v_snapshot_count;
END $$;

-- Delete events (before deleting their sessions)
\echo 'Deleting events...'
DO $$
DECLARE
    v_event_count INT;
BEGIN
    DELETE FROM events
    WHERE session_id IN (
        SELECT id FROM sessions WHERE user_id IN (
            SELECT id FROM users WHERE is_admin = false
        )
    );
    GET DIAGNOSTICS v_event_count = ROW_COUNT;
    RAISE NOTICE 'Deleted % events', v_event_count;
END $$;

-- Delete sessions
\echo 'Deleting sessions...'
DO $$
DECLARE
    v_session_count INT;
BEGIN
    DELETE FROM sessions
    WHERE user_id IN (
        SELECT id FROM users WHERE is_admin = false
    );
    GET DIAGNOSTICS v_session_count = ROW_COUNT;
    RAISE NOTICE 'Deleted % sessions', v_session_count;
END $$;
-- Delete events tied to threads (not just sessions)
\echo 'Deleting thread-linked events...'
DO $$
DECLARE
    v_event_count INT;
BEGIN
    DELETE FROM events
    WHERE thread_id IN (
        SELECT id FROM threads WHERE user_id IN (
            SELECT id FROM users WHERE is_admin = false
        )
    );
    GET DIAGNOSTICS v_event_count = ROW_COUNT;
    RAISE NOTICE 'Deleted % thread-linked events', v_event_count;
END $$;
-- Delete threads (issues will cascade due to foreign key)
\echo 'Deleting threads...'
DO $$
DECLARE
    v_thread_count INT;
BEGIN
    DELETE FROM threads
    WHERE user_id IN (
        SELECT id FROM users WHERE is_admin = false
    );
    GET DIAGNOSTICS v_thread_count = ROW_COUNT;
    RAISE NOTICE 'Deleted % threads', v_thread_count;
END $$;

-- Delete users (revoked_tokens will cascade, collections will cascade)
\echo 'Deleting users...'
DO $$
DECLARE
    v_user_count INT;
BEGIN
    DELETE FROM users
    WHERE is_admin = false;
    GET DIAGNOSTICS v_user_count = ROW_COUNT;
    RAISE NOTICE 'Deleted % users', v_user_count;
END $$;

COMMIT;

-- =============================================================================
-- STEP 3: VERIFY DELETION
-- =============================================================================
\echo ''
\echo '>>> STEP 3: Verification - Checking for remaining records...'
\echo ''

DO $$
DECLARE
    v_remaining_users INT;
    v_remaining_threads INT;
    v_remaining_sessions INT;
    v_remaining_snapshots INT;
    v_remaining_events INT;
BEGIN
    SELECT COUNT(*) INTO v_remaining_users FROM users WHERE is_admin = false;
    SELECT COUNT(*) INTO v_remaining_threads FROM threads WHERE user_id IN (SELECT id FROM users WHERE is_admin = false);
    SELECT COUNT(*) INTO v_remaining_sessions FROM sessions WHERE user_id IN (SELECT id FROM users WHERE is_admin = false);
    SELECT COUNT(*) INTO v_remaining_snapshots FROM snapshots WHERE session_id IN (SELECT id FROM sessions WHERE user_id IN (SELECT id FROM users WHERE is_admin = false));
    SELECT COUNT(*) INTO v_remaining_events FROM events WHERE session_id IN (SELECT id FROM sessions WHERE user_id IN (SELECT id FROM users WHERE is_admin = false));

    IF v_remaining_users = 0 AND v_remaining_threads = 0 AND v_remaining_sessions = 0 AND v_remaining_snapshots = 0 AND v_remaining_events = 0 THEN
        RAISE NOTICE '✅ SUCCESS: All prod_smoke test data cleaned up successfully!';
    ELSE
        RAISE NOTICE '⚠ WARNING: Some records remain - Users: %, Threads: %, Sessions: %, Snapshots: %, Events: %',
            v_remaining_users, v_remaining_threads, v_remaining_sessions, v_remaining_snapshots, v_remaining_events;
    END IF;
END $$;

\echo ''
\echo '=============================================================================='
\echo 'CLEANUP COMPLETE'
\echo '=============================================================================='
\echo ''
