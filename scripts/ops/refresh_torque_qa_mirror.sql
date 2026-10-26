-- Authorized Torque QA-only reading mirror from user ID 1.
-- 2026-10-26: Owner authorized replacement. Preserve users/auth and source user rows.
-- This is a single atomic transaction, and must not be run statement-by-statement.
-- Historic QA sessions/events/snapshots are intentionally cleared, not copied, so
-- interactive tests start with a clean QA session. Muse remains disabled.
-- Clone IDs use a fixed +10000000 offset, allowing deterministic source-to-QA test mappings.
-- NEXT_STATEMENT
LOCK TABLE threads, issues, dependencies, custom_cbl_lists, custom_cbl_entries, custom_cbl_overlap_decisions, custom_cbl_source_links, continuity_plans, continuity_rules, reading_plan_issues, reading_plan_sources, reading_plan_source_placements, reading_plan_release_sources, reading_plan_dependencies, events, sessions, snapshots, thread_external_series_mappings, issue_external_identity_mappings, dependency_groups, dependency_group_memberships, collection_exclusions, reading_orders, reading_order_items, tags, tag_assignments, cbl_adoption_receipts IN SHARE ROW EXCLUSIVE MODE-- NEXT_STATEMENT
SELECT pg_advisory_xact_lock(23199)
-- NEXT_STATEMENT
DO $guard$ BEGIN
 IF (SELECT username FROM users WHERE id=1) IS DISTINCT FROM 'Josh' OR (SELECT username FROM users WHERE id=23199) IS DISTINCT FROM 'torque' THEN RAISE EXCEPTION 'unexpected source/target accounts'; END IF;
 IF (SELECT count(*) FROM threads WHERE user_id=1) < 800 THEN RAISE EXCEPTION 'source library incomplete'; END IF;
 IF EXISTS (SELECT 1 FROM dependencies d JOIN issues a ON a.id=d.source_issue_id JOIN threads ta ON ta.id=a.thread_id JOIN issues b ON b.id=d.target_issue_id JOIN threads tb ON tb.id=b.thread_id WHERE (ta.user_id=23199 AND tb.user_id<>23199) OR (tb.user_id=23199 AND ta.user_id<>23199)) THEN RAISE EXCEPTION 'QA dependency crosses reader accounts'; END IF;
 IF EXISTS(SELECT 1 FROM events e JOIN sessions se ON se.id=e.session_id WHERE se.user_id<>23199 AND (e.thread_id IN (SELECT id FROM threads WHERE user_id=23199) OR e.selected_thread_id IN (SELECT id FROM threads WHERE user_id=23199) OR e.issue_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199))) THEN RAISE EXCEPTION 'foreign session references QA library'; END IF;
 IF EXISTS(SELECT 1 FROM tag_assignments a JOIN tags owner_tag ON owner_tag.id=a.tag_id WHERE owner_tag.owner_user_id IS DISTINCT FROM 23199 AND ((a.target_type IN ('thread','series') AND a.target_id IN (SELECT id FROM threads WHERE user_id=23199)) OR (a.target_type='issue' AND a.target_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199)))) THEN RAISE EXCEPTION 'other reader owns tag assignment to QA records'; END IF;
 END $guard$
-- NEXT_STATEMENT
DELETE FROM snapshots WHERE session_id IN (SELECT id FROM sessions WHERE user_id=23199)
-- NEXT_STATEMENT
DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE user_id=23199) OR thread_id IN (SELECT id FROM threads WHERE user_id=23199) OR selected_thread_id IN (SELECT id FROM threads WHERE user_id=23199) OR issue_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199)
-- NEXT_STATEMENT
DELETE FROM sessions WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM catalog_commit_receipts WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM taste_signals WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM reading_order_items WHERE reading_order_id IN (SELECT id FROM reading_orders WHERE user_id=23199)
-- NEXT_STATEMENT
DELETE FROM reading_orders WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM continuity_rules WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM continuity_plans WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM dependency_groups WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM custom_cbl_source_links WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM custom_cbl_overlap_decisions WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM custom_cbl_lists WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM collection_exclusions WHERE user_id=23199
-- NEXT_STATEMENT
DELETE FROM tag_assignments WHERE tag_id IN (SELECT id FROM tags WHERE owner_user_id=23199) OR (target_type IN ('thread','series') AND target_id IN (SELECT id FROM threads WHERE user_id=23199)) OR (target_type='issue' AND target_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199))
-- NEXT_STATEMENT
DELETE FROM tags WHERE owner_user_id=23199
-- NEXT_STATEMENT
DELETE FROM dependencies WHERE source_issue_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199) OR target_issue_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199)
-- NEXT_STATEMENT
DELETE FROM threads WHERE user_id=23199
-- NEXT_STATEMENT
DO $coll$ DECLARE tab text; occupied bigint; BEGIN
 FOREACH tab IN ARRAY ARRAY['threads','issues','dependencies','custom_cbl_lists','custom_cbl_entries','continuity_plans','continuity_rules','continuity_rule_selected_members','reading_plan_sources','reading_plan_release_sources','collection_exclusions','thread_external_series_mappings','issue_external_identity_mappings','dependency_groups','dependency_group_memberships','reading_orders','reading_order_items','tags','tag_assignments','custom_cbl_source_links','custom_cbl_overlap_decisions','cbl_adoption_receipts'] LOOP
 EXECUTE format('SELECT count(*) FROM %I WHERE id >= 10000000',tab) INTO occupied;
 IF occupied > 0 THEN RAISE EXCEPTION 'fixed QA offset overlaps existing IDs in %',tab; END IF;
 END LOOP; END $coll$
-- NEXT_STATEMENT
CREATE FUNCTION pg_temp.qa_rewrite_json(doc jsonb) RETURNS jsonb LANGUAGE plpgsql AS $rewrite$
DECLARE k text; v jsonb; outval jsonb; child jsonb; old_id bigint; raw text;
BEGIN
 IF doc IS NULL THEN RETURN NULL; END IF;
 IF jsonb_typeof(doc)='array' THEN
  outval='[]'::jsonb;
  FOR child IN SELECT value FROM jsonb_array_elements(doc) LOOP outval=outval||jsonb_build_array(pg_temp.qa_rewrite_json(child)); END LOOP;
  RETURN outval;
 ELSIF jsonb_typeof(doc)='object' THEN
  outval='{}'::jsonb;
  FOR k,v IN SELECT key,value FROM jsonb_each(doc) LOOP
   IF jsonb_typeof(v)='number' AND (k IN ('issue_id','checkpoint_issue_id','source_issue_id','target_issue_id','checkpoint_target_ref_id') OR (k='ref_id' AND doc->>'node_type' IN ('issue','crossover')) OR (k='id' AND doc->>'type' IN ('issue','crossover'))) THEN
    old_id=(v#>>'{}')::bigint;
    IF EXISTS(SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=old_id AND t.user_id=1) THEN v=to_jsonb(old_id+10000000); END IF;
   ELSIF jsonb_typeof(v)='number' AND (k IN ('thread_id','pending_thread_id') OR (k='ref_id' AND doc->>'node_type' IN ('thread','series'))) THEN
    old_id=(v#>>'{}')::bigint;
    IF EXISTS(SELECT 1 FROM threads WHERE id=old_id AND user_id=1) THEN v=to_jsonb(old_id+10000000); END IF;
   ELSIF jsonb_typeof(v)='number' AND k='custom_cbl_list_id' THEN
    old_id=(v#>>'{}')::bigint;
    IF EXISTS(SELECT 1 FROM custom_cbl_lists WHERE id=old_id AND user_id=1) THEN v=to_jsonb(old_id+10000000); END IF;
   ELSIF k='id' AND jsonb_typeof(v)='string' AND doc->>'type' IN ('issue','crossover') AND (v#>>'{}')~'^[0-9]+$' THEN
    old_id=(v#>>'{}')::bigint;
    IF EXISTS(SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=old_id AND t.user_id=1) THEN v=to_jsonb((old_id+10000000)::text); END IF;
   ELSIF k IN ('checkpoint_target_ref_ids','checkpoint_target_issue_ids') AND jsonb_typeof(v)='array' THEN
    v=(SELECT coalesce(jsonb_agg(
       CASE WHEN jsonb_typeof(x.value)='number'
         AND EXISTS(SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=(x.value#>>'{}')::bigint AND t.user_id=1)
         THEN to_jsonb((x.value#>>'{}')::bigint+10000000) ELSE x.value END
       ORDER BY x.ordinality),'[]'::jsonb)
       FROM jsonb_array_elements(v) WITH ORDINALITY AS x(value,ordinality));
   ELSE v=pg_temp.qa_rewrite_json(v); END IF;
   outval=outval||jsonb_build_object(k,v);
  END LOOP;
  RETURN outval;
 ELSIF jsonb_typeof(doc)='string' THEN
  raw=doc#>>'{}';
  IF raw~'^custom-cbl:[0-9]+$' THEN
   old_id=substring(raw from 12)::bigint;
   IF EXISTS(SELECT 1 FROM custom_cbl_lists WHERE id=old_id AND user_id=1) THEN RETURN to_jsonb('custom-cbl:'||(old_id+10000000)::text); END IF;
  END IF;
 END IF;
 RETURN doc;
END $rewrite$
-- NEXT_STATEMENT
INSERT INTO threads (id,title,format,issues_remaining,queue_position,status,last_rating,last_activity_at,created_at,user_id,notes,is_test,is_blocked,total_issues,next_unread_issue_id,reading_progress,manual_creator_credits,catalog_series_id,queue_order_key,queue_position_is_manual) SELECT id+10000000,title,format,issues_remaining,queue_position,status,last_rating,last_activity_at,created_at,23199,notes,is_test,is_blocked,total_issues,NULL,reading_progress,manual_creator_credits,catalog_series_id,queue_order_key,queue_position_is_manual FROM threads WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO issues (id,thread_id,issue_number,status,read_at,created_at,position,catalog_issue_id) SELECT i.id+10000000,i.thread_id+10000000,i.issue_number,i.status,i.read_at,i.created_at,i.position,i.catalog_issue_id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=1
-- NEXT_STATEMENT
UPDATE threads q SET next_unread_issue_id=s.next_unread_issue_id+10000000 FROM threads s WHERE s.user_id=1 AND q.id=s.id+10000000 AND s.next_unread_issue_id IS NOT NULL
-- NEXT_STATEMENT
INSERT INTO dependencies (id,source_issue_id,target_issue_id,created_at,note,origin,classification,provenance) SELECT d.id+10000000,d.source_issue_id+10000000,d.target_issue_id+10000000,d.created_at,d.note,d.origin,d.classification,d.provenance FROM dependencies d JOIN issues i ON i.id=d.source_issue_id JOIN threads t ON t.id=i.thread_id JOIN issues j ON j.id=d.target_issue_id JOIN threads z ON z.id=j.thread_id WHERE t.user_id=1 AND z.user_id=1
-- NEXT_STATEMENT
INSERT INTO thread_external_series_mappings (id,thread_id,external_identity_id,status,evidence_source,confidence,created_at,updated_at) SELECT m.id+10000000,m.thread_id+10000000,m.external_identity_id,m.status,m.evidence_source,m.confidence,m.created_at,m.updated_at FROM thread_external_series_mappings m JOIN threads t ON t.id=m.thread_id WHERE t.user_id=1
-- NEXT_STATEMENT
INSERT INTO issue_external_identity_mappings (id,issue_id,external_identity_id,status,evidence_source,confidence,created_at,updated_at,rejection_reason,evidence_json) SELECT m.id+10000000,m.issue_id+10000000,m.external_identity_id,m.status,m.evidence_source,m.confidence,m.created_at,m.updated_at,m.rejection_reason,m.evidence_json FROM issue_external_identity_mappings m JOIN issues i ON i.id=m.issue_id JOIN threads t ON t.id=i.thread_id WHERE t.user_id=1
-- NEXT_STATEMENT
INSERT INTO custom_cbl_lists (id,user_id,name,description,created_at,updated_at,mode,overlap_decisions_updated_at) SELECT id+10000000,23199,name,description,created_at,updated_at,mode,overlap_decisions_updated_at FROM custom_cbl_lists WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO custom_cbl_entries (id,list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) SELECT e.id+10000000,e.list_id+10000000,e.issue_id+10000000,e.position,e.created_at,e.is_checkpoint,(SELECT coalesce(json_agg((x.value)::bigint+10000000 ORDER BY x.ordinality),'[]'::json) FROM json_array_elements_text(e.checkpoint_target_issue_ids::json) WITH ORDINALITY AS x(value,ordinality)),e.gate,e.skipped FROM custom_cbl_entries e JOIN custom_cbl_lists l ON l.id=e.list_id WHERE l.user_id=1
-- NEXT_STATEMENT
INSERT INTO custom_cbl_overlap_decisions (id,user_id,list_id,continuing_external_identity_id,waiting_external_identity_id,created_at,updated_at) SELECT id+10000000,23199,list_id+10000000,continuing_external_identity_id,waiting_external_identity_id,created_at,updated_at FROM custom_cbl_overlap_decisions WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO custom_cbl_source_links (id,user_id,cbl_source_list_id,custom_cbl_list_id,source_revision_sha,source_content_hash,created_at,updated_at) SELECT id+10000000,23199,cbl_source_list_id,custom_cbl_list_id+10000000,source_revision_sha,source_content_hash,created_at,updated_at FROM custom_cbl_source_links WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO collection_exclusions (id,user_id,provider,external_volume_id,thread_id,issue_id,created_at) SELECT id+10000000,23199,provider,external_volume_id,CASE WHEN thread_id IS NULL THEN NULL ELSE thread_id+10000000 END,CASE WHEN issue_id IS NULL THEN NULL ELSE issue_id+10000000 END,created_at FROM collection_exclusions WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO dependency_groups (id,user_id,name,created_at) SELECT id+10000000,23199,name,created_at FROM dependency_groups WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO dependency_group_memberships (id,group_id,thread_id,issue_id,sequence_order) SELECT m.id+10000000,m.group_id+10000000,CASE WHEN m.thread_id IS NULL THEN NULL ELSE m.thread_id+10000000 END,CASE WHEN m.issue_id IS NULL THEN NULL ELSE m.issue_id+10000000 END,m.sequence_order FROM dependency_group_memberships m JOIN dependency_groups g ON g.id=m.group_id WHERE g.user_id=1
-- NEXT_STATEMENT
INSERT INTO reading_orders (id,name,description,user_id) SELECT id+10000000,name,description,23199 FROM reading_orders WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO reading_order_items (id,reading_order_id,thread_id,position,issue_number) SELECT i.id+10000000,i.reading_order_id+10000000,i.thread_id+10000000,i.position,i.issue_number FROM reading_order_items i JOIN reading_orders o ON o.id=i.reading_order_id WHERE o.user_id=1
-- NEXT_STATEMENT
INSERT INTO continuity_plans (id,user_id,name,ordering_mode,nodes_json,lanes_json,created_at,updated_at) SELECT id+10000000,23199,name,ordering_mode,pg_temp.qa_rewrite_json(nodes_json::jsonb),pg_temp.qa_rewrite_json(lanes_json::jsonb),created_at,updated_at FROM continuity_plans WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO reading_plan_issues (plan_id,occurrence_id,issue_id,lane_id,display_position,label,reader_role,reader_optional,is_checkpoint,source_metadata_json) SELECT i.plan_id+10000000,i.occurrence_id,i.issue_id+10000000,i.lane_id,i.display_position,i.label,i.reader_role,i.reader_optional,i.is_checkpoint,pg_temp.qa_rewrite_json(i.source_metadata_json::jsonb) FROM reading_plan_issues i JOIN continuity_plans p ON p.id=i.plan_id WHERE p.user_id=1
-- NEXT_STATEMENT
INSERT INTO reading_plan_sources (id,plan_id,raw_source_path,repository,source_path,revision_sha,content_hash,cbl_source_list_id,custom_cbl_list_id,adopted_at,recorded_at,metadata_json)
SELECT s.id+10000000,s.plan_id+10000000,
 CASE WHEN s.raw_source_path ~ '^custom-cbl:[0-9]+$' THEN 'custom-cbl:' || ((substring(s.raw_source_path from 12)::bigint)+10000000)::text ELSE s.raw_source_path END,
 s.repository,s.source_path,s.revision_sha,s.content_hash,s.cbl_source_list_id,
 CASE WHEN s.custom_cbl_list_id IS NULL THEN NULL ELSE s.custom_cbl_list_id+10000000 END,
 s.adopted_at,s.recorded_at,pg_temp.qa_rewrite_json(s.metadata_json::jsonb)
FROM reading_plan_sources s JOIN continuity_plans p ON p.id=s.plan_id
WHERE p.user_id=1-- NEXT_STATEMENT
INSERT INTO reading_plan_source_placements (plan_id,occurrence_id,plan_source_id,source_position) SELECT x.plan_id+10000000,x.occurrence_id,x.plan_source_id+10000000,x.source_position FROM reading_plan_source_placements x JOIN continuity_plans p ON p.id=x.plan_id WHERE p.user_id=1
-- NEXT_STATEMENT
INSERT INTO reading_plan_release_sources (id,plan_id,thread_id,external_identity_id,enabled,last_synced_at,created_at,updated_at) SELECT x.id+10000000,x.plan_id+10000000,x.thread_id+10000000,x.external_identity_id,x.enabled,x.last_synced_at,x.created_at,x.updated_at FROM reading_plan_release_sources x JOIN continuity_plans p ON p.id=x.plan_id WHERE p.user_id=1
-- NEXT_STATEMENT
INSERT INTO reading_plan_dependencies (plan_id,dependency_id,explanation) SELECT x.plan_id+10000000,x.dependency_id+10000000,x.explanation FROM reading_plan_dependencies x JOIN continuity_plans p ON p.id=x.plan_id WHERE p.user_id=1
-- NEXT_STATEMENT
INSERT INTO continuity_rules (id,user_id,source_type,source_id,target_type,target_id,satisfaction_type,checkpoint_issue_id,note,created_at,updated_at,legacy_dependency_id,convergence_targets) SELECT id+10000000,23199,source_type,CASE WHEN source_type IN ('issue','crossover','thread','plan','group') THEN source_id+10000000 ELSE source_id END,target_type,CASE WHEN target_type IN ('issue','crossover','thread','plan','group') THEN target_id+10000000 ELSE target_id END,satisfaction_type,CASE WHEN checkpoint_issue_id IS NULL THEN NULL ELSE checkpoint_issue_id+10000000 END,CASE WHEN note ~ '^continuity-plan:[0-9]+$' THEN 'continuity-plan:'||((substring(note from 17)::bigint)+10000000)::text ELSE note END,created_at,updated_at,CASE WHEN legacy_dependency_id IS NULL THEN NULL ELSE legacy_dependency_id+10000000 END,pg_temp.qa_rewrite_json(convergence_targets::jsonb) FROM continuity_rules WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO continuity_rule_selected_members (id,rule_id,issue_id) SELECT m.id+10000000,m.rule_id+10000000,m.issue_id+10000000 FROM continuity_rule_selected_members m JOIN continuity_rules r ON r.id=m.rule_id WHERE r.user_id=1
-- NEXT_STATEMENT
INSERT INTO cbl_adoption_receipts (id,user_id,cbl_source_list_id,plan_id,request_fingerprint,created_at) SELECT id+10000000,23199,cbl_source_list_id,plan_id+10000000,request_fingerprint,created_at FROM cbl_adoption_receipts WHERE user_id=1
-- NEXT_STATEMENT
INSERT INTO tags (id,name,normalized_name,scope,owner_user_id,color,created_at,updated_at) SELECT id+10000000,name,normalized_name,scope,23199,color,created_at,updated_at FROM tags WHERE owner_user_id=1
-- NEXT_STATEMENT
INSERT INTO tag_assignments (id,tag_id,target_type,target_id,created_at) SELECT a.id+10000000,a.tag_id+10000000,a.target_type,CASE WHEN a.target_type IN ('thread','series','issue') THEN a.target_id+10000000 ELSE a.target_id END,a.created_at FROM tag_assignments a JOIN tags t ON t.id=a.tag_id WHERE t.owner_user_id=1
-- NEXT_STATEMENT
DO $verify$ BEGIN
 IF (SELECT count(*) FROM threads WHERE user_id=1) IS DISTINCT FROM (SELECT count(*) FROM threads WHERE user_id=23199) THEN RAISE EXCEPTION 'thread count mismatch'; END IF;
 IF (SELECT count(*) FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=1) IS DISTINCT FROM (SELECT count(*) FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199) THEN RAISE EXCEPTION 'issue count mismatch'; END IF;
 IF (SELECT count(*) FROM dependencies d JOIN issues i ON i.id=d.source_issue_id JOIN threads t ON t.id=i.thread_id WHERE t.user_id=1) IS DISTINCT FROM (SELECT count(*) FROM dependencies d JOIN issues i ON i.id=d.source_issue_id JOIN threads t ON t.id=i.thread_id WHERE t.user_id=23199) THEN RAISE EXCEPTION 'dependency count mismatch'; END IF;
 IF (SELECT count(*) FROM custom_cbl_lists WHERE user_id=1) IS DISTINCT FROM (SELECT count(*) FROM custom_cbl_lists WHERE user_id=23199) THEN RAISE EXCEPTION 'list count mismatch'; END IF;
 IF (SELECT count(*) FROM custom_cbl_entries e JOIN custom_cbl_lists l ON l.id=e.list_id WHERE l.user_id=1) IS DISTINCT FROM (SELECT count(*) FROM custom_cbl_entries e JOIN custom_cbl_lists l ON l.id=e.list_id WHERE l.user_id=23199) THEN RAISE EXCEPTION 'list entry count mismatch'; END IF;
 IF (SELECT count(*) FROM continuity_plans WHERE user_id=1) IS DISTINCT FROM (SELECT count(*) FROM continuity_plans WHERE user_id=23199) THEN RAISE EXCEPTION 'plan count mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM issues s JOIN threads t ON t.id=s.thread_id LEFT JOIN issues q ON q.id=s.id+10000000 WHERE t.user_id=1 AND (q.id IS NULL OR q.status IS DISTINCT FROM s.status OR q.thread_id IS DISTINCT FROM s.thread_id+10000000)) THEN RAISE EXCEPTION 'QA issue progress/owner mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM threads s LEFT JOIN threads q ON q.id=s.id+10000000 WHERE s.user_id=1 AND (q.id IS NULL OR q.title IS DISTINCT FROM s.title OR q.next_unread_issue_id IS DISTINCT FROM CASE WHEN s.next_unread_issue_id IS NULL THEN NULL ELSE s.next_unread_issue_id+10000000 END)) THEN RAISE EXCEPTION 'QA thread/frontier mismatch'; END IF;
 IF EXISTS (
 SELECT 1 FROM continuity_rules r
 CROSS JOIN LATERAL jsonb_array_elements(r.convergence_targets::jsonb) e(value)
 LEFT JOIN issues i ON i.id=(e.value->>'id')::int
 LEFT JOIN threads t ON t.id=i.thread_id
 WHERE r.user_id=23199 AND e.value->>'type'='issue' AND (i.id IS NULL OR t.user_id IS DISTINCT FROM 23199)
 ) THEN RAISE EXCEPTION 'QA convergence target references non-QA issue'; END IF;
 END $verify$
