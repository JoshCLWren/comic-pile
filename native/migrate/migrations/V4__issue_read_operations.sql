-- Migration V4: track bulk issue read/unread operations for review and undo (#4655).
-- Each operation records the exact affected issues and their previous read state so
-- an undo can write compensating events without reverting unrelated later changes.

CREATE TABLE public.issue_read_operations (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    operation_type character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    undone_at timestamp with time zone,
    CONSTRAINT ck_issue_read_operations_type CHECK (((operation_type)::text = ANY ((ARRAY['bulk_mark_read'::character varying, 'bulk_mark_unread'::character varying])::text[])))
);

CREATE SEQUENCE public.issue_read_operations_id_seq
    AS bigint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.issue_read_operations_id_seq OWNED BY public.issue_read_operations.id;
ALTER TABLE ONLY public.issue_read_operations ALTER COLUMN id SET DEFAULT nextval('public.issue_read_operations_id_seq'::regclass);
ALTER TABLE ONLY public.issue_read_operations ADD CONSTRAINT issue_read_operations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.issue_read_operations ADD CONSTRAINT issue_read_operations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
CREATE INDEX ix_issue_read_operations_user_created ON public.issue_read_operations USING btree (user_id, created_at DESC, id DESC);

CREATE TABLE public.issue_read_operation_items (
    id bigint NOT NULL,
    operation_id bigint NOT NULL,
    issue_id integer NOT NULL,
    thread_id integer NOT NULL,
    issue_number character varying(50) NOT NULL,
    previous_status character varying(20) NOT NULL,
    previous_read_at timestamp with time zone,
    CONSTRAINT ck_issue_read_operation_items_previous_status CHECK (((previous_status)::text = ANY ((ARRAY['read'::character varying, 'unread'::character varying])::text[])))
);

CREATE SEQUENCE public.issue_read_operation_items_id_seq
    AS bigint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.issue_read_operation_items_id_seq OWNED BY public.issue_read_operation_items.id;
ALTER TABLE ONLY public.issue_read_operation_items ALTER COLUMN id SET DEFAULT nextval('public.issue_read_operation_items_id_seq'::regclass);
ALTER TABLE ONLY public.issue_read_operation_items ADD CONSTRAINT issue_read_operation_items_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.issue_read_operation_items ADD CONSTRAINT issue_read_operation_items_operation_id_fkey FOREIGN KEY (operation_id) REFERENCES public.issue_read_operations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.issue_read_operation_items ADD CONSTRAINT issue_read_operation_items_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.issue_read_operation_items ADD CONSTRAINT issue_read_operation_items_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.threads(id) ON DELETE CASCADE;
CREATE INDEX ix_issue_read_operation_items_operation_id ON public.issue_read_operation_items USING btree (operation_id);
CREATE INDEX ix_issue_read_operation_items_issue_id ON public.issue_read_operation_items USING btree (issue_id);
