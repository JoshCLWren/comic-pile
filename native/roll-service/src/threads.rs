                 SELECT u.id AS user_id
                   AND NOT EXISTS (SELECT 1 FROM revoked_tokens r WHERE r.jti = $2)
             SELECT t.id, t.title, t.format, t.issues_remaining, t.queue_position,
                    (SELECT i.issue_number FROM issues i WHERE i.id = t.next_unread_issue_id)
    SELECT u.id AS user_id,
           EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) AS revoked
    SELECT COALESCE($6::int, (SELECT user_id FROM auth WHERE NOT revoked AND password_epoch <= $3)) AS user_id
    SELECT t.id,
    SELECT t.id, t.title, t.format, t.queue_position, t.status,
                THEN (SELECT count(*)::int FROM issues i
           (SELECT i.issue_number FROM issues i WHERE i.id = t.next_unread_issue_id) AS next_issue_number
    SELECT p.id AS thread_id,
        SELECT thread_state.thread_id,
            SELECT i.id, i.thread_id,
            WHERE i.thread_id IN (SELECT id FROM page WHERE total_issues IS NOT NULL)
SELECT json_build_object(
    'auth', (SELECT json_build_object(
    'active_count', (SELECT count(*)::int FROM threads t
        SELECT json_agg(json_build_object('id', l.id, 'name', l.name) ORDER BY l.id)
        SELECT json_agg(json_build_object(
                SELECT json_agg(json_build_object(
                       OR tg.owner_user_id = (SELECT user_id FROM me))
                SELECT json_agg(ei.metadata_json ORDER BY m.confidence DESC NULLS LAST, ei.id)
            'health', (SELECT json_build_object(
