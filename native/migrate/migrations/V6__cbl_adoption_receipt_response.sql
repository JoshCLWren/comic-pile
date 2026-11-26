-- #5522: store authoritative CBL adoption commit result for replay/recovery.
ALTER TABLE public.cbl_adoption_receipts
    ADD COLUMN IF NOT EXISTS response_json jsonb;
