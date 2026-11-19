-- Prod-shaped migration rehearsal seed for #3554.
-- Loaded after: alembic upgrade m5d300000001 (see manifest.json)
-- Synthetic/anonymized data only. Never contains production credentials or PII.
-- Exercises edge cases: multiple users, threads with dependencies, reading plans
-- with nodes_json, CBL source-linked plan shapes, snoozed/blocked threads,
-- NULL-heavy legacy rows, and the reviewed dangling ContinuityRule allowlist
-- (#3359/#3495) so upgrade through c25530000001 must succeed and then full
-- downgrade/upgrade cycles remain valid.

BEGIN;
SET session_replication_role = 'replica';

-- Users (multiple; includes reviewed dangling-rule owner 23199 for #3359/#3495)
INSERT INTO users (id, username, created_at, email, password_hash, is_admin, password_changed_at)
VALUES
  (23199, 'rehearsal-reviewed-owner', '2025-01-10T00:00:00Z', NULL, '$2b$12$rehearsal.synthetic.hash.not.real', false, NULL),
  (23200, 'rehearsal-reader-a', '2025-02-01T00:00:00Z', 'reader-a@example.invalid', '$2b$12$rehearsal.synthetic.hash.not.real', false, NULL),
  (23201, 'rehearsal-reader-b', '2025-03-15T00:00:00Z', NULL, '$2b$12$rehearsal.synthetic.hash.not.real', false, '2026-01-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('users','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM users), 23201));

-- Threads: active, blocked, snoozed-shape (notes/status edge case), completed, NULL-heavy legacy
INSERT INTO threads (
  id, title, format, issues_remaining, queue_position, status, last_rating,
  last_activity_at, created_at, user_id, notes, is_blocked, is_test,
  total_issues, next_unread_issue_id, reading_progress, manual_creator_credits, catalog_series_id
) VALUES
  (900001, 'Rehearsal Active Thread', 'comic', 3, 1, 'active', 4.5, '2026-06-01T12:00:00Z', '2026-01-01T00:00:00Z', 23200, 'active', false, false, 3, NULL, 'in_progress', '[]'::json, NULL),
  (900002, 'Rehearsal Blocked Thread', 'comic', 2, 2, 'active', NULL, '2026-05-01T12:00:00Z', '2026-01-02T00:00:00Z', 23200, NULL, true, false, 2, NULL, 'in_progress', '[]'::json, NULL),
  (900003, 'Rehearsal Snoozed Thread', 'comic', 5, 3, 'active', NULL, NULL, '2026-01-03T00:00:00Z', 23200, 'snoozed-until-synthetic', false, false, 5, NULL, 'unstarted', '[]'::json, NULL),
  (900004, 'Rehearsal Completed Thread', 'trade', 0, 0, 'completed', 5.0, '2026-04-01T12:00:00Z', '2025-12-01T00:00:00Z', 23201, NULL, false, false, 6, NULL, 'completed', '[]'::json, NULL),
  (900005, 'Rehearsal NULL-heavy Legacy', 'comic', 1, 10, 'active', NULL, NULL, '2024-01-01T00:00:00Z', 23201, NULL, false, false, NULL, NULL, NULL, '[]'::json, NULL),
  (900006, 'Reviewed Owner Thread', 'comic', 4, 1, 'active', NULL, NULL, '2025-06-01T00:00:00Z', 23199, NULL, false, false, 4, NULL, 'unstarted', '[]'::json, NULL)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('threads','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM threads), 900006));

-- Issues for dependency/plan edges. Missing issue IDs 1117318/1117522/1117685 are
-- intentionally absent to reproduce the #3359 allowlisted dangling-rule case.
INSERT INTO issues (id, thread_id, issue_number, status, read_at, created_at, position, catalog_issue_id)
VALUES
  (910001, 900001, '1', 'read',   '2026-02-01T00:00:00Z', '2026-01-01T00:00:00Z', 1, NULL),
  (910002, 900001, '2', 'unread', NULL,                   '2026-01-01T00:00:00Z', 2, NULL),
  (910003, 900001, '3', 'unread', NULL,                   '2026-01-01T00:00:00Z', 3, NULL),
  (910004, 900002, '1', 'read',   '2026-03-01T00:00:00Z', '2026-01-02T00:00:00Z', 1, NULL),
  (910005, 900002, '2', 'unread', NULL,                   '2026-01-02T00:00:00Z', 2, NULL),
  (910006, 900004, '1', 'read',   '2026-04-01T00:00:00Z', '2025-12-01T00:00:00Z', 1, NULL),
  (910007, 900006, '1', 'unread', NULL,                   '2025-06-01T00:00:00Z', 1, NULL),
  (910008, 900006, '2', 'unread', NULL,                   '2025-06-01T00:00:00Z', 2, NULL),
  (910009, 900006, '3', 'unread', NULL,                   '2025-06-01T00:00:00Z', 3, NULL),
  (910010, 900006, '4', 'unread', NULL,                   '2025-06-01T00:00:00Z', 4, NULL)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('issues','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM issues), 910010));

UPDATE threads SET next_unread_issue_id = 910002 WHERE id = 900001;
UPDATE threads SET next_unread_issue_id = 910005 WHERE id = 900002;

-- Canonical dependency edge (issue-level) exercising blocked-thread data shape.
INSERT INTO dependencies (id, created_at, source_issue_id, target_issue_id, note)
VALUES (920001, '2026-01-02T00:00:00Z', 910004, 910005, 'rehearsal:blocker')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('dependencies','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM dependencies), 920001));

-- Continuity plans with nodes_json/lanes_json (including CBL-source-linked shape below).
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

-- CBL source/list/entry and reading-plan source linkage (CBL-adopted/source-linked shape).
INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
VALUES (940001, 'synthetic/rehearsal-cbl', '0000000000000000000000000000000000000000', '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('cbl_sources','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM cbl_sources), 940001));

INSERT INTO cbl_source_lists (id, source_id, source_path, name, declared_issue_count, content_hash, revision_sha, active, created_at, updated_at)
VALUES (940002, 940001, 'lists/rehearsal.cbl', 'Rehearsal List', 2, 'rehearsal-content-hash-0000000000000000', '0000000000000000000000000000000000000000', true, '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('cbl_source_lists','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM cbl_source_lists), 940002));

INSERT INTO cbl_source_entries (
  id, list_id, position, series_name, issue_number, volume_year, publication_year,
  external_series_identity_id, external_issue_identity_id, created_at
) VALUES
  (940003, 940002, 1, 'Rehearsal Series', '1', 2020, 2020, NULL, NULL, '2026-02-01T00:00:00Z'),
  (940004, 940002, 2, 'Rehearsal Series', '2', 2020, 2020, NULL, NULL, '2026-02-01T00:00:00Z')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('cbl_source_entries','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM cbl_source_entries), 940004));

INSERT INTO reading_plan_sources (
  id, plan_id, raw_source_path, repository, source_path, revision_sha, content_hash,
  cbl_source_list_id, custom_cbl_list_id, adopted_at, recorded_at, metadata_json
) VALUES (
  950001, 930001, 'lists/rehearsal.cbl', 'synthetic/rehearsal-cbl', 'lists/rehearsal.cbl',
  '0000000000000000000000000000000000000000', 'rehearsal-content-hash-0000000000000000',
  940002, NULL, '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z', '{"rehearsal":true}'::json
)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('reading_plan_sources','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM reading_plan_sources), 950001));

INSERT INTO reading_plan_issues (
  plan_id, occurrence_id, issue_id, lane_id, display_position, label,
  reader_role, reader_optional, is_checkpoint, source_metadata_json
) VALUES
  (930001, 'occ-910001', 910001, 'main', 1, 'Issue 1', NULL, NULL, false, '{"rehearsal":true}'::json),
  (930001, 'occ-910002', 910002, 'main', 2, 'Issue 2', NULL, NULL, false, NULL)
ON CONFLICT DO NOTHING;

-- #3359/#3495 regression case: six reviewed dangling ContinuityRules owned by
-- reviewed test user 23199. Missing issue IDs 1117318/1117522/1117685 are
-- intentionally absent. Pre-#3495 c25530000001 aborted on these rows; post-#3495
-- must skip/report them (allowlist in app/services/canonical_backfill.py).
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

-- NULL-heavy legacy reading order row (minimal valid shape)
INSERT INTO reading_orders (id, name, description, user_id)
VALUES (960001, 'Rehearsal Legacy Order', NULL, 23201)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('reading_orders','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM reading_orders), 960001));

INSERT INTO reading_order_items (id, reading_order_id, thread_id, position, issue_number)
VALUES (960002, 960001, 900005, 1, NULL)
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('reading_order_items','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM reading_order_items), 960002));

SET session_replication_role = 'origin';
COMMIT;
