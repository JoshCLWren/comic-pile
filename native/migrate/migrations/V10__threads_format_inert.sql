-- Retire the Thread.format concept (#3035).
--
-- The column is deliberately retained: dropping it or converting its stored
-- values into tags is destructive production data loss and requires an explicit
-- owner decision. This forward migration only makes the column inert so no
-- writer needs to supply it and no reader depends on it. Existing rows keep
-- their historical values until the owner decides what to do with them.
ALTER TABLE threads ALTER COLUMN format DROP NOT NULL;
ALTER TABLE threads ALTER COLUMN format SET DEFAULT 'Comic';
