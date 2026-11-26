-- #4653: guided canonical duplicate-comic reconciliation
ALTER TABLE public.issues
    ADD COLUMN IF NOT EXISTS merged_into_issue_id integer REFERENCES public.issues(id),
    ADD COLUMN IF NOT EXISTS merged_at timestamp with time zone;

CREATE INDEX IF NOT EXISTS idx_issues_merged_into_issue_id
    ON public.issues(merged_into_issue_id)
    WHERE merged_into_issue_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.issue_duplicate_reconciliations (
    id bigserial PRIMARY KEY,
    user_id integer NOT NULL REFERENCES public.users(id),
    canonical_issue_id integer NOT NULL REFERENCES public.issues(id),
    duplicate_issue_ids integer[] NOT NULL,
    preview_token text NOT NULL,
    applied_at timestamp with time zone NOT NULL DEFAULT now(),
    undone_at timestamp with time zone,
    undo_snapshot jsonb,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_issue_duplicate_reconciliations_user
    ON public.issue_duplicate_reconciliations(user_id, applied_at DESC);
