-- Keep story-local and overall numbering on the same owned physical issue.
-- identity_version optimistic-locks atomic alias/provider-identity edits.
ALTER TABLE public.issues
    ADD COLUMN overall_issue_number character varying(50),
    ADD COLUMN identity_version bigint NOT NULL DEFAULT 1;

ALTER TABLE public.issues
    ADD CONSTRAINT ck_issues_identity_version_positive CHECK (identity_version > 0);

CREATE INDEX idx_issues_thread_overall_number
    ON public.issues (thread_id, overall_issue_number)
    WHERE overall_issue_number IS NOT NULL;
