-- Retire the Thread.format concept (#3035).
--
-- The column is deliberately retained: dropping it or converting its stored
-- values into tags is destructive production data loss and requires an explicit
-- owner decision. This forward migration only makes the column inert so no
-- writer needs to supply it and no reader depends on it. Existing rows keep
-- their historical values until the owner decides what to do with them.
--
-- Refinery embeds migrations in path order: a top-level V10 file would sort
-- before V1 and break the embedded-version-order guard. The `future/` directory
-- keeps this migration embedded after V9; refinery still applies by version.
ALTER TABLE threads ALTER COLUMN format DROP NOT NULL;
ALTER TABLE threads ALTER COLUMN format SET DEFAULT 'Comic';
