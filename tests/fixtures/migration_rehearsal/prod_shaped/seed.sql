-- Prod-shaped migration rehearsal seed for #3554.
-- Loaded after: alembic upgrade m5d300000001 (see manifest.json)
-- Synthetic/anonymized data only. Never contains production credentials or PII.
-- Exercises edge cases: multiple users, dependency edges, reading plans with
-- nodes_json, CBL-linked plan/source shapes, snoozed/blocked threads,
-- NULL-heavy legacy rows, and the reviewed dangling ContinuityRule allowlist
-- (issue #3359 / fix #3495) so upgrade through c25530000001 must succeed.

BEGIN;

-- Users (multiple; includes reviewed dangling-rule owner 23199 for #3359/#3495)
INSERT INTO users (id, username, email, hashed_password, is_active, is_admin, created_at, failed_login_attempts, locked_until, password_changed_at)
VALUES
  (23199, 'rehearsal-reviewed-owner', NULL, '$2b$12$rehearsal.synthetic.hash.not.a.real.credential', true, false, '2025-01-10T00:00:00Z', 0, NULL, NULL),
  (23200, 'rehearsal-reader-a', 'reader-a@example.invalid', '$2b$12$rehearsal.synthetic.hash.not.a.real.credential', true, false, '2025-02-01T00:00:00Z', 0, NULL, NULL),
  (23201, 'rehearsal-reader-b', NULL, '$2b$12$rehearsal.synthetic.hash.not.a.real.credential', true, false, '2025-03-15T00:00:00Z', 2, NULL, '2026-01-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;

-- Ensure sequence is ahead of explicit IDs where applicable.
SELECT setval(pg_get_serial_sequence('users','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM users), 23201));

-- Threads: active, blocked, snoozed-shape (via legacy/nullable fields where present), completed, NULL-heavy legacy rows
INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, created_at, notes, is_blocked, is_test, total_issues, next_unread_issue_id, reading_progress, manual_creator_credits, catalog_series_id)
VALUES
  (900001, 23200, 'Rehearsal Active Thread', 'comic', 3, 1, 'active', 4.5, '2026-06-01T12:00:00Z', '2026-01-01T00:00:00Z', 'active', false, false, 3, NULL, 'in_progress', '[]'::json, NULL),
  (900002, 23200, 'Rehearsal Blocked Thread', 'comic', 2, 2, 'active', NULL, '2026-05-01T12:00:00Z', '2026-01-02T00:00:00Z', NULL, true, false, 2, NULL, 'in_progress', '[]'::json, NULL),
  (900003, 23200, 'Rehearsal Snoozed Thread', 'comic', 5, 3, 'active', NULL, NULL, '2026-01-03T00:00:00Z', 'snoozed edge case', false, false, 5, NULL, 'unstarted', '[]'::json, NULL),
  (900004, 23201, 'Rehearsal Completed Thread', 'trade', 0, 0, 'completed', 5.0, '2026-04-01T12:00:00Z', '2025-12-01T00:00:00Z', NULL, false, false, 6, NULL, 'completed', '[]'::json, NULL),
  (900005, 23201, 'Rehearsal NULL-heavy Legacy', 'comic', 1, 10, 'active', NULL, NULL, '2024-01-01T00:00:00Z', NULL, false, false, NULL, NULL, NULL, '[]'::json, NULL),
  (900006, 23199, 'Reviewed Owner Thread', 'comic', 4, 1, 'active', NULL, NULL, '2025-06-01T00:00:00Z', NULL, false, false, 4, NULL, 'unstarted', '[]'::json, NULL)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('threads','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM threads), 900006));

-- Issues for dependency/plan edges (all present; dangling continuity rules below
-- intentionally reference missing issue IDs to reproduce #3359 allowlist case)
INSERT INTO issues (id, thread_id, issue_number, title, read, position, status, created_at, is_manual, display_order, last_read_at, read_at, rating)
VALUES
  (910001, 900001, '1', 'Issue One', true, 1, 'read', '2026-01-01T00:00:00Z', false, 1, '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z', 4.0),
  (910002, 900001, '2', 'Issue Two', false, 2, 'unread', '2026-01-01T00:00:00Z', false, 2, NULL, NULL, NULL),
  (910003, 900001, '3', 'Issue Three', false, 3, 'unread', '2026-01-01T00:00:00Z', false, 3, NULL, NULL, NULL),
  (910004, 900002, '1', 'Blocked Source', true, 1, 'read', '2026-01-02T00:00:00Z', false, 1, NULL, NULL, NULL),
  (910005, 900002, '2', 'Blocked Target', false, 2, 'unread', '2026-01-02T00:00:00Z', false, 2, NULL, NULL, NULL),
  (910006, 900004, '1', NULL, true, 1, 'read', '2025-12-01T00:00:00Z', false, 1, NULL, NULL, NULL),
  (910007, 900006, '1', 'Surviving Source', false, 1, 'unread', '2025-06-01T00:00:00Z', false, 1, NULL, NULL, NULL),
  (910008, 900006, '2', 'Surviving Target', false, 2, 'unread', '2025-06-01T00:00:00Z', false, 2, NULL, NULL, NULL),
  (910009, 900006, '3', 'Surviving Target 2', false, 3, 'unread', '2025-06-01T00:00:00Z', false, 3, NULL, NULL, NULL),
  (910010, 900006, '4', 'Surviving Target 3', false, 4, 'unread', '2025-06-01T00:00:00Z', false, 4, NULL, NULL, NULL)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('issues','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM issues), 910010));

UPDATE threads SET next_unread_issue_id = 910002 WHERE id = 900001;
UPDATE threads SET next_unread_issue_id = 910005 WHERE id = 900002;

-- Canonical dependency edge (issue-level) for blocked/snoozed-shape scenarios
INSERT INTO dependencies (id, source_issue_id, target_issue_id, note, created_at)
VALUES
  (920001, 910004, 910005, 'rehearsal:blocker', '2026-01-02T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('dependencies','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM dependencies), 920001));

-- Continuity plan with nodes_json/lanes_json and CBL-source-linked shape
INSERT INTO continuity_plans (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
VALUES
  (930001, 23200, 'Rehearsal Plan', 'informational',
   '[{"id":"n1","type":"issue","issue_id":910001},{"id":"n2","type":"issue","issue_id":910002}]'::json,
   '[{"id":"main","name":"Main","order":0}]'::json,
   '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z'),
  (930002, 23199, 'Reviewed Owner Plan', 'informational',
   '[{"id":"p1","type":"issue","issue_id":910007}]'::json,
   '[{"id":"main","name":"Main","order":0}]'::json,
   '2025-07-01T00:00:00Z', '2025-07-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('continuity_plans','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM continuity_plans), 930002));

-- CBL source/list linkage shape (present at this revision) for adopted-plan context
INSERT INTO cbl_sources (id, name, source_type, location, created_at, updated_at)
VALUES (940001, 'Rehearsal CBL Source', 'file', 'synthetic://rehearsal', '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
INSERT INTO cbl_source_lists (id, source_id, name, slug, created_at, updated_at)
VALUES (940002, 940001, 'Rehearsal List', 'rehearsal-list', '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
INSERT INTO cbl_source_entries (id, source_list_id, position, payload_json, created_at, updated_at)
VALUES (940003, 940002, 1, '{"series":"Rehearsal","issue":"1"}'::json, '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;

-- Reading plan source placement / membership shapes where applicable
INSERT INTO reading_plan_sources (id, plan_id, source_kind, source_ref, created_at, updated_at)
VALUES (950001, 930001, 'cbl_source_list', '940002', '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
INSERT INTO reading_plan_issues (id, plan_id, issue_id, position, created_at, updated_at)
VALUES (950002, 930001, 910001, 1, '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;

-- #3359/#3495 regression case: six reviewed dangling ContinuityRules owned by
-- test user 23199 (REVIEWED_DANGLING_OWNER_USER_ID). Source/target issue IDs
-- 1117318,1117522,1117685 are intentionally absent. Pre-#3495 c25530000001
-- aborted on these rows during deploy; post-#3495 must skip/report them and
-- continue. The allowlist and expected shapes live in
-- app/services/canonical_backfill.py and alembic revision c25530000001.
INSERT INTO continuity_rules (
  id, user_id, source_type, source_id, target_type, target_id,
  satisfaction_type, checkpoint_issue_id, note, created_at, updated_at,
  legacy_dependency_id, convergence_targets
) VALUES
  (1715192, 23199, 'issue', 1117318, 'issue', 910008, 'item_read', NULL, 'continuity-plan:930002', '2025-07-10T00:00:00Z', '2025-07-10T00:00:00Z', NULL, NULL),
  (1715241, 23199, 'issue', 910007, 'issue', 1117522, 'item_read', NULL, 'continuity-plan:930002', '2025-07-10T00:00:00Z', '2025-07-10T00:00:00Z', NULL, NULL),
  (1715291, 23199, 'issue', 1117685, 'issue', 910009, 'item_read', NULL, 'continuity-plan:930002', '2025-07-10T00:00:00Z', '2025-07-10T00:00:00Z', NULL, NULL),
  (1715333, 23199, 'issue', 910007, 'issue', 1117685, 'item_read', NULL, 'continuity-plan:930002', '2025-07-10T00:00:00Z', '2025-07-10T00:00:00Z', NULL, NULL),
  (1715578, 23199, 'issue', 1117318, 'issue', 1117522, 'item_read', NULL, 'continuity-plan:930002', '2025-07-10T00:00:00Z', '2025-07-10T00:00:00Z', NULL, NULL),
  (1715620, 23199, 'issue', 1117522, 'issue', 1117685, 'item_read', NULL, 'continuity-plan:930002', '2025-07-10T00:00:00Z', '2025-07-10T00:00:00Z', NULL, NULL)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('continuity_rules','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM continuity_rules), 1715620));

-- NULL-heavy legacy row shapes in related tables where nullable
INSERT INTO reading_order_items (id, reading_order_id, thread_id, position, created_at)
SELECT 960001, ro.id, 900005, 1, '2024-01-01T00:00:00Z'
FROM reading_orders ro
LIMIT 0; -- keep valid if table/order rows absent in this fixture revision; no-op safe

COMMIT;
