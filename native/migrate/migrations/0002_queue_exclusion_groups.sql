-- Migration 0002: queue exclusion groups for bulk queue removal provenance.
-- Mirrors Alembic s54350000001 (revises c44050000002).

CREATE TABLE public.queue_exclusion_groups (
    id integer NOT NULL,
    user_id integer NOT NULL,
    source_kind character varying(32) NOT NULL,
    source_id integer NOT NULL,
    source_name character varying(500) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_queue_exclusion_groups_source_kind CHECK (((source_kind)::text = ANY ((ARRAY['reading_list'::character varying, 'reading_plan'::character varying, 'crossover'::character varying])::text[])))
);

CREATE SEQUENCE public.queue_exclusion_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.queue_exclusion_groups_id_seq OWNED BY public.queue_exclusion_groups.id;

ALTER TABLE ONLY public.queue_exclusion_groups ALTER COLUMN id SET DEFAULT nextval('public.queue_exclusion_groups_id_seq'::regclass);

ALTER TABLE ONLY public.queue_exclusion_groups
    ADD CONSTRAINT queue_exclusion_groups_pkey PRIMARY KEY (id);

CREATE INDEX ix_queue_exclusion_groups_user_id ON public.queue_exclusion_groups USING btree (user_id);

ALTER TABLE ONLY public.queue_exclusion_groups
    ADD CONSTRAINT queue_exclusion_groups_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE public.threads ADD COLUMN queue_exclusion_group_id integer;

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT fk_threads_queue_exclusion_group_id FOREIGN KEY (queue_exclusion_group_id) REFERENCES public.queue_exclusion_groups(id) ON DELETE SET NULL;

CREATE INDEX ix_threads_queue_exclusion_group_id ON public.threads USING btree (queue_exclusion_group_id);
