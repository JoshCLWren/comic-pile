-- Migration 0003: preserve release subscriptions while targeting authoritative Reading Lists.
-- Non-destructive: add nullable list association; backfill only unambiguous same-owner provenance.
-- Ambiguous or unpaired records remain NULL and require explicit reassociation.

ALTER TABLE public.reading_plan_release_sources
    ADD COLUMN custom_cbl_list_id integer;

ALTER TABLE ONLY public.reading_plan_release_sources
    ADD CONSTRAINT reading_plan_release_sources_custom_cbl_list_id_fkey
    FOREIGN KEY (custom_cbl_list_id) REFERENCES public.custom_cbl_lists(id) ON DELETE SET NULL;

CREATE INDEX ix_release_sources_custom_cbl_list_id
    ON public.reading_plan_release_sources (custom_cbl_list_id);

-- Backfill unambiguous provenance: only plans with exactly one distinct same-owner
-- linked custom_cbl_list_id among reading_plan_sources are eligible.
WITH plan_lists AS (
    SELECT src.plan_id,
           count(DISTINCT src.custom_cbl_list_id) AS distinct_lists
    FROM public.reading_plan_sources src
    WHERE src.custom_cbl_list_id IS NOT NULL
    GROUP BY src.plan_id
),
single_list AS (
    SELECT src.plan_id, min(src.custom_cbl_list_id) AS list_id
    FROM public.reading_plan_sources src
    JOIN plan_lists pl ON pl.plan_id = src.plan_id AND pl.distinct_lists = 1
    JOIN public.custom_cbl_lists l ON l.id = src.custom_cbl_list_id
    JOIN public.continuity_plans cp ON cp.id = src.plan_id AND cp.user_id = l.user_id
    WHERE src.custom_cbl_list_id IS NOT NULL
    GROUP BY src.plan_id
)
UPDATE public.reading_plan_release_sources rps
SET custom_cbl_list_id = sl.list_id
FROM single_list sl
JOIN public.continuity_plans cp ON cp.id = sl.plan_id
WHERE rps.plan_id = sl.plan_id
  AND rps.custom_cbl_list_id IS NULL;
