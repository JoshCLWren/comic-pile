-- #4022: make the canonical Reading List identity source-linked and owner-scoped.
--
-- A CBL Add/Update is identified by (reader, stable source list), never by a
-- display name or by a legacy continuity Plan. The source link is written in
-- the same transaction as the list entries, so a retry of the same source
-- updates the same list and a changed source revision/list version is rejected
-- atomically before any row is touched.
ALTER TABLE public.custom_cbl_source_links
    ADD COLUMN IF NOT EXISTS list_version integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS selections_json jsonb,
    ADD COLUMN IF NOT EXISTS overlap_decisions_json jsonb;
