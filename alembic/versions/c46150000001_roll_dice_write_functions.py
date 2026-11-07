"""Move single-statement dice-command/reset writes into VOLATILE functions.

Revision ID: c46150000001
Revises: c44050000002

The data-modifying CTE form this replaces (#4615) is not semantically
equivalent under READ COMMITTED: the whole statement shares one snapshot
taken before the MATERIALIZED advisory lock is acquired, so a concurrent
same-key retry misses the winner's receipt and fails on the unique
idempotency index instead of replaying, and distinct commands record a
stale ``die_before`` (proven by ``dice_single_statement`` concurrency
regression).

Each PL/pgSQL command runs with a fresh READ COMMITTED snapshot, so
lock-then-read-then-write observes the winner's committed rows. The
client still issues exactly one SQL command per HTTP request: a single
``SELECT`` of the function. ``SECURITY INVOKER`` keeps ownership and
revocation checks on the caller's role.
"""

from alembic import op


revision = "c46150000001"
down_revision = "c44050000002"
branch_labels = None
depends_on = None


_DICE_COMMAND_FUNCTION = """
CREATE OR REPLACE FUNCTION public.roll_dice_command_write(
    p_username text,
    p_jti text,
    p_expected_epoch bigint,
    p_key text,
    p_die int,
    p_context text
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
AS $func$
DECLARE
    v_auth record;
    v_user int;
    v_prev record;
    v_die_before int;
    v_event_id int;
BEGIN
    -- Auth lookup; each command takes a fresh snapshot.
    SELECT user_id, password_epoch, revoked INTO v_auth FROM (
        SELECT u.id AS user_id,
               COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
               EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = p_jti) AS revoked
        FROM users u
        WHERE u.username = p_username
        LIMIT 1
    ) AS resolved;
    IF v_auth IS NULL THEN
        RETURN jsonb_build_object(
            'auth', NULL, 'event_id', NULL::int, 'die_before', NULL::int,
            'die_after', NULL::int, 'replayed', false, 'context', NULL::text,
            'session_id', NULL::int, 'session_cleared', NULL::bigint
        )::text;
    END IF;
    IF NOT v_auth.revoked AND v_auth.password_epoch <= p_expected_epoch THEN
        v_user := v_auth.user_id;
    END IF;
    IF v_user IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(v_user::bigint);
    END IF;
    -- Fresh snapshot after the lock: observe the winner's committed receipt.
    SELECT id, die, die_after, context::text AS context INTO v_prev
    FROM events
    WHERE user_id = v_user AND context->>'dice_command_key' = p_key
    LIMIT 1;
    IF FOUND THEN
        RETURN jsonb_build_object(
            'auth', jsonb_build_object('password_epoch', v_auth.password_epoch, 'revoked', v_auth.revoked),
            'event_id', v_prev.id, 'die_before', v_prev.die, 'die_after', v_prev.die_after,
            'replayed', true, 'context', v_prev.context,
            'session_id', NULL::int, 'session_cleared', NULL::bigint
        )::text;
    END IF;
    IF v_user IS NULL THEN
        RETURN jsonb_build_object(
            'auth', jsonb_build_object('password_epoch', v_auth.password_epoch, 'revoked', v_auth.revoked),
            'event_id', NULL::int, 'die_before', NULL::int, 'die_after', NULL::int,
            'replayed', false, 'context', NULL::text,
            'session_id', NULL::int, 'session_cleared', NULL::bigint
        )::text;
    END IF;
    SELECT die_after INTO v_die_before FROM events
    WHERE user_id = v_user
      AND type IN ('rate', 'snooze', 'undo', 'manual_die', 'reset_dice')
      AND die_after IN (2, 4, 6, 8, 10, 12, 20, 30, 50, 100)
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;
    v_die_before := CASE
        WHEN v_die_before IN (30, 50, 100) THEN 20
        WHEN v_die_before IN (2, 4, 6, 8, 10, 12, 20) THEN v_die_before
        ELSE 6
    END;
    INSERT INTO events
        (user_id, type, timestamp, die, die_after, thread_id, issue_id, rating, context)
    VALUES (v_user, 'manual_die', clock_timestamp(), v_die_before, p_die, NULL, NULL, NULL, p_context::text::json)
    RETURNING id INTO v_event_id;
    RETURN jsonb_build_object(
        'auth', jsonb_build_object('password_epoch', v_auth.password_epoch, 'revoked', v_auth.revoked),
        'event_id', v_event_id, 'die_before', v_die_before, 'die_after', p_die,
        'replayed', false, 'context', p_context,
        'session_id', NULL::int, 'session_cleared', NULL::bigint
    )::text;
END
$func$
"""

_RESET_FUNCTION = """
CREATE OR REPLACE FUNCTION public.roll_reset_write(
    p_username text,
    p_jti text,
    p_expected_epoch bigint,
    p_key text,
    p_context text,
    p_now double precision,
    p_gap_hours integer
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
AS $func$
DECLARE
    v_auth record;
    v_user int;
    v_prev record;
    v_die_before int;
    v_event_id int;
    v_session_id int;
    v_cleared bigint := 0;
BEGIN
    SELECT user_id, password_epoch, revoked INTO v_auth FROM (
        SELECT u.id AS user_id,
               COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
               EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = p_jti) AS revoked
        FROM users u
        WHERE u.username = p_username
        LIMIT 1
    ) AS resolved;
    IF v_auth IS NULL THEN
        RETURN jsonb_build_object(
            'auth', NULL, 'event_id', NULL::int, 'die_before', NULL::int,
            'die_after', NULL::int, 'replayed', false, 'context', NULL::text,
            'session_id', NULL::int, 'session_cleared', 0::bigint
        )::text;
    END IF;
    IF NOT v_auth.revoked AND v_auth.password_epoch <= p_expected_epoch THEN
        v_user := v_auth.user_id;
    END IF;
    IF v_user IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(v_user::bigint);
    END IF;
    -- Current-session resolution after the lock, with a fresh snapshot.
    SELECT s.id INTO v_session_id
    FROM sessions s LEFT JOIN LATERAL
      (SELECT max(timestamp) AS last_event FROM events WHERE session_id = s.id) e ON true
    WHERE s.user_id = v_user AND s.ended_at IS NULL
      AND greatest(s.started_at,
          CASE WHEN s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL
              THEN s.pending_thread_updated_at END,
          e.last_event) >= to_timestamp(p_now) - make_interval(hours => p_gap_hours)
    ORDER BY (s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL) DESC,
      greatest(s.started_at,
          CASE WHEN s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL
              THEN s.pending_thread_updated_at END,
          e.last_event) DESC, s.started_at DESC, s.id DESC
    LIMIT 1;
    SELECT id, die, die_after, context::text AS context INTO v_prev
    FROM events
    WHERE user_id = v_user AND context->>'dice_command_key' = p_key
    LIMIT 1;
    IF FOUND THEN
        RETURN jsonb_build_object(
            'auth', jsonb_build_object('password_epoch', v_auth.password_epoch, 'revoked', v_auth.revoked),
            'event_id', v_prev.id, 'die_before', v_prev.die, 'die_after', v_prev.die_after,
            'replayed', true, 'context', v_prev.context,
            'session_id', v_session_id, 'session_cleared', 0::bigint
        )::text;
    END IF;
    IF v_user IS NULL THEN
        RETURN jsonb_build_object(
            'auth', jsonb_build_object('password_epoch', v_auth.password_epoch, 'revoked', v_auth.revoked),
            'event_id', NULL::int, 'die_before', NULL::int, 'die_after', NULL::int,
            'replayed', false, 'context', NULL::text,
            'session_id', v_session_id, 'session_cleared', 0::bigint
        )::text;
    END IF;
    SELECT die_after INTO v_die_before FROM events
    WHERE user_id = v_user
      AND type IN ('rate', 'snooze', 'undo', 'manual_die', 'reset_dice')
      AND die_after IN (2, 4, 6, 8, 10, 12, 20, 30, 50, 100)
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;
    v_die_before := CASE
        WHEN v_die_before IN (30, 50, 100) THEN 20
        WHEN v_die_before IN (2, 4, 6, 8, 10, 12, 20) THEN v_die_before
        ELSE 6
    END;
    INSERT INTO events
        (user_id, type, timestamp, die, die_after, thread_id, issue_id, rating, context)
    VALUES (v_user, 'reset_dice', clock_timestamp(), v_die_before, 6, NULL, NULL, NULL, p_context::text::json)
    RETURNING id INTO v_event_id;
    -- Only a fresh reset clears; a replay returns above and never reaches here.
    UPDATE sessions
    SET pending_thread_id = NULL, pending_issue_id = NULL,
        pending_thread_updated_at = NULL, manual_die = NULL
    WHERE id = v_session_id AND user_id = v_user;
    GET DIAGNOSTICS v_cleared = ROW_COUNT;
    RETURN jsonb_build_object(
        'auth', jsonb_build_object('password_epoch', v_auth.password_epoch, 'revoked', v_auth.revoked),
        'event_id', v_event_id, 'die_before', v_die_before, 'die_after', 6,
        'replayed', false, 'context', p_context,
        'session_id', v_session_id, 'session_cleared', v_cleared
    )::text;
END
$func$
"""


def upgrade() -> None:
    # Drop the pre-release overload so argument resolution cannot pick a
    # stale `double precision` gap variant (CREATE OR REPLACE alone would
    # leave both overloads in place).
    op.execute(
        "DROP FUNCTION IF EXISTS public.roll_reset_write("
        "text, text, bigint, text, text, double precision, double precision)"
    )
    op.execute(_DICE_COMMAND_FUNCTION)
    op.execute(_RESET_FUNCTION)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.roll_dice_command_write(text, text, bigint, text, int, text)")
    op.execute("DROP FUNCTION IF EXISTS public.roll_reset_write(text, text, bigint, text, text, double precision, integer)")
