-- Story-arc/overall issue-number alias for one physical comic (#4652).
-- Authored issue_number stays the reader-facing label; this optional alias
-- records the alternate numbering (overall vs story arc) without renumbering.
ALTER TABLE public.issues
    ADD COLUMN IF NOT EXISTS issue_number_alias character varying(50);
