-- #4026: one source-aware, owner-scoped CBL replacement commits against an
-- explicitly selected canonical Reading List and leaves a list-only snapshot
-- that can be restored without touching read/rating/collection history.
--
-- The snapshot is deliberately narrow (name/description/mode, ordered entries
-- with their gating intents, and overlap decisions). It never stores Issue,
-- session, event or collection rows, so an Undo cannot reverse a later read.
CREATE TABLE IF NOT EXISTS public.custom_cbl_replacement_snapshots (
    id integer NOT NULL,
    user_id integer NOT NULL,
    list_id integer NOT NULL,
    source_list_id integer NOT NULL,
    source_revision_sha character varying(64) NOT NULL,
    source_content_hash character varying(64) NOT NULL,
    idempotency_key character varying(200),
    list_version_before integer NOT NULL,
    list_version_after integer NOT NULL,
    before_state_json jsonb NOT NULL,
    after_state_json jsonb NOT NULL,
    response_json jsonb,
    -- Undo has its own key/response: reusing the commit key would collide with
    -- the commit replay constraint and could never represent an undo retry.
    undo_idempotency_key character varying(200),
    undo_response_json jsonb,
    undone_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT custom_cbl_replacement_snapshots_pkey PRIMARY KEY (id)
);

CREATE SEQUENCE IF NOT EXISTS public.custom_cbl_replacement_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.custom_cbl_replacement_snapshots_id_seq
    OWNED BY public.custom_cbl_replacement_snapshots.id;

ALTER TABLE ONLY public.custom_cbl_replacement_snapshots
    ALTER COLUMN id SET DEFAULT nextval('public.custom_cbl_replacement_snapshots_id_seq'::regclass);

-- Reader-row locking serializes a user's writes; this constraint is the
-- durable backstop that makes a retried/concurrent commit replay one snapshot
-- instead of creating a second replacement for the same request.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cbl_replacement_idempotency
    ON public.custom_cbl_replacement_snapshots (user_id, list_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- A retried Undo replays its stored response after the list version has already
-- advanced, instead of failing the stale-version guard.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cbl_replacement_undo_idempotency
    ON public.custom_cbl_replacement_snapshots (user_id, list_id, undo_idempotency_key)
    WHERE undo_idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_cbl_replacement_snapshot_lookup
    ON public.custom_cbl_replacement_snapshots (user_id, list_id, id DESC);
