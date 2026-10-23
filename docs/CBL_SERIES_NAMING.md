# Names for newly materialized CBL series

CBL adoption resolves an owned series by its confirmed external volume identity. Its display title is not its identity, so a retry or another issue from the same volume reuses the existing series even if the reader renamed it.

A newly created confirmed series uses `CBL: <source series> (<volume year>)` when the source has a year. If that title is already in use by the same reader, a readable `(run 2)`, `(run 3)`, etc. suffix distinguishes the new volume. Unknown-year series use the same collision rule without inventing a year or displaying internal identity numbers. Long source names are shortened to fit the 200-character title limit while preserving the year/run suffix.

Materialization holds the reader lock throughout title selection and creation. Collision checks are owner-scoped, so another reader's titles never affect a new series name. Existing mapped series and their reader-owned titles are preserved; this change does not rename historical imports or repair production data.

PostgreSQL regressions live in `tests/test_cbl_series_naming.py` and exercise distinct years, same-year runs, unknown years, exact-identity retries, reader renames, long names, and ownership isolation. Existing adoption retry/concurrency tests cover the surrounding transaction.
