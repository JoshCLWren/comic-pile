-- Diagnostic query for Josh_Digital_Comics
-- Covers: Absolute threads, Absolute Evil deps, Dark Knights: Death Metal, eligible roll pool
\timing off
\pset format aligned
\pset border 2

-- ============================================================
-- 1. USER
-- ============================================================
\echo '=== USER ==='
SELECT id, username, email FROM users WHERE username = 'Josh_Digital_Comics';

-- ============================================================
-- 2. ALL ACTIVE THREADS (eligible roll pool overview)
-- ============================================================
\echo ''
\echo '=== ALL ACTIVE THREADS (queue order) ==='
SELECT
    t.id,
    t.title,
    t.status,
    t.is_blocked,
    t.issues_remaining,
    t.total_issues,
    t.next_unread_issue_id,
    t.queue_position
FROM threads t
JOIN users u ON u.id = t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND t.status = 'active'
ORDER BY t.queue_position;

-- ============================================================
-- 3. ABSOLUTE-RELATED THREADS (all statuses)
-- ============================================================
\echo ''
\echo '=== ABSOLUTE-RELATED THREADS ==='
SELECT
    t.id,
    t.title,
    t.status,
    t.is_blocked,
    t.issues_remaining,
    t.total_issues,
    t.next_unread_issue_id,
    t.queue_position
FROM threads t
JOIN users u ON u.id = t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND (t.title ILIKE '%absolute%' OR t.title ILIKE '%absolute evil%')
ORDER BY t.title;

-- ============================================================
-- 4. DARK KNIGHTS: DEATH METAL THREAD + ISSUES
-- ============================================================
\echo ''
\echo '=== DARK KNIGHTS: DEATH METAL THREAD ==='
SELECT
    t.id,
    t.title,
    t.status,
    t.is_blocked,
    t.issues_remaining,
    t.total_issues,
    t.next_unread_issue_id,
    t.queue_position
FROM threads t
JOIN users u ON u.id = t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND t.title ILIKE '%death metal%';

\echo ''
\echo '=== DARK KNIGHTS: DEATH METAL ISSUES ==='
SELECT
    i.id,
    i.issue_number,
    i.position,
    i.status,
    i.read_at
FROM issues i
JOIN threads t ON t.id = i.thread_id
JOIN users u ON u.id = t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND t.title ILIKE '%death metal%'
ORDER BY i.position;

-- ============================================================
-- 5. ABSOLUTE BATMAN ISSUES (all, showing annual/special)
-- ============================================================
\echo ''
\echo '=== ABSOLUTE BATMAN ISSUES ==='
SELECT
    i.id,
    i.issue_number,
    i.position,
    i.status,
    i.read_at
FROM issues i
JOIN threads t ON t.id = i.thread_id
JOIN users u ON u.id = t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND t.title = 'Absolute Batman'
ORDER BY i.position;

-- ============================================================
-- 6. ABSOLUTE EVIL THREAD + ISSUES
-- ============================================================
\echo ''
\echo '=== ABSOLUTE EVIL THREAD + ISSUES ==='
SELECT
    t.id AS thread_id,
    t.title,
    t.status,
    t.is_blocked,
    t.issues_remaining,
    t.total_issues,
    t.next_unread_issue_id,
    i.id AS issue_id,
    i.issue_number,
    i.position,
    i.status AS issue_status
FROM threads t
JOIN users u ON u.id = t.user_id
LEFT JOIN issues i ON i.thread_id = t.id
WHERE u.username = 'Josh_Digital_Comics'
  AND t.title ILIKE '%absolute evil%'
ORDER BY i.position;

-- ============================================================
-- 7. ALL DEPENDENCIES FOR JOSH (with full labels)
-- ============================================================
\echo ''
\echo '=== ALL DEPENDENCIES (issue-level) ==='
SELECT
    d.id AS dep_id,
    src_t.title  AS source_thread,
    src_i.issue_number AS source_issue,
    src_i.status AS source_issue_status,
    tgt_t.title  AS target_thread,
    tgt_i.issue_number AS target_issue,
    tgt_i.status AS target_issue_status
FROM dependencies d
JOIN issues src_i ON src_i.id = d.source_issue_id
JOIN threads src_t ON src_t.id = src_i.thread_id
JOIN issues tgt_i ON tgt_i.id = d.target_issue_id
JOIN threads tgt_t ON tgt_t.id = tgt_i.thread_id
JOIN users u ON u.id = src_t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND d.source_thread_id IS NULL
ORDER BY src_t.title, src_i.position, tgt_t.title, tgt_i.position;

\echo ''
\echo '=== ALL DEPENDENCIES (thread-level) ==='
SELECT
    d.id AS dep_id,
    src_t.title AS source_thread,
    src_t.status AS source_thread_status,
    tgt_t.title AS target_thread,
    tgt_t.status AS target_thread_status
FROM dependencies d
JOIN threads src_t ON src_t.id = d.source_thread_id
JOIN threads tgt_t ON tgt_t.id = d.target_thread_id
JOIN users u ON u.id = src_t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND d.source_issue_id IS NULL
ORDER BY src_t.title;

-- ============================================================
-- 8. WHY IS EACH ABSOLUTE THREAD BLOCKED? (active, blocked)
-- ============================================================
\echo ''
\echo '=== ACTIVE BLOCKED THREADS: blocking reasons ==='
SELECT
    tgt_t.title AS blocked_thread,
    -- Issue-level blocks
    src_t.title AS blocking_thread,
    src_i.issue_number AS blocking_issue,
    src_i.status AS blocking_issue_status,
    'issue-level' AS dep_type
FROM dependencies d
JOIN issues src_i ON src_i.id = d.source_issue_id
JOIN threads src_t ON src_t.id = src_i.thread_id
JOIN issues tgt_i ON tgt_i.id = d.target_issue_id
JOIN threads tgt_t ON tgt_t.id = tgt_i.thread_id
JOIN users u ON u.id = tgt_t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND tgt_t.status = 'active'
  AND src_i.status != 'read'

UNION ALL

SELECT
    tgt_t.title AS blocked_thread,
    src_t.title AS blocking_thread,
    NULL AS blocking_issue,
    src_t.status AS blocking_issue_status,
    'thread-level' AS dep_type
FROM dependencies d
JOIN threads src_t ON src_t.id = d.source_thread_id
JOIN threads tgt_t ON tgt_t.id = d.target_thread_id
JOIN users u ON u.id = tgt_t.user_id
WHERE u.username = 'Josh_Digital_Comics'
  AND tgt_t.status = 'active'
  AND src_t.status != 'completed'

ORDER BY blocked_thread, dep_type, blocking_thread;

\echo 'Done.'
