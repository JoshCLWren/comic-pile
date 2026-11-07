--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: assign_event_owner(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.assign_event_owner() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE inferred_owner integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                -- Legacy writers do not yet pass user_id. Most direct Mark Read,
                -- issue, and queue events already have an owned thread/issue.
                -- Deletions with no surviving references pass user_id explicitly.
                IF NEW.session_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM sessions WHERE id = NEW.session_id;
                ELSIF NEW.thread_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM threads WHERE id = NEW.thread_id;
                ELSIF NEW.issue_id IS NOT NULL THEN
                    SELECT t.user_id INTO inferred_owner
                    FROM issues i JOIN threads t ON t.id = i.thread_id
                    WHERE i.id = NEW.issue_id;
                ELSIF NEW.selected_thread_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM threads WHERE id = NEW.selected_thread_id;
                ELSIF NEW.source_roll_event_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM events WHERE id = NEW.source_roll_event_id;
                END IF;
                IF inferred_owner IS NOT NULL AND NEW.user_id IS NOT NULL
                   AND NEW.user_id <> inferred_owner THEN
                    RAISE EXCEPTION 'event owner conflicts with owning reference'
                        USING ERRCODE = '23514';
                END IF;
                NEW.user_id := COALESCE(NEW.user_id, inferred_owner);
                IF NEW.user_id IS NULL THEN
                    RAISE EXCEPTION 'event requires an owner or an owned reference'
                        USING ERRCODE = '23502';
                END IF;
            ELSE
                -- Ownership is established on insert and never inferred or
                -- reassigned later. A session-cleanup SET NULL must not
                -- attribute a preserved historical row, and a recorded owner
                -- must never move to a different reader.
                IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                    RAISE EXCEPTION 'event ownership is immutable'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            -- A compound event may carry several references. The first
            -- determines a missing owner, but *every* existing reference
            -- must agree with that owner to prevent cross-reader linkage.
            -- Unattributed historical rows stay outside owner projections.
            IF NEW.user_id IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1 FROM sessions s
                    WHERE s.id = NEW.session_id AND s.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM threads t
                    WHERE t.id = NEW.thread_id AND t.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM issues i JOIN threads t ON t.id = i.thread_id
                    WHERE i.id = NEW.issue_id AND t.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM threads t
                    WHERE t.id = NEW.selected_thread_id AND t.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM events source
                    WHERE source.id = NEW.source_roll_event_id
                      AND source.user_id IS NOT NULL
                      AND source.user_id <> NEW.user_id
                ) THEN
                    RAISE EXCEPTION 'event references data owned by another user'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: roll_dice_command_write(text, text, bigint, text, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.roll_dice_command_write(p_username text, p_jti text, p_expected_epoch bigint, p_key text, p_die integer, p_context text) RETURNS text
    LANGUAGE plpgsql
    AS $$
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
$$;


--
-- Name: roll_reset_write(text, text, bigint, text, text, double precision, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.roll_reset_write(p_username text, p_jti text, p_expected_epoch bigint, p_key text, p_context text, p_now double precision, p_gap_hours integer) RETURNS text
    LANGUAGE plpgsql
    AS $$
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
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: catalog_commit_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.catalog_commit_receipts (
    id integer NOT NULL,
    user_id integer NOT NULL,
    idempotency_key character varying(100) NOT NULL,
    endpoint character varying(100) NOT NULL,
    request_fingerprint character varying(64) NOT NULL,
    response_json json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: catalog_commit_receipts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.catalog_commit_receipts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: catalog_commit_receipts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.catalog_commit_receipts_id_seq OWNED BY public.catalog_commit_receipts.id;


--
-- Name: catalog_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.catalog_issues (
    id bigint NOT NULL,
    canonical_external_identity_id integer NOT NULL,
    catalog_series_id bigint,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: catalog_issues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.catalog_issues_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: catalog_issues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.catalog_issues_id_seq OWNED BY public.catalog_issues.id;


--
-- Name: catalog_series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.catalog_series (
    id bigint NOT NULL,
    canonical_external_identity_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: catalog_series_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.catalog_series_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: catalog_series_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.catalog_series_id_seq OWNED BY public.catalog_series.id;


--
-- Name: cbl_adoption_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cbl_adoption_receipts (
    id integer NOT NULL,
    user_id integer NOT NULL,
    cbl_source_list_id integer NOT NULL,
    plan_id integer NOT NULL,
    request_fingerprint character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: cbl_adoption_receipts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cbl_adoption_receipts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cbl_adoption_receipts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cbl_adoption_receipts_id_seq OWNED BY public.cbl_adoption_receipts.id;


--
-- Name: cbl_source_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cbl_source_entries (
    id integer NOT NULL,
    list_id integer NOT NULL,
    "position" integer NOT NULL,
    series_name character varying(500) NOT NULL,
    issue_number character varying(100) NOT NULL,
    volume_year integer,
    publication_year integer,
    external_series_identity_id integer,
    external_issue_identity_id integer,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: cbl_source_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cbl_source_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cbl_source_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cbl_source_entries_id_seq OWNED BY public.cbl_source_entries.id;


--
-- Name: cbl_source_lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cbl_source_lists (
    id integer NOT NULL,
    source_id integer NOT NULL,
    source_path character varying(1000) NOT NULL,
    name character varying(500) NOT NULL,
    declared_issue_count integer,
    content_hash character varying(64) NOT NULL,
    revision_sha character varying(64) NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: cbl_source_lists_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cbl_source_lists_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cbl_source_lists_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cbl_source_lists_id_seq OWNED BY public.cbl_source_lists.id;


--
-- Name: cbl_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cbl_sources (
    id integer NOT NULL,
    repository character varying(255) NOT NULL,
    revision_sha character varying(64) NOT NULL,
    synced_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: cbl_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cbl_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cbl_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cbl_sources_id_seq OWNED BY public.cbl_sources.id;


--
-- Name: collection_exclusions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.collection_exclusions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    provider character varying(50),
    external_volume_id character varying(100),
    thread_id integer,
    issue_id integer,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_collection_exclusion_exactly_one_target CHECK (((num_nonnulls(external_volume_id, thread_id, issue_id) = 1) AND ((provider IS NULL) = (external_volume_id IS NULL)))),
    CONSTRAINT ck_collection_exclusion_positive_ids CHECK ((((thread_id IS NULL) OR (thread_id > 0)) AND ((issue_id IS NULL) OR (issue_id > 0))))
);


--
-- Name: collection_exclusions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.collection_exclusions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: collection_exclusions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.collection_exclusions_id_seq OWNED BY public.collection_exclusions.id;


--
-- Name: comicvine_metadata_refresh_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comicvine_metadata_refresh_requests (
    id integer NOT NULL,
    external_identity_id integer NOT NULL,
    state character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone NOT NULL,
    lease_expires_at timestamp with time zone,
    last_error character varying(200),
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_comicvine_metadata_refresh_state CHECK (((state)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'no_credits'::character varying, 'deferred'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: comicvine_metadata_refresh_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.comicvine_metadata_refresh_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: comicvine_metadata_refresh_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.comicvine_metadata_refresh_requests_id_seq OWNED BY public.comicvine_metadata_refresh_requests.id;


--
-- Name: continuity_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.continuity_plans (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(200) NOT NULL,
    ordering_mode character varying(32) NOT NULL,
    nodes_json json NOT NULL,
    lanes_json json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_continuity_plans_ordering_mode CHECK (((ordering_mode)::text = ANY ((ARRAY['informational'::character varying, 'strict_sequential'::character varying])::text[])))
);


--
-- Name: continuity_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.continuity_plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: continuity_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.continuity_plans_id_seq OWNED BY public.continuity_plans.id;


--
-- Name: continuity_rule_selected_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.continuity_rule_selected_members (
    id integer NOT NULL,
    rule_id integer NOT NULL,
    issue_id integer NOT NULL
);


--
-- Name: continuity_rule_selected_members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.continuity_rule_selected_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: continuity_rule_selected_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.continuity_rule_selected_members_id_seq OWNED BY public.continuity_rule_selected_members.id;


--
-- Name: continuity_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.continuity_rules (
    id integer NOT NULL,
    user_id integer NOT NULL,
    source_type character varying(20) NOT NULL,
    source_id integer NOT NULL,
    target_type character varying(20) NOT NULL,
    target_id integer NOT NULL,
    satisfaction_type character varying(32) NOT NULL,
    checkpoint_issue_id integer,
    note character varying(500),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    legacy_dependency_id integer,
    convergence_targets json,
    CONSTRAINT ck_continuity_rule_checkpoint_shape CHECK (((((satisfaction_type)::text = 'checkpoint'::text) AND (checkpoint_issue_id IS NOT NULL)) OR (((satisfaction_type)::text = 'converged'::text) AND (convergence_targets IS NOT NULL) AND ((convergence_targets)::text <> 'null'::text)) OR (((satisfaction_type)::text <> ALL ((ARRAY['checkpoint'::character varying, 'converged'::character varying])::text[])) AND (checkpoint_issue_id IS NULL) AND ((convergence_targets IS NULL) OR ((convergence_targets)::text = 'null'::text))))),
    CONSTRAINT ck_continuity_rule_not_self CHECK (((NOT (((source_type)::text = (target_type)::text) AND (source_id = target_id))) OR ((satisfaction_type)::text = 'converged'::text))),
    CONSTRAINT ck_continuity_rule_satisfaction_type CHECK (((satisfaction_type)::text = ANY ((ARRAY['item_read'::character varying, 'all_members_read'::character varying, 'checkpoint'::character varying, 'selected_members_read'::character varying, 'converged'::character varying])::text[]))),
    CONSTRAINT ck_continuity_rule_source_type CHECK (((source_type)::text = ANY ((ARRAY['issue'::character varying, 'crossover'::character varying])::text[]))),
    CONSTRAINT ck_continuity_rule_target_type CHECK (((target_type)::text = ANY ((ARRAY['issue'::character varying, 'crossover'::character varying])::text[])))
);


--
-- Name: continuity_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.continuity_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: continuity_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.continuity_rules_id_seq OWNED BY public.continuity_rules.id;


--
-- Name: custom_cbl_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.custom_cbl_entries (
    id integer NOT NULL,
    list_id integer NOT NULL,
    issue_id integer NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    is_checkpoint boolean DEFAULT false NOT NULL,
    checkpoint_target_issue_ids json DEFAULT '[]'::json NOT NULL,
    gate character varying(14) DEFAULT 'none'::character varying NOT NULL,
    skipped boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_custom_cbl_entries_gate CHECK (((gate)::text = ANY ((ARRAY['none'::character varying, 'hold'::character varying, 'after_previous'::character varying])::text[])))
);


--
-- Name: custom_cbl_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.custom_cbl_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: custom_cbl_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.custom_cbl_entries_id_seq OWNED BY public.custom_cbl_entries.id;


--
-- Name: custom_cbl_lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.custom_cbl_lists (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    mode character varying(6) DEFAULT 'loose'::character varying NOT NULL,
    overlap_decisions_updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_custom_cbl_lists_mode CHECK (((mode)::text = ANY ((ARRAY['strict'::character varying, 'loose'::character varying])::text[])))
);


--
-- Name: custom_cbl_lists_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.custom_cbl_lists_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: custom_cbl_lists_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.custom_cbl_lists_id_seq OWNED BY public.custom_cbl_lists.id;


--
-- Name: custom_cbl_overlap_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.custom_cbl_overlap_decisions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    list_id integer NOT NULL,
    continuing_external_identity_id integer NOT NULL,
    waiting_external_identity_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_custom_cbl_overlap_decision_distinct_volumes CHECK ((continuing_external_identity_id <> waiting_external_identity_id))
);


--
-- Name: custom_cbl_overlap_decisions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.custom_cbl_overlap_decisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: custom_cbl_overlap_decisions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.custom_cbl_overlap_decisions_id_seq OWNED BY public.custom_cbl_overlap_decisions.id;


--
-- Name: custom_cbl_source_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.custom_cbl_source_links (
    id integer NOT NULL,
    user_id integer NOT NULL,
    cbl_source_list_id integer NOT NULL,
    custom_cbl_list_id integer NOT NULL,
    source_revision_sha character varying(64) NOT NULL,
    source_content_hash character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: custom_cbl_source_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.custom_cbl_source_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: custom_cbl_source_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.custom_cbl_source_links_id_seq OWNED BY public.custom_cbl_source_links.id;


--
-- Name: delivery_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.delivery_records (
    id integer NOT NULL,
    source_repository character varying(255) NOT NULL,
    target_repository character varying(255) NOT NULL,
    target_branch character varying(255) NOT NULL,
    target_pr_number integer,
    target_merge_sha character varying(64),
    issue_number integer,
    status character varying(50) NOT NULL,
    worker_id character varying(100) NOT NULL,
    error_message text,
    metadata_json json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_delivery_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'branch_created'::character varying, 'pr_opened'::character varying, 'merged'::character varying, 'failed'::character varying, 'released'::character varying])::text[]))),
    CONSTRAINT ck_delivery_target_repo CHECK (((target_repository)::text = ANY ((ARRAY['JoshCLWren/comic-pile'::character varying, 'JoshCLWren/Latticery'::character varying])::text[])))
);


--
-- Name: delivery_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.delivery_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: delivery_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.delivery_records_id_seq OWNED BY public.delivery_records.id;


--
-- Name: dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dependencies (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    source_issue_id integer NOT NULL,
    target_issue_id integer NOT NULL,
    note character varying(255),
    origin character varying(20),
    classification character varying(1),
    provenance character varying(2000),
    CONSTRAINT ck_dependency_classification CHECK (((classification IS NULL) OR ((classification)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying, 'D'::character varying])::text[])))),
    CONSTRAINT ck_dependency_converted_provenance CHECK ((((origin)::text IS DISTINCT FROM 'converted'::text) OR ((classification IS NOT NULL) AND (provenance IS NOT NULL)))),
    CONSTRAINT ck_dependency_exactly_one_type CHECK (((source_issue_id IS NOT NULL) AND (target_issue_id IS NOT NULL))),
    CONSTRAINT ck_dependency_origin CHECK (((origin IS NULL) OR ((origin)::text = ANY ((ARRAY['reader'::character varying, 'converted'::character varying])::text[]))))
);


--
-- Name: dependencies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dependencies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dependencies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dependencies_id_seq OWNED BY public.dependencies.id;


--
-- Name: dependency_group_memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dependency_group_memberships (
    id integer NOT NULL,
    group_id integer NOT NULL,
    thread_id integer,
    issue_id integer,
    sequence_order integer,
    CONSTRAINT ck_dependency_group_membership_one_target CHECK ((((thread_id IS NOT NULL) AND (issue_id IS NULL)) OR ((thread_id IS NULL) AND (issue_id IS NOT NULL))))
);


--
-- Name: dependency_group_memberships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dependency_group_memberships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dependency_group_memberships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dependency_group_memberships_id_seq OWNED BY public.dependency_group_memberships.id;


--
-- Name: dependency_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dependency_groups (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(120) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: dependency_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dependency_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dependency_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dependency_groups_id_seq OWNED BY public.dependency_groups.id;


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    id integer NOT NULL,
    type character varying(50) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    die integer,
    result integer,
    selected_thread_id integer,
    selection_method character varying(50),
    rating double precision,
    issues_read integer,
    queue_move character varying(20),
    die_after integer,
    session_id integer,
    thread_id integer,
    issue_id integer,
    issue_number character varying(50),
    recommendation_reason_codes text[],
    source_roll_event_id integer,
    recommendation_context json,
    context json,
    rolling_recommendation_context json,
    user_id integer
);


--
-- Name: events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.events_id_seq OWNED BY public.events.id;


--
-- Name: external_identities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_identities (
    id integer NOT NULL,
    provider character varying(50) NOT NULL,
    entity_type character varying(20) NOT NULL,
    external_id character varying(100) NOT NULL,
    external_url character varying(500),
    metadata_json json NOT NULL,
    provider_updated_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_external_identity_entity_type CHECK (((entity_type)::text = ANY ((ARRAY['issue'::character varying, 'series'::character varying])::text[])))
);


--
-- Name: external_identities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.external_identities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: external_identities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.external_identities_id_seq OWNED BY public.external_identities.id;


--
-- Name: failed_login_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.failed_login_attempts (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    ip_address character varying(45) NOT NULL,
    attempted_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: failed_login_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.failed_login_attempts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: failed_login_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.failed_login_attempts_id_seq OWNED BY public.failed_login_attempts.id;


--
-- Name: github_issue_submission_limits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.github_issue_submission_limits (
    user_id integer NOT NULL,
    last_submitted_at timestamp with time zone
);


--
-- Name: issue_external_identity_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.issue_external_identity_mappings (
    id integer NOT NULL,
    issue_id integer NOT NULL,
    external_identity_id integer NOT NULL,
    status character varying(20) NOT NULL,
    evidence_source character varying(100),
    confidence double precision,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    rejection_reason character varying(500),
    evidence_json json NOT NULL,
    CONSTRAINT ck_issue_external_identity_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_issue_external_identity_status CHECK (((status)::text = ANY ((ARRAY['unresolved'::character varying, 'candidate'::character varying, 'confirmed'::character varying, 'rejected'::character varying, 'deferred'::character varying])::text[])))
);


--
-- Name: issue_external_identity_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.issue_external_identity_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: issue_external_identity_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.issue_external_identity_mappings_id_seq OWNED BY public.issue_external_identity_mappings.id;


--
-- Name: issue_metadata_corrections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.issue_metadata_corrections (
    id integer NOT NULL,
    issue_id integer NOT NULL,
    field_name character varying(100) NOT NULL,
    provider_value text,
    canonical_value text NOT NULL,
    provenance character varying(100) DEFAULT 'user_correction'::character varying NOT NULL,
    created_by integer NOT NULL,
    reverted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: issue_metadata_corrections_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.issue_metadata_corrections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: issue_metadata_corrections_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.issue_metadata_corrections_id_seq OWNED BY public.issue_metadata_corrections.id;


--
-- Name: issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.issues (
    id integer NOT NULL,
    thread_id integer NOT NULL,
    issue_number character varying(50) NOT NULL,
    status character varying(20) NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    "position" integer NOT NULL,
    catalog_issue_id bigint
);


--
-- Name: issues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.issues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: issues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.issues_id_seq OWNED BY public.issues.id;


--
-- Name: migration_data_deletion_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.migration_data_deletion_audit (
    id integer NOT NULL,
    migration_revision character varying(32) NOT NULL,
    resource character varying(100) NOT NULL,
    row_count bigint NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: migration_data_deletion_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.migration_data_deletion_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: migration_data_deletion_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.migration_data_deletion_audit_id_seq OWNED BY public.migration_data_deletion_audit.id;


--
-- Name: password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_reset_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token_digest character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.password_reset_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.password_reset_tokens_id_seq OWNED BY public.password_reset_tokens.id;


--
-- Name: perf_alarm_counters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.perf_alarm_counters (
    fingerprint character varying(32) NOT NULL,
    utc_day date NOT NULL,
    hit_count integer NOT NULL
);


--
-- Name: perf_alarm_incidents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.perf_alarm_incidents (
    fingerprint character varying(32) NOT NULL,
    open_issue_number integer,
    last_closed_issue_number integer,
    last_comment_at timestamp with time zone,
    filing_claimed_at timestamp with time zone
);


--
-- Name: performance_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.performance_metrics (
    id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    deployment_id character varying(255),
    request_path character varying(500),
    metric_type character varying(100) NOT NULL,
    cold boolean NOT NULL,
    response_time_ms double precision NOT NULL,
    success boolean DEFAULT true NOT NULL,
    user_id integer
);


--
-- Name: performance_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.performance_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: performance_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.performance_metrics_id_seq OWNED BY public.performance_metrics.id;


--
-- Name: reading_order_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_order_items (
    id integer NOT NULL,
    reading_order_id integer NOT NULL,
    thread_id integer NOT NULL,
    "position" integer NOT NULL,
    issue_number character varying(50)
);


--
-- Name: reading_order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reading_order_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reading_order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reading_order_items_id_seq OWNED BY public.reading_order_items.id;


--
-- Name: reading_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_orders (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    user_id integer NOT NULL
);


--
-- Name: reading_orders_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reading_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reading_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reading_orders_id_seq OWNED BY public.reading_orders.id;


--
-- Name: reading_plan_dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_plan_dependencies (
    plan_id integer NOT NULL,
    dependency_id integer NOT NULL,
    explanation character varying(500)
);


--
-- Name: reading_plan_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_plan_issues (
    plan_id integer NOT NULL,
    occurrence_id character varying(80) NOT NULL,
    issue_id integer NOT NULL,
    lane_id character varying(80) NOT NULL,
    display_position integer NOT NULL,
    label character varying(200),
    reader_role character varying(32),
    reader_optional boolean,
    is_checkpoint boolean DEFAULT false NOT NULL,
    source_metadata_json json
);


--
-- Name: reading_plan_release_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_plan_release_sources (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    thread_id integer NOT NULL,
    external_identity_id integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: reading_plan_release_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reading_plan_release_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reading_plan_release_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reading_plan_release_sources_id_seq OWNED BY public.reading_plan_release_sources.id;


--
-- Name: reading_plan_source_placements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_plan_source_placements (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    occurrence_id character varying(80) NOT NULL,
    plan_source_id integer NOT NULL,
    source_position integer
);


--
-- Name: reading_plan_source_placements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reading_plan_source_placements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reading_plan_source_placements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reading_plan_source_placements_id_seq OWNED BY public.reading_plan_source_placements.id;


--
-- Name: reading_plan_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reading_plan_sources (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    raw_source_path character varying(1000) NOT NULL,
    repository character varying(255),
    source_path character varying(1000),
    revision_sha character varying(64),
    content_hash character varying(64),
    cbl_source_list_id integer,
    custom_cbl_list_id integer,
    adopted_at timestamp with time zone,
    recorded_at timestamp with time zone NOT NULL,
    metadata_json json
);


--
-- Name: reading_plan_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reading_plan_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reading_plan_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reading_plan_sources_id_seq OWNED BY public.reading_plan_sources.id;


--
-- Name: recommendation_contexts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendation_contexts (
    id integer NOT NULL,
    event_id integer NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    intent character varying(30) NOT NULL,
    intent_source character varying(30) NOT NULL,
    intent_confidence double precision DEFAULT '0'::double precision NOT NULL,
    bandwidth character varying(30),
    bandwidth_source character varying(30),
    bandwidth_confidence double precision,
    candidate_factors json,
    final_weight double precision,
    random_bypass boolean DEFAULT false NOT NULL,
    balanced_neutrality boolean DEFAULT false NOT NULL,
    effort_minutes double precision,
    effort_band character varying(20),
    effort_source character varying(30),
    effort_confidence double precision,
    effort_sample_count integer
);


--
-- Name: recommendation_contexts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recommendation_contexts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recommendation_contexts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recommendation_contexts_id_seq OWNED BY public.recommendation_contexts.id;


--
-- Name: releases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.releases (
    id integer NOT NULL,
    source_repository character varying(255) NOT NULL,
    source_pr_number integer,
    source_merge_sha character varying(64),
    merged_at timestamp with time zone,
    released_at timestamp with time zone NOT NULL,
    category character varying(100) NOT NULL,
    title character varying(255) NOT NULL,
    summary text NOT NULL,
    body text,
    visibility character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    sort_order integer NOT NULL,
    provenance_json json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_release_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'published'::character varying, 'retracted'::character varying])::text[]))),
    CONSTRAINT ck_release_visibility CHECK (((visibility)::text = ANY ((ARRAY['public'::character varying, 'internal'::character varying])::text[])))
);


--
-- Name: releases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.releases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: releases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.releases_id_seq OWNED BY public.releases.id;


--
-- Name: revoked_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.revoked_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    jti character varying(64) NOT NULL,
    revoked_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: revoked_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.revoked_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: revoked_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.revoked_tokens_id_seq OWNED BY public.revoked_tokens.id;


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id integer NOT NULL,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ended_at timestamp with time zone,
    start_die integer NOT NULL,
    user_id integer NOT NULL,
    pending_thread_updated_at timestamp with time zone,
    pending_thread_id integer,
    manual_die integer,
    snoozed_thread_ids json,
    pending_issue_id integer,
    predicted_bandwidth character varying(20),
    active_bandwidth character varying(20),
    bandwidth_confidence double precision,
    bandwidth_source character varying(30),
    bandwidth_version character varying(50),
    reading_bandwidth character varying(16),
    reading_intent character varying(16),
    reading_mode_source character varying(16),
    reading_mode_suggested boolean DEFAULT false NOT NULL,
    active_intent character varying(30),
    predicted_intent character varying(30),
    intent_confidence double precision,
    intent_source character varying(30),
    intent_version character varying(50),
    session_mode_correction_guidance json,
    timezone character varying(100),
    bandwidth_updated_at timestamp with time zone,
    skipped_thread_ids json,
    CONSTRAINT ck_sessions_active_bandwidth_valid CHECK (((active_bandwidth IS NULL) OR ((active_bandwidth)::text = ANY ((ARRAY['light'::character varying, 'balanced'::character varying, 'deep'::character varying])::text[])))),
    CONSTRAINT ck_sessions_active_intent_valid CHECK (((active_intent IS NULL) OR ((active_intent)::text = ANY ((ARRAY['balanced'::character varying, 'momentum'::character varying, 'familiar'::character varying, 'explore'::character varying, 'random'::character varying])::text[])))),
    CONSTRAINT ck_sessions_bandwidth_confidence_range CHECK (((bandwidth_confidence IS NULL) OR ((bandwidth_confidence >= (0)::double precision) AND (bandwidth_confidence <= (1)::double precision)))),
    CONSTRAINT ck_sessions_bandwidth_source_valid CHECK (((bandwidth_source IS NULL) OR ((bandwidth_source)::text = ANY ((ARRAY['inferred'::character varying, 'manual'::character varying, 'snooze'::character varying, 'quiz'::character varying])::text[])))),
    CONSTRAINT ck_sessions_intent_confidence_range CHECK (((intent_confidence IS NULL) OR ((intent_confidence >= (0)::double precision) AND (intent_confidence <= (1)::double precision)))),
    CONSTRAINT ck_sessions_intent_source_valid CHECK (((intent_source IS NULL) OR ((intent_source)::text = ANY ((ARRAY['inferred'::character varying, 'manual'::character varying, 'snooze'::character varying, 'quiz'::character varying])::text[])))),
    CONSTRAINT ck_sessions_predicted_bandwidth_valid CHECK (((predicted_bandwidth IS NULL) OR ((predicted_bandwidth)::text = ANY ((ARRAY['light'::character varying, 'balanced'::character varying, 'deep'::character varying])::text[])))),
    CONSTRAINT ck_sessions_predicted_intent_valid CHECK (((predicted_intent IS NULL) OR ((predicted_intent)::text = ANY ((ARRAY['balanced'::character varying, 'momentum'::character varying, 'familiar'::character varying, 'explore'::character varying, 'random'::character varying])::text[]))))
);


--
-- Name: sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sessions_id_seq OWNED BY public.sessions.id;


--
-- Name: snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.snapshots (
    id integer NOT NULL,
    session_id integer NOT NULL,
    event_id integer,
    thread_states json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    description text,
    session_state json,
    snapshot_kind character varying(20),
    schema_version integer
);


--
-- Name: snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.snapshots_id_seq OWNED BY public.snapshots.id;


--
-- Name: tag_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_assignments (
    id integer NOT NULL,
    tag_id integer NOT NULL,
    target_type character varying(50) NOT NULL,
    target_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: tag_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tag_assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tag_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tag_assignments_id_seq OWNED BY public.tag_assignments.id;


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tags (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    normalized_name character varying(100) NOT NULL,
    scope character varying(10) NOT NULL,
    owner_user_id integer,
    color character varying(7) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: tags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tags_id_seq OWNED BY public.tags.id;


--
-- Name: taste_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taste_signals (
    id integer NOT NULL,
    user_id integer NOT NULL,
    signal_type character varying(20) NOT NULL,
    external_key character varying(255) NOT NULL,
    display_name character varying(200) NOT NULL,
    affinity_estimate double precision,
    evidence_count integer DEFAULT 0 NOT NULL,
    distinct_thread_count integer DEFAULT 0 NOT NULL,
    confidence double precision,
    user_verdict character varying(20),
    verdict_at timestamp with time zone,
    first_observed_at timestamp with time zone,
    last_observed_at timestamp with time zone,
    last_prompted_at timestamp with time zone,
    prompt_suppressed_until timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_taste_signal_affinity_range CHECK (((affinity_estimate IS NULL) OR ((affinity_estimate >= ('-1'::integer)::double precision) AND (affinity_estimate <= (1)::double precision)))),
    CONSTRAINT ck_taste_signal_confidence_range CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_taste_signal_evidence_non_negative CHECK (((evidence_count >= 0) AND (distinct_thread_count >= 0))),
    CONSTRAINT ck_taste_signal_signal_type CHECK (((signal_type)::text = ANY ((ARRAY['creator'::character varying, 'character'::character varying, 'team'::character varying, 'publisher'::character varying, 'era'::character varying])::text[]))),
    CONSTRAINT ck_taste_signal_user_verdict CHECK (((user_verdict IS NULL) OR ((user_verdict)::text = ANY ((ARRAY['confirmed'::character varying, 'sometimes'::character varying, 'rejected'::character varying])::text[]))))
);


--
-- Name: taste_signals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.taste_signals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: taste_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.taste_signals_id_seq OWNED BY public.taste_signals.id;


--
-- Name: thread_external_series_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.thread_external_series_mappings (
    id integer NOT NULL,
    thread_id integer NOT NULL,
    external_identity_id integer NOT NULL,
    status character varying(20) NOT NULL,
    evidence_source character varying(100),
    confidence double precision,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_thread_external_series_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_thread_external_series_status CHECK (((status)::text = ANY ((ARRAY['unresolved'::character varying, 'candidate'::character varying, 'confirmed'::character varying, 'rejected'::character varying, 'deferred'::character varying])::text[])))
);


--
-- Name: thread_external_series_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.thread_external_series_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: thread_external_series_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.thread_external_series_mappings_id_seq OWNED BY public.thread_external_series_mappings.id;


--
-- Name: threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.threads (
    id integer NOT NULL,
    title character varying(200) NOT NULL,
    format character varying(50) NOT NULL,
    issues_remaining integer NOT NULL,
    queue_position integer NOT NULL,
    status character varying(20) NOT NULL,
    last_rating double precision,
    last_activity_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    user_id integer NOT NULL,
    notes text,
    is_blocked boolean DEFAULT false NOT NULL,
    is_test boolean DEFAULT false NOT NULL,
    total_issues integer,
    next_unread_issue_id integer,
    reading_progress character varying(20),
    manual_creator_credits json DEFAULT '[]'::json NOT NULL,
    catalog_series_id bigint,
    queue_order_key bigint,
    queue_position_is_manual boolean DEFAULT false NOT NULL
);


--
-- Name: threads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.threads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: threads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.threads_id_seq OWNED BY public.threads.id;


--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preferences (
    id integer NOT NULL,
    user_id integer NOT NULL,
    theme character varying(50) DEFAULT 'classic'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: user_preferences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_preferences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_preferences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_preferences_id_seq OWNED BY public.user_preferences.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    email character varying(255),
    password_hash character varying(255),
    is_admin boolean DEFAULT false NOT NULL,
    password_changed_at timestamp with time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: catalog_commit_receipts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_commit_receipts ALTER COLUMN id SET DEFAULT nextval('public.catalog_commit_receipts_id_seq'::regclass);


--
-- Name: catalog_issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_issues ALTER COLUMN id SET DEFAULT nextval('public.catalog_issues_id_seq'::regclass);


--
-- Name: catalog_series id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_series ALTER COLUMN id SET DEFAULT nextval('public.catalog_series_id_seq'::regclass);


--
-- Name: cbl_adoption_receipts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_adoption_receipts ALTER COLUMN id SET DEFAULT nextval('public.cbl_adoption_receipts_id_seq'::regclass);


--
-- Name: cbl_source_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_entries ALTER COLUMN id SET DEFAULT nextval('public.cbl_source_entries_id_seq'::regclass);


--
-- Name: cbl_source_lists id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_lists ALTER COLUMN id SET DEFAULT nextval('public.cbl_source_lists_id_seq'::regclass);


--
-- Name: cbl_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_sources ALTER COLUMN id SET DEFAULT nextval('public.cbl_sources_id_seq'::regclass);


--
-- Name: collection_exclusions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_exclusions ALTER COLUMN id SET DEFAULT nextval('public.collection_exclusions_id_seq'::regclass);


--
-- Name: comicvine_metadata_refresh_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comicvine_metadata_refresh_requests ALTER COLUMN id SET DEFAULT nextval('public.comicvine_metadata_refresh_requests_id_seq'::regclass);


--
-- Name: continuity_plans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_plans ALTER COLUMN id SET DEFAULT nextval('public.continuity_plans_id_seq'::regclass);


--
-- Name: continuity_rule_selected_members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rule_selected_members ALTER COLUMN id SET DEFAULT nextval('public.continuity_rule_selected_members_id_seq'::regclass);


--
-- Name: continuity_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules ALTER COLUMN id SET DEFAULT nextval('public.continuity_rules_id_seq'::regclass);


--
-- Name: custom_cbl_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_entries ALTER COLUMN id SET DEFAULT nextval('public.custom_cbl_entries_id_seq'::regclass);


--
-- Name: custom_cbl_lists id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_lists ALTER COLUMN id SET DEFAULT nextval('public.custom_cbl_lists_id_seq'::regclass);


--
-- Name: custom_cbl_overlap_decisions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions ALTER COLUMN id SET DEFAULT nextval('public.custom_cbl_overlap_decisions_id_seq'::regclass);


--
-- Name: custom_cbl_source_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links ALTER COLUMN id SET DEFAULT nextval('public.custom_cbl_source_links_id_seq'::regclass);


--
-- Name: delivery_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.delivery_records ALTER COLUMN id SET DEFAULT nextval('public.delivery_records_id_seq'::regclass);


--
-- Name: dependencies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependencies ALTER COLUMN id SET DEFAULT nextval('public.dependencies_id_seq'::regclass);


--
-- Name: dependency_group_memberships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships ALTER COLUMN id SET DEFAULT nextval('public.dependency_group_memberships_id_seq'::regclass);


--
-- Name: dependency_groups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_groups ALTER COLUMN id SET DEFAULT nextval('public.dependency_groups_id_seq'::regclass);


--
-- Name: events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events ALTER COLUMN id SET DEFAULT nextval('public.events_id_seq'::regclass);


--
-- Name: external_identities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities ALTER COLUMN id SET DEFAULT nextval('public.external_identities_id_seq'::regclass);


--
-- Name: failed_login_attempts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.failed_login_attempts ALTER COLUMN id SET DEFAULT nextval('public.failed_login_attempts_id_seq'::regclass);


--
-- Name: issue_external_identity_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_external_identity_mappings ALTER COLUMN id SET DEFAULT nextval('public.issue_external_identity_mappings_id_seq'::regclass);


--
-- Name: issue_metadata_corrections id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_metadata_corrections ALTER COLUMN id SET DEFAULT nextval('public.issue_metadata_corrections_id_seq'::regclass);


--
-- Name: issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues ALTER COLUMN id SET DEFAULT nextval('public.issues_id_seq'::regclass);


--
-- Name: migration_data_deletion_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.migration_data_deletion_audit ALTER COLUMN id SET DEFAULT nextval('public.migration_data_deletion_audit_id_seq'::regclass);


--
-- Name: password_reset_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens ALTER COLUMN id SET DEFAULT nextval('public.password_reset_tokens_id_seq'::regclass);


--
-- Name: performance_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_metrics ALTER COLUMN id SET DEFAULT nextval('public.performance_metrics_id_seq'::regclass);


--
-- Name: reading_order_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_order_items ALTER COLUMN id SET DEFAULT nextval('public.reading_order_items_id_seq'::regclass);


--
-- Name: reading_orders id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_orders ALTER COLUMN id SET DEFAULT nextval('public.reading_orders_id_seq'::regclass);


--
-- Name: reading_plan_release_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_release_sources ALTER COLUMN id SET DEFAULT nextval('public.reading_plan_release_sources_id_seq'::regclass);


--
-- Name: reading_plan_source_placements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_source_placements ALTER COLUMN id SET DEFAULT nextval('public.reading_plan_source_placements_id_seq'::regclass);


--
-- Name: reading_plan_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_sources ALTER COLUMN id SET DEFAULT nextval('public.reading_plan_sources_id_seq'::regclass);


--
-- Name: recommendation_contexts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_contexts ALTER COLUMN id SET DEFAULT nextval('public.recommendation_contexts_id_seq'::regclass);


--
-- Name: releases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases ALTER COLUMN id SET DEFAULT nextval('public.releases_id_seq'::regclass);


--
-- Name: revoked_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revoked_tokens ALTER COLUMN id SET DEFAULT nextval('public.revoked_tokens_id_seq'::regclass);


--
-- Name: sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions ALTER COLUMN id SET DEFAULT nextval('public.sessions_id_seq'::regclass);


--
-- Name: snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots ALTER COLUMN id SET DEFAULT nextval('public.snapshots_id_seq'::regclass);


--
-- Name: tag_assignments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments ALTER COLUMN id SET DEFAULT nextval('public.tag_assignments_id_seq'::regclass);


--
-- Name: tags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags ALTER COLUMN id SET DEFAULT nextval('public.tags_id_seq'::regclass);


--
-- Name: taste_signals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taste_signals ALTER COLUMN id SET DEFAULT nextval('public.taste_signals_id_seq'::regclass);


--
-- Name: thread_external_series_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_external_series_mappings ALTER COLUMN id SET DEFAULT nextval('public.thread_external_series_mappings_id_seq'::regclass);


--
-- Name: threads id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads ALTER COLUMN id SET DEFAULT nextval('public.threads_id_seq'::regclass);


--
-- Name: user_preferences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences ALTER COLUMN id SET DEFAULT nextval('public.user_preferences_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: catalog_commit_receipts catalog_commit_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_commit_receipts
    ADD CONSTRAINT catalog_commit_receipts_pkey PRIMARY KEY (id);


--
-- Name: catalog_issues catalog_issues_canonical_external_identity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_issues
    ADD CONSTRAINT catalog_issues_canonical_external_identity_id_key UNIQUE (canonical_external_identity_id);


--
-- Name: catalog_issues catalog_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_issues
    ADD CONSTRAINT catalog_issues_pkey PRIMARY KEY (id);


--
-- Name: catalog_series catalog_series_canonical_external_identity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_series
    ADD CONSTRAINT catalog_series_canonical_external_identity_id_key UNIQUE (canonical_external_identity_id);


--
-- Name: catalog_series catalog_series_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_series
    ADD CONSTRAINT catalog_series_pkey PRIMARY KEY (id);


--
-- Name: cbl_adoption_receipts cbl_adoption_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_adoption_receipts
    ADD CONSTRAINT cbl_adoption_receipts_pkey PRIMARY KEY (id);


--
-- Name: cbl_source_entries cbl_source_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_entries
    ADD CONSTRAINT cbl_source_entries_pkey PRIMARY KEY (id);


--
-- Name: cbl_source_lists cbl_source_lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_lists
    ADD CONSTRAINT cbl_source_lists_pkey PRIMARY KEY (id);


--
-- Name: cbl_sources cbl_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_sources
    ADD CONSTRAINT cbl_sources_pkey PRIMARY KEY (id);


--
-- Name: cbl_sources cbl_sources_repository_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_sources
    ADD CONSTRAINT cbl_sources_repository_key UNIQUE (repository);


--
-- Name: collection_exclusions collection_exclusions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_exclusions
    ADD CONSTRAINT collection_exclusions_pkey PRIMARY KEY (id);


--
-- Name: comicvine_metadata_refresh_requests comicvine_metadata_refresh_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comicvine_metadata_refresh_requests
    ADD CONSTRAINT comicvine_metadata_refresh_requests_pkey PRIMARY KEY (id);


--
-- Name: continuity_plans continuity_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_plans
    ADD CONSTRAINT continuity_plans_pkey PRIMARY KEY (id);


--
-- Name: continuity_rule_selected_members continuity_rule_selected_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rule_selected_members
    ADD CONSTRAINT continuity_rule_selected_members_pkey PRIMARY KEY (id);


--
-- Name: continuity_rules continuity_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules
    ADD CONSTRAINT continuity_rules_pkey PRIMARY KEY (id);


--
-- Name: custom_cbl_entries custom_cbl_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_entries
    ADD CONSTRAINT custom_cbl_entries_pkey PRIMARY KEY (id);


--
-- Name: custom_cbl_lists custom_cbl_lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_lists
    ADD CONSTRAINT custom_cbl_lists_pkey PRIMARY KEY (id);


--
-- Name: custom_cbl_overlap_decisions custom_cbl_overlap_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions
    ADD CONSTRAINT custom_cbl_overlap_decisions_pkey PRIMARY KEY (id);


--
-- Name: custom_cbl_source_links custom_cbl_source_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links
    ADD CONSTRAINT custom_cbl_source_links_pkey PRIMARY KEY (id);


--
-- Name: delivery_records delivery_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.delivery_records
    ADD CONSTRAINT delivery_records_pkey PRIMARY KEY (id);


--
-- Name: dependencies dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependencies
    ADD CONSTRAINT dependencies_pkey PRIMARY KEY (id);


--
-- Name: dependency_group_memberships dependency_group_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships
    ADD CONSTRAINT dependency_group_memberships_pkey PRIMARY KEY (id);


--
-- Name: dependency_groups dependency_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_groups
    ADD CONSTRAINT dependency_groups_pkey PRIMARY KEY (id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: external_identities external_identities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_pkey PRIMARY KEY (id);


--
-- Name: failed_login_attempts failed_login_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.failed_login_attempts
    ADD CONSTRAINT failed_login_attempts_pkey PRIMARY KEY (id);


--
-- Name: github_issue_submission_limits github_issue_submission_limits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_issue_submission_limits
    ADD CONSTRAINT github_issue_submission_limits_pkey PRIMARY KEY (user_id);


--
-- Name: issue_external_identity_mappings issue_external_identity_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_external_identity_mappings
    ADD CONSTRAINT issue_external_identity_mappings_pkey PRIMARY KEY (id);


--
-- Name: issue_metadata_corrections issue_metadata_corrections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_metadata_corrections
    ADD CONSTRAINT issue_metadata_corrections_pkey PRIMARY KEY (id);


--
-- Name: issues issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues
    ADD CONSTRAINT issues_pkey PRIMARY KEY (id);


--
-- Name: migration_data_deletion_audit migration_data_deletion_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.migration_data_deletion_audit
    ADD CONSTRAINT migration_data_deletion_audit_pkey PRIMARY KEY (id);


--
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- Name: perf_alarm_counters perf_alarm_counters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perf_alarm_counters
    ADD CONSTRAINT perf_alarm_counters_pkey PRIMARY KEY (fingerprint, utc_day);


--
-- Name: perf_alarm_incidents perf_alarm_incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perf_alarm_incidents
    ADD CONSTRAINT perf_alarm_incidents_pkey PRIMARY KEY (fingerprint);


--
-- Name: performance_metrics performance_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_metrics
    ADD CONSTRAINT performance_metrics_pkey PRIMARY KEY (id);


--
-- Name: revoked_tokens pk_revoked_tokens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revoked_tokens
    ADD CONSTRAINT pk_revoked_tokens PRIMARY KEY (id);


--
-- Name: reading_order_items reading_order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_order_items
    ADD CONSTRAINT reading_order_items_pkey PRIMARY KEY (id);


--
-- Name: reading_orders reading_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_orders
    ADD CONSTRAINT reading_orders_pkey PRIMARY KEY (id);


--
-- Name: reading_plan_dependencies reading_plan_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_dependencies
    ADD CONSTRAINT reading_plan_dependencies_pkey PRIMARY KEY (plan_id, dependency_id);


--
-- Name: reading_plan_issues reading_plan_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_issues
    ADD CONSTRAINT reading_plan_issues_pkey PRIMARY KEY (plan_id, occurrence_id);


--
-- Name: reading_plan_release_sources reading_plan_release_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_release_sources
    ADD CONSTRAINT reading_plan_release_sources_pkey PRIMARY KEY (id);


--
-- Name: reading_plan_source_placements reading_plan_source_placements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_source_placements
    ADD CONSTRAINT reading_plan_source_placements_pkey PRIMARY KEY (id);


--
-- Name: reading_plan_sources reading_plan_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_sources
    ADD CONSTRAINT reading_plan_sources_pkey PRIMARY KEY (id);


--
-- Name: recommendation_contexts recommendation_contexts_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_contexts
    ADD CONSTRAINT recommendation_contexts_event_id_key UNIQUE (event_id);


--
-- Name: recommendation_contexts recommendation_contexts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_contexts
    ADD CONSTRAINT recommendation_contexts_pkey PRIMARY KEY (id);


--
-- Name: releases releases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases
    ADD CONSTRAINT releases_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: snapshots snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_pkey PRIMARY KEY (id);


--
-- Name: tag_assignments tag_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments
    ADD CONSTRAINT tag_assignments_pkey PRIMARY KEY (id);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);


--
-- Name: taste_signals taste_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taste_signals
    ADD CONSTRAINT taste_signals_pkey PRIMARY KEY (id);


--
-- Name: thread_external_series_mappings thread_external_series_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_external_series_mappings
    ADD CONSTRAINT thread_external_series_mappings_pkey PRIMARY KEY (id);


--
-- Name: threads threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT threads_pkey PRIMARY KEY (id);


--
-- Name: catalog_commit_receipts uq_catalog_commit_receipt_user_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_commit_receipts
    ADD CONSTRAINT uq_catalog_commit_receipt_user_key UNIQUE (user_id, idempotency_key);


--
-- Name: cbl_adoption_receipts uq_cbl_adoption_receipt_user_list; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_adoption_receipts
    ADD CONSTRAINT uq_cbl_adoption_receipt_user_list UNIQUE (user_id, cbl_source_list_id);


--
-- Name: cbl_source_entries uq_cbl_source_entry_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_entries
    ADD CONSTRAINT uq_cbl_source_entry_position UNIQUE (list_id, "position");


--
-- Name: cbl_source_lists uq_cbl_source_list_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_lists
    ADD CONSTRAINT uq_cbl_source_list_path UNIQUE (source_id, source_path);


--
-- Name: comicvine_metadata_refresh_requests uq_comicvine_metadata_refresh_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comicvine_metadata_refresh_requests
    ADD CONSTRAINT uq_comicvine_metadata_refresh_identity UNIQUE (external_identity_id);


--
-- Name: continuity_rules uq_continuity_rule_edge; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules
    ADD CONSTRAINT uq_continuity_rule_edge UNIQUE (user_id, source_type, source_id, target_type, target_id);


--
-- Name: continuity_rule_selected_members uq_continuity_rule_selected_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rule_selected_members
    ADD CONSTRAINT uq_continuity_rule_selected_member UNIQUE (rule_id, issue_id);


--
-- Name: continuity_rules uq_continuity_rules_legacy_dependency_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules
    ADD CONSTRAINT uq_continuity_rules_legacy_dependency_id UNIQUE (legacy_dependency_id);


--
-- Name: custom_cbl_entries uq_custom_cbl_entry_issue; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_entries
    ADD CONSTRAINT uq_custom_cbl_entry_issue UNIQUE (list_id, issue_id);


--
-- Name: custom_cbl_entries uq_custom_cbl_entry_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_entries
    ADD CONSTRAINT uq_custom_cbl_entry_position UNIQUE (list_id, "position");


--
-- Name: custom_cbl_lists uq_custom_cbl_lists_id_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_lists
    ADD CONSTRAINT uq_custom_cbl_lists_id_user UNIQUE (id, user_id);


--
-- Name: custom_cbl_overlap_decisions uq_custom_cbl_overlap_decision_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions
    ADD CONSTRAINT uq_custom_cbl_overlap_decision_pair UNIQUE (list_id, continuing_external_identity_id, waiting_external_identity_id);


--
-- Name: custom_cbl_source_links uq_custom_cbl_source_link_list; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links
    ADD CONSTRAINT uq_custom_cbl_source_link_list UNIQUE (custom_cbl_list_id);


--
-- Name: custom_cbl_source_links uq_custom_cbl_source_link_user_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links
    ADD CONSTRAINT uq_custom_cbl_source_link_user_source UNIQUE (user_id, cbl_source_list_id);


--
-- Name: dependency_group_memberships uq_dependency_group_issue; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships
    ADD CONSTRAINT uq_dependency_group_issue UNIQUE (group_id, issue_id);


--
-- Name: dependency_group_memberships uq_dependency_group_thread; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships
    ADD CONSTRAINT uq_dependency_group_thread UNIQUE (group_id, thread_id);


--
-- Name: dependency_groups uq_dependency_groups_user_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_groups
    ADD CONSTRAINT uq_dependency_groups_user_name UNIQUE (user_id, name);


--
-- Name: dependencies uq_dependency_issue_edge; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependencies
    ADD CONSTRAINT uq_dependency_issue_edge UNIQUE (source_issue_id, target_issue_id);


--
-- Name: external_identities uq_external_identity_provider_entity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT uq_external_identity_provider_entity UNIQUE (provider, entity_type, external_id);


--
-- Name: issue_external_identity_mappings uq_issue_external_identity_mapping; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_external_identity_mappings
    ADD CONSTRAINT uq_issue_external_identity_mapping UNIQUE (issue_id, external_identity_id);


--
-- Name: issues uq_issue_thread_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues
    ADD CONSTRAINT uq_issue_thread_number UNIQUE (thread_id, issue_number);


--
-- Name: issues uq_issue_thread_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues
    ADD CONSTRAINT uq_issue_thread_position UNIQUE (thread_id, "position") DEFERRABLE INITIALLY DEFERRED;


--
-- Name: issues uq_issues_thread_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues
    ADD CONSTRAINT uq_issues_thread_id_id UNIQUE (thread_id, id);


--
-- Name: password_reset_tokens uq_password_reset_token_digest; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT uq_password_reset_token_digest UNIQUE (token_digest);


--
-- Name: reading_plan_issues uq_reading_plan_issue_lane_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_issues
    ADD CONSTRAINT uq_reading_plan_issue_lane_position UNIQUE (plan_id, lane_id, display_position);


--
-- Name: reading_plan_issues uq_reading_plan_issue_once_per_plan; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_issues
    ADD CONSTRAINT uq_reading_plan_issue_once_per_plan UNIQUE (plan_id, issue_id);


--
-- Name: reading_plan_source_placements uq_reading_plan_source_placement; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_source_placements
    ADD CONSTRAINT uq_reading_plan_source_placement UNIQUE NULLS NOT DISTINCT (plan_id, occurrence_id, plan_source_id, source_position);


--
-- Name: reading_plan_sources uq_reading_plan_source_snapshot; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_sources
    ADD CONSTRAINT uq_reading_plan_source_snapshot UNIQUE NULLS NOT DISTINCT (plan_id, raw_source_path, repository, source_path, revision_sha, content_hash);


--
-- Name: releases uq_release_source_merge_sha; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases
    ADD CONSTRAINT uq_release_source_merge_sha UNIQUE (source_repository, source_merge_sha);


--
-- Name: reading_plan_release_sources uq_release_source_once_per_plan_thread_volume; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_release_sources
    ADD CONSTRAINT uq_release_source_once_per_plan_thread_volume UNIQUE (plan_id, thread_id, external_identity_id);


--
-- Name: releases uq_release_source_pr; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases
    ADD CONSTRAINT uq_release_source_pr UNIQUE (source_repository, source_pr_number);


--
-- Name: revoked_tokens uq_revoked_tokens_jti; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revoked_tokens
    ADD CONSTRAINT uq_revoked_tokens_jti UNIQUE (jti);


--
-- Name: taste_signals uq_taste_signal_user_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taste_signals
    ADD CONSTRAINT uq_taste_signal_user_key UNIQUE (user_id, signal_type, external_key);


--
-- Name: thread_external_series_mappings uq_thread_external_series_mapping; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_external_series_mappings
    ADD CONSTRAINT uq_thread_external_series_mapping UNIQUE (thread_id, external_identity_id);


--
-- Name: user_preferences uq_user_preferences_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT uq_user_preferences_user_id UNIQUE (user_id);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: ix_catalog_commit_receipt_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_catalog_commit_receipt_created_at ON public.catalog_commit_receipts USING btree (created_at);


--
-- Name: ix_catalog_commit_receipt_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_catalog_commit_receipt_user_id ON public.catalog_commit_receipts USING btree (user_id);


--
-- Name: ix_catalog_issues_catalog_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_catalog_issues_catalog_series ON public.catalog_issues USING btree (catalog_series_id);


--
-- Name: ix_catalog_issues_external_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_catalog_issues_external_identity ON public.catalog_issues USING btree (canonical_external_identity_id);


--
-- Name: ix_catalog_series_external_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_catalog_series_external_identity ON public.catalog_series USING btree (canonical_external_identity_id);


--
-- Name: ix_cbl_adoption_receipt_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_adoption_receipt_plan_id ON public.cbl_adoption_receipts USING btree (plan_id);


--
-- Name: ix_cbl_source_entry_issue_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_entry_issue_identity ON public.cbl_source_entries USING btree (external_issue_identity_id);


--
-- Name: ix_cbl_source_entry_list_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_entry_list_id ON public.cbl_source_entries USING btree (list_id);


--
-- Name: ix_cbl_source_entry_series_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_entry_series_identity ON public.cbl_source_entries USING btree (external_series_identity_id);


--
-- Name: ix_cbl_source_list_active_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_list_active_path ON public.cbl_source_lists USING btree (active, source_path text_pattern_ops);


--
-- Name: ix_cbl_source_list_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_list_name_trgm ON public.cbl_source_lists USING gin (name public.gin_trgm_ops);


--
-- Name: ix_cbl_source_list_source_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_list_source_active ON public.cbl_source_lists USING btree (source_id, active);


--
-- Name: ix_cbl_source_list_source_path_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cbl_source_list_source_path_trgm ON public.cbl_source_lists USING gin (source_path public.gin_trgm_ops);


--
-- Name: ix_collection_exclusions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_collection_exclusions_user_id ON public.collection_exclusions USING btree (user_id);


--
-- Name: ix_comicvine_metadata_refresh_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comicvine_metadata_refresh_due ON public.comicvine_metadata_refresh_requests USING btree (state, next_attempt_at);


--
-- Name: ix_continuity_plans_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_continuity_plans_user_id ON public.continuity_plans USING btree (user_id);


--
-- Name: ix_continuity_rule_selected_members_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_continuity_rule_selected_members_issue_id ON public.continuity_rule_selected_members USING btree (issue_id);


--
-- Name: ix_continuity_rule_selected_members_rule_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_continuity_rule_selected_members_rule_id ON public.continuity_rule_selected_members USING btree (rule_id);


--
-- Name: ix_continuity_rules_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_continuity_rules_source ON public.continuity_rules USING btree (user_id, source_type, source_id);


--
-- Name: ix_continuity_rules_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_continuity_rules_target ON public.continuity_rules USING btree (user_id, target_type, target_id);


--
-- Name: ix_continuity_rules_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_continuity_rules_user_id ON public.continuity_rules USING btree (user_id);


--
-- Name: ix_custom_cbl_entries_issue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_custom_cbl_entries_issue ON public.custom_cbl_entries USING btree (issue_id);


--
-- Name: ix_custom_cbl_entries_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_custom_cbl_entries_list ON public.custom_cbl_entries USING btree (list_id);


--
-- Name: ix_custom_cbl_lists_user_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_custom_cbl_lists_user_updated ON public.custom_cbl_lists USING btree (user_id, updated_at);


--
-- Name: ix_custom_cbl_overlap_decisions_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_custom_cbl_overlap_decisions_list ON public.custom_cbl_overlap_decisions USING btree (list_id);


--
-- Name: ix_custom_cbl_overlap_decisions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_custom_cbl_overlap_decisions_user ON public.custom_cbl_overlap_decisions USING btree (user_id);


--
-- Name: ix_custom_cbl_source_link_source_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_custom_cbl_source_link_source_list ON public.custom_cbl_source_links USING btree (cbl_source_list_id);


--
-- Name: ix_delivery_record_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_delivery_record_source ON public.delivery_records USING btree (source_repository);


--
-- Name: ix_delivery_record_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_delivery_record_target ON public.delivery_records USING btree (target_repository);


--
-- Name: ix_dependencies_target_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dependencies_target_issue_id ON public.dependencies USING btree (target_issue_id);


--
-- Name: ix_dependency_group_memberships_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dependency_group_memberships_group_id ON public.dependency_group_memberships USING btree (group_id);


--
-- Name: ix_dependency_group_memberships_group_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dependency_group_memberships_group_order ON public.dependency_group_memberships USING btree (group_id, sequence_order);


--
-- Name: ix_dependency_group_memberships_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dependency_group_memberships_issue_id ON public.dependency_group_memberships USING btree (issue_id);


--
-- Name: ix_dependency_group_memberships_thread_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dependency_group_memberships_thread_id ON public.dependency_group_memberships USING btree (thread_id);


--
-- Name: ix_dependency_groups_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dependency_groups_user_id ON public.dependency_groups USING btree (user_id);


--
-- Name: ix_event_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_session_id ON public.events USING btree (session_id);


--
-- Name: ix_event_session_latest_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_session_latest_action ON public.events USING btree (session_id, "timestamp" DESC, id DESC);


--
-- Name: ix_event_session_type_die_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_session_type_die_after ON public.events USING btree (session_id, type, die_after);


--
-- Name: ix_event_session_type_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_session_type_timestamp ON public.events USING btree (session_id, type, "timestamp");


--
-- Name: ix_event_source_roll_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_source_roll_event_id ON public.events USING btree (source_roll_event_id);


--
-- Name: ix_event_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_timestamp ON public.events USING btree ("timestamp");


--
-- Name: ix_event_type_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_type_issue_id ON public.events USING btree (type, issue_id);


--
-- Name: ix_event_user_timestamp_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_event_user_timestamp_id ON public.events USING btree (user_id, "timestamp" DESC, id DESC);


--
-- Name: ix_events_user_dice_command_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_events_user_dice_command_key ON public.events USING btree (user_id, ((context ->> 'dice_command_key'::text))) WHERE ((context ->> 'dice_command_key'::text) IS NOT NULL);


--
-- Name: ix_external_identity_metadata_jsonb_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_identity_metadata_jsonb_path ON public.external_identities USING gin (((metadata_json)::jsonb) jsonb_path_ops);


--
-- Name: ix_external_identity_provider_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_identity_provider_type ON public.external_identities USING btree (provider, entity_type);


--
-- Name: ix_failed_login_ip_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_failed_login_ip_time ON public.failed_login_attempts USING btree (ip_address, attempted_at);


--
-- Name: ix_failed_login_username_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_failed_login_username_time ON public.failed_login_attempts USING btree (username, attempted_at);


--
-- Name: ix_issue_catalog_issue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_catalog_issue ON public.issues USING btree (catalog_issue_id);


--
-- Name: ix_issue_external_identity_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_external_identity_external_id ON public.issue_external_identity_mappings USING btree (external_identity_id);


--
-- Name: ix_issue_external_identity_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_external_identity_issue_id ON public.issue_external_identity_mappings USING btree (issue_id);


--
-- Name: ix_issue_metadata_correction_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_metadata_correction_created_by ON public.issue_metadata_corrections USING btree (created_by);


--
-- Name: ix_issue_metadata_correction_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_metadata_correction_issue_id ON public.issue_metadata_corrections USING btree (issue_id);


--
-- Name: ix_issue_thread_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_thread_id ON public.issues USING btree (thread_id);


--
-- Name: ix_issue_thread_is_read; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_thread_is_read ON public.issues USING btree (thread_id, status);


--
-- Name: ix_password_reset_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_expires_at ON public.password_reset_tokens USING btree (expires_at);


--
-- Name: ix_password_reset_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_user_id ON public.password_reset_tokens USING btree (user_id);


--
-- Name: ix_perf_metric_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_perf_metric_timestamp ON public.performance_metrics USING btree ("timestamp");


--
-- Name: ix_perf_metric_type_cold; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_perf_metric_type_cold ON public.performance_metrics USING btree (metric_type, cold);


--
-- Name: ix_perf_metrics_cold; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_perf_metrics_cold ON public.performance_metrics USING btree (cold);


--
-- Name: ix_perf_metrics_deployment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_perf_metrics_deployment_id ON public.performance_metrics USING btree (deployment_id);


--
-- Name: ix_perf_metrics_metric_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_perf_metrics_metric_type ON public.performance_metrics USING btree (metric_type);


--
-- Name: ix_reading_plan_dependencies_dependency_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reading_plan_dependencies_dependency_id ON public.reading_plan_dependencies USING btree (dependency_id);


--
-- Name: ix_reading_plan_issues_issue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reading_plan_issues_issue_id ON public.reading_plan_issues USING btree (issue_id);


--
-- Name: ix_reading_plan_issues_plan_issue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reading_plan_issues_plan_issue ON public.reading_plan_issues USING btree (plan_id, issue_id);


--
-- Name: ix_reading_plan_source_placements_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reading_plan_source_placements_plan_id ON public.reading_plan_source_placements USING btree (plan_id);


--
-- Name: ix_reading_plan_source_placements_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reading_plan_source_placements_source_id ON public.reading_plan_source_placements USING btree (plan_source_id);


--
-- Name: ix_reading_plan_sources_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reading_plan_sources_plan_id ON public.reading_plan_sources USING btree (plan_id);


--
-- Name: ix_recommendation_contexts_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_contexts_created_at ON public.recommendation_contexts USING btree (created_at);


--
-- Name: ix_recommendation_contexts_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recommendation_contexts_intent ON public.recommendation_contexts USING btree (intent);


--
-- Name: ix_release_published_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_release_published_order ON public.releases USING btree (status, visibility, released_at, sort_order, id);


--
-- Name: ix_release_sources_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_release_sources_enabled ON public.reading_plan_release_sources USING btree (enabled);


--
-- Name: ix_release_sources_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_release_sources_plan_id ON public.reading_plan_release_sources USING btree (plan_id);


--
-- Name: ix_release_sources_thread_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_release_sources_thread_id ON public.reading_plan_release_sources USING btree (thread_id);


--
-- Name: ix_revoked_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_revoked_tokens_expires_at ON public.revoked_tokens USING btree (expires_at);


--
-- Name: ix_revoked_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_revoked_tokens_user_id ON public.revoked_tokens USING btree (user_id);


--
-- Name: ix_session_ended_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_ended_at ON public.sessions USING btree (ended_at);


--
-- Name: ix_session_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_started_at ON public.sessions USING btree (started_at);


--
-- Name: ix_session_user_ended_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_user_ended_started ON public.sessions USING btree (user_id, ended_at, started_at);


--
-- Name: ix_snapshot_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_snapshot_created_at ON public.snapshots USING btree (created_at);


--
-- Name: ix_snapshot_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_snapshot_event_id ON public.snapshots USING btree (event_id);


--
-- Name: ix_snapshot_session_delta_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_snapshot_session_delta_lookup ON public.snapshots USING btree (session_id, snapshot_kind, schema_version, created_at, id);


--
-- Name: ix_snapshot_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_snapshot_session_id ON public.snapshots USING btree (session_id);


--
-- Name: ix_tag_assignments_tag_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tag_assignments_tag_id ON public.tag_assignments USING btree (tag_id);


--
-- Name: ix_tag_assignments_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tag_assignments_target ON public.tag_assignments USING btree (target_type, target_id);


--
-- Name: ix_tags_normalized_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tags_normalized_name ON public.tags USING btree (normalized_name);


--
-- Name: ix_tags_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tags_owner_user_id ON public.tags USING btree (owner_user_id);


--
-- Name: ix_tags_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tags_scope ON public.tags USING btree (scope);


--
-- Name: ix_taste_signal_user_verdict; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taste_signal_user_verdict ON public.taste_signals USING btree (user_id, user_verdict);


--
-- Name: ix_thread_catalog_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_catalog_series ON public.threads USING btree (catalog_series_id);


--
-- Name: ix_thread_external_series_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_external_series_external_id ON public.thread_external_series_mappings USING btree (external_identity_id);


--
-- Name: ix_thread_external_series_thread_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_external_series_thread_id ON public.thread_external_series_mappings USING btree (thread_id);


--
-- Name: ix_thread_last_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_last_activity ON public.threads USING btree (last_activity_at);


--
-- Name: ix_thread_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_position ON public.threads USING btree (queue_position);


--
-- Name: ix_thread_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_status ON public.threads USING btree (status);


--
-- Name: ix_thread_user_active_queue_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_user_active_queue_position ON public.threads USING btree (user_id, is_blocked, queue_position, id) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_thread_user_completed_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_user_completed_created_id ON public.threads USING btree (user_id, created_at, id) WHERE ((status)::text = 'completed'::text);


--
-- Name: ix_thread_user_completed_title_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_user_completed_title_id ON public.threads USING btree (user_id, title, id) WHERE ((status)::text = 'completed'::text);


--
-- Name: ix_thread_user_status_blocked_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_user_status_blocked_position ON public.threads USING btree (user_id, status, is_blocked, queue_position);


--
-- Name: ix_thread_user_status_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_user_status_position ON public.threads USING btree (user_id, status, queue_position);


--
-- Name: uq_collection_exclusion_owner_issue; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_collection_exclusion_owner_issue ON public.collection_exclusions USING btree (user_id, issue_id) WHERE (issue_id IS NOT NULL);


--
-- Name: uq_collection_exclusion_owner_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_collection_exclusion_owner_thread ON public.collection_exclusions USING btree (user_id, thread_id) WHERE (thread_id IS NOT NULL);


--
-- Name: uq_collection_exclusion_owner_volume; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_collection_exclusion_owner_volume ON public.collection_exclusions USING btree (user_id, provider, external_volume_id) WHERE (external_volume_id IS NOT NULL);


--
-- Name: uq_tag_assignments_target; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tag_assignments_target ON public.tag_assignments USING btree (tag_id, target_type, target_id);


--
-- Name: uq_tags_global_names; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tags_global_names ON public.tags USING btree (normalized_name) WHERE ((scope)::text = 'global'::text);


--
-- Name: uq_tags_private_names; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tags_private_names ON public.tags USING btree (owner_user_id, normalized_name) WHERE ((scope)::text = 'private'::text);


--
-- Name: events trg_assign_event_owner; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_assign_event_owner BEFORE INSERT OR UPDATE OF user_id, session_id, thread_id, issue_id, selected_thread_id, source_roll_event_id ON public.events FOR EACH ROW EXECUTE FUNCTION public.assign_event_owner();


--
-- Name: catalog_commit_receipts catalog_commit_receipts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_commit_receipts
    ADD CONSTRAINT catalog_commit_receipts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: catalog_issues catalog_issues_canonical_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_issues
    ADD CONSTRAINT catalog_issues_canonical_external_identity_id_fkey FOREIGN KEY (canonical_external_identity_id) REFERENCES public.external_identities(id) ON DELETE RESTRICT;


--
-- Name: catalog_issues catalog_issues_catalog_series_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_issues
    ADD CONSTRAINT catalog_issues_catalog_series_id_fkey FOREIGN KEY (catalog_series_id) REFERENCES public.catalog_series(id) ON DELETE SET NULL;


--
-- Name: catalog_series catalog_series_canonical_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_series
    ADD CONSTRAINT catalog_series_canonical_external_identity_id_fkey FOREIGN KEY (canonical_external_identity_id) REFERENCES public.external_identities(id) ON DELETE RESTRICT;


--
-- Name: cbl_adoption_receipts cbl_adoption_receipts_cbl_source_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_adoption_receipts
    ADD CONSTRAINT cbl_adoption_receipts_cbl_source_list_id_fkey FOREIGN KEY (cbl_source_list_id) REFERENCES public.cbl_source_lists(id) ON DELETE CASCADE;


--
-- Name: cbl_adoption_receipts cbl_adoption_receipts_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_adoption_receipts
    ADD CONSTRAINT cbl_adoption_receipts_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.continuity_plans(id) ON DELETE CASCADE;


--
-- Name: cbl_adoption_receipts cbl_adoption_receipts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_adoption_receipts
    ADD CONSTRAINT cbl_adoption_receipts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cbl_source_entries cbl_source_entries_external_issue_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_entries
    ADD CONSTRAINT cbl_source_entries_external_issue_identity_id_fkey FOREIGN KEY (external_issue_identity_id) REFERENCES public.external_identities(id) ON DELETE SET NULL;


--
-- Name: cbl_source_entries cbl_source_entries_external_series_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_entries
    ADD CONSTRAINT cbl_source_entries_external_series_identity_id_fkey FOREIGN KEY (external_series_identity_id) REFERENCES public.external_identities(id) ON DELETE SET NULL;


--
-- Name: cbl_source_entries cbl_source_entries_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_entries
    ADD CONSTRAINT cbl_source_entries_list_id_fkey FOREIGN KEY (list_id) REFERENCES public.cbl_source_lists(id) ON DELETE CASCADE;


--
-- Name: cbl_source_lists cbl_source_lists_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cbl_source_lists
    ADD CONSTRAINT cbl_source_lists_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.cbl_sources(id) ON DELETE CASCADE;


--
-- Name: collection_exclusions collection_exclusions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_exclusions
    ADD CONSTRAINT collection_exclusions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: comicvine_metadata_refresh_requests comicvine_metadata_refresh_requests_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comicvine_metadata_refresh_requests
    ADD CONSTRAINT comicvine_metadata_refresh_requests_external_identity_id_fkey FOREIGN KEY (external_identity_id) REFERENCES public.external_identities(id) ON DELETE CASCADE;


--
-- Name: continuity_plans continuity_plans_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_plans
    ADD CONSTRAINT continuity_plans_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: continuity_rule_selected_members continuity_rule_selected_members_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rule_selected_members
    ADD CONSTRAINT continuity_rule_selected_members_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: continuity_rule_selected_members continuity_rule_selected_members_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rule_selected_members
    ADD CONSTRAINT continuity_rule_selected_members_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.continuity_rules(id) ON DELETE CASCADE;


--
-- Name: continuity_rules continuity_rules_checkpoint_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules
    ADD CONSTRAINT continuity_rules_checkpoint_issue_id_fkey FOREIGN KEY (checkpoint_issue_id) REFERENCES public.issues(id) ON DELETE RESTRICT;


--
-- Name: continuity_rules continuity_rules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules
    ADD CONSTRAINT continuity_rules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_entries custom_cbl_entries_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_entries
    ADD CONSTRAINT custom_cbl_entries_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_entries custom_cbl_entries_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_entries
    ADD CONSTRAINT custom_cbl_entries_list_id_fkey FOREIGN KEY (list_id) REFERENCES public.custom_cbl_lists(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_lists custom_cbl_lists_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_lists
    ADD CONSTRAINT custom_cbl_lists_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_overlap_decisions custom_cbl_overlap_decisions_continuing_external_identity__fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions
    ADD CONSTRAINT custom_cbl_overlap_decisions_continuing_external_identity__fkey FOREIGN KEY (continuing_external_identity_id) REFERENCES public.external_identities(id) ON DELETE RESTRICT;


--
-- Name: custom_cbl_overlap_decisions custom_cbl_overlap_decisions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions
    ADD CONSTRAINT custom_cbl_overlap_decisions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_overlap_decisions custom_cbl_overlap_decisions_waiting_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions
    ADD CONSTRAINT custom_cbl_overlap_decisions_waiting_external_identity_id_fkey FOREIGN KEY (waiting_external_identity_id) REFERENCES public.external_identities(id) ON DELETE RESTRICT;


--
-- Name: custom_cbl_source_links custom_cbl_source_links_cbl_source_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links
    ADD CONSTRAINT custom_cbl_source_links_cbl_source_list_id_fkey FOREIGN KEY (cbl_source_list_id) REFERENCES public.cbl_source_lists(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_source_links custom_cbl_source_links_custom_cbl_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links
    ADD CONSTRAINT custom_cbl_source_links_custom_cbl_list_id_fkey FOREIGN KEY (custom_cbl_list_id) REFERENCES public.custom_cbl_lists(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_source_links custom_cbl_source_links_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_source_links
    ADD CONSTRAINT custom_cbl_source_links_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: dependency_group_memberships dependency_group_memberships_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships
    ADD CONSTRAINT dependency_group_memberships_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.dependency_groups(id) ON DELETE CASCADE;


--
-- Name: dependency_group_memberships dependency_group_memberships_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships
    ADD CONSTRAINT dependency_group_memberships_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: dependency_group_memberships dependency_group_memberships_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_group_memberships
    ADD CONSTRAINT dependency_group_memberships_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id) ON DELETE CASCADE;


--
-- Name: dependency_groups dependency_groups_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency_groups
    ADD CONSTRAINT dependency_groups_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: events events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;


--
-- Name: events events_source_roll_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_source_roll_event_id_fkey FOREIGN KEY (source_roll_event_id) REFERENCES public.events(id) ON DELETE SET NULL;


--
-- Name: events events_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id) ON DELETE CASCADE;


--
-- Name: continuity_rules fk_continuity_rules_legacy_dependency_id_dependencies; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.continuity_rules
    ADD CONSTRAINT fk_continuity_rules_legacy_dependency_id_dependencies FOREIGN KEY (legacy_dependency_id) REFERENCES public.dependencies(id) ON DELETE CASCADE;


--
-- Name: custom_cbl_overlap_decisions fk_custom_cbl_overlap_decision_owner_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custom_cbl_overlap_decisions
    ADD CONSTRAINT fk_custom_cbl_overlap_decision_owner_list FOREIGN KEY (list_id, user_id) REFERENCES public.custom_cbl_lists(id, user_id) ON DELETE CASCADE;


--
-- Name: dependencies fk_dependencies_source_issue_id_issues; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependencies
    ADD CONSTRAINT fk_dependencies_source_issue_id_issues FOREIGN KEY (source_issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: dependencies fk_dependencies_target_issue_id_issues; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependencies
    ADD CONSTRAINT fk_dependencies_target_issue_id_issues FOREIGN KEY (target_issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: events fk_events_issue_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT fk_events_issue_id FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE SET NULL;


--
-- Name: events fk_events_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT fk_events_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: github_issue_submission_limits fk_github_issue_submission_limits_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_issue_submission_limits
    ADD CONSTRAINT fk_github_issue_submission_limits_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: recommendation_contexts fk_recommendation_contexts_event_id_events; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendation_contexts
    ADD CONSTRAINT fk_recommendation_contexts_event_id_events FOREIGN KEY (event_id) REFERENCES public.events(id) ON DELETE CASCADE;


--
-- Name: revoked_tokens fk_revoked_tokens_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revoked_tokens
    ADD CONSTRAINT fk_revoked_tokens_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: sessions fk_sessions_pending_issue_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_pending_issue_id FOREIGN KEY (pending_issue_id) REFERENCES public.issues(id) ON DELETE SET NULL;


--
-- Name: taste_signals fk_taste_signal_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taste_signals
    ADD CONSTRAINT fk_taste_signal_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: threads fk_threads_frontier_same_thread; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT fk_threads_frontier_same_thread FOREIGN KEY (id, next_unread_issue_id) REFERENCES public.issues(thread_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: threads fk_threads_next_unread_issue_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT fk_threads_next_unread_issue_id FOREIGN KEY (next_unread_issue_id) REFERENCES public.issues(id) ON DELETE SET NULL;


--
-- Name: user_preferences fk_user_preferences_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT fk_user_preferences_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: issue_external_identity_mappings issue_external_identity_mappings_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_external_identity_mappings
    ADD CONSTRAINT issue_external_identity_mappings_external_identity_id_fkey FOREIGN KEY (external_identity_id) REFERENCES public.external_identities(id) ON DELETE CASCADE;


--
-- Name: issue_external_identity_mappings issue_external_identity_mappings_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_external_identity_mappings
    ADD CONSTRAINT issue_external_identity_mappings_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: issue_metadata_corrections issue_metadata_corrections_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_metadata_corrections
    ADD CONSTRAINT issue_metadata_corrections_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: issue_metadata_corrections issue_metadata_corrections_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_metadata_corrections
    ADD CONSTRAINT issue_metadata_corrections_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: issues issues_catalog_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues
    ADD CONSTRAINT issues_catalog_issue_id_fkey FOREIGN KEY (catalog_issue_id) REFERENCES public.catalog_issues(id) ON DELETE SET NULL;


--
-- Name: issues issues_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issues
    ADD CONSTRAINT issues_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id) ON DELETE CASCADE;


--
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: performance_metrics performance_metrics_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.performance_metrics
    ADD CONSTRAINT performance_metrics_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: reading_order_items reading_order_items_reading_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_order_items
    ADD CONSTRAINT reading_order_items_reading_order_id_fkey FOREIGN KEY (reading_order_id) REFERENCES public.reading_orders(id);


--
-- Name: reading_order_items reading_order_items_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_order_items
    ADD CONSTRAINT reading_order_items_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id);


--
-- Name: reading_orders reading_orders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_orders
    ADD CONSTRAINT reading_orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: reading_plan_dependencies reading_plan_dependencies_dependency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_dependencies
    ADD CONSTRAINT reading_plan_dependencies_dependency_id_fkey FOREIGN KEY (dependency_id) REFERENCES public.dependencies(id) ON DELETE CASCADE;


--
-- Name: reading_plan_dependencies reading_plan_dependencies_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_dependencies
    ADD CONSTRAINT reading_plan_dependencies_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.continuity_plans(id) ON DELETE CASCADE;


--
-- Name: reading_plan_issues reading_plan_issues_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_issues
    ADD CONSTRAINT reading_plan_issues_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;


--
-- Name: reading_plan_issues reading_plan_issues_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_issues
    ADD CONSTRAINT reading_plan_issues_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.continuity_plans(id) ON DELETE CASCADE;


--
-- Name: reading_plan_release_sources reading_plan_release_sources_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_release_sources
    ADD CONSTRAINT reading_plan_release_sources_external_identity_id_fkey FOREIGN KEY (external_identity_id) REFERENCES public.external_identities(id) ON DELETE CASCADE;


--
-- Name: reading_plan_release_sources reading_plan_release_sources_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_release_sources
    ADD CONSTRAINT reading_plan_release_sources_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.continuity_plans(id) ON DELETE CASCADE;


--
-- Name: reading_plan_release_sources reading_plan_release_sources_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_release_sources
    ADD CONSTRAINT reading_plan_release_sources_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id) ON DELETE CASCADE;


--
-- Name: reading_plan_source_placements reading_plan_source_placements_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_source_placements
    ADD CONSTRAINT reading_plan_source_placements_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.continuity_plans(id) ON DELETE CASCADE;


--
-- Name: reading_plan_source_placements reading_plan_source_placements_plan_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_source_placements
    ADD CONSTRAINT reading_plan_source_placements_plan_source_id_fkey FOREIGN KEY (plan_source_id) REFERENCES public.reading_plan_sources(id) ON DELETE CASCADE;


--
-- Name: reading_plan_sources reading_plan_sources_cbl_source_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_sources
    ADD CONSTRAINT reading_plan_sources_cbl_source_list_id_fkey FOREIGN KEY (cbl_source_list_id) REFERENCES public.cbl_source_lists(id) ON DELETE SET NULL;


--
-- Name: reading_plan_sources reading_plan_sources_custom_cbl_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_sources
    ADD CONSTRAINT reading_plan_sources_custom_cbl_list_id_fkey FOREIGN KEY (custom_cbl_list_id) REFERENCES public.custom_cbl_lists(id) ON DELETE SET NULL;


--
-- Name: reading_plan_sources reading_plan_sources_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reading_plan_sources
    ADD CONSTRAINT reading_plan_sources_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.continuity_plans(id) ON DELETE CASCADE;


--
-- Name: sessions sessions_pending_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pending_thread_id_fkey FOREIGN KEY (pending_thread_id) REFERENCES public.threads(id) ON DELETE SET NULL;


--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: snapshots snapshots_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.events(id) ON DELETE CASCADE;


--
-- Name: snapshots snapshots_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: tag_assignments tag_assignments_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments
    ADD CONSTRAINT tag_assignments_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id) ON DELETE CASCADE;


--
-- Name: tags tags_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: thread_external_series_mappings thread_external_series_mappings_external_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_external_series_mappings
    ADD CONSTRAINT thread_external_series_mappings_external_identity_id_fkey FOREIGN KEY (external_identity_id) REFERENCES public.external_identities(id) ON DELETE CASCADE;


--
-- Name: thread_external_series_mappings thread_external_series_mappings_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_external_series_mappings
    ADD CONSTRAINT thread_external_series_mappings_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id) ON DELETE CASCADE;


--
-- Name: threads threads_catalog_series_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT threads_catalog_series_id_fkey FOREIGN KEY (catalog_series_id) REFERENCES public.catalog_series(id) ON DELETE SET NULL;


--
-- Name: threads threads_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT threads_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--
