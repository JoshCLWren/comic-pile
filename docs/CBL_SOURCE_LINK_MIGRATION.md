# Reader-owned CBL source links

> **Status: historical implementation note.** Alembic apply/downgrade commands are
> retired; the schema is now in the refinery baseline and later migrations are
> append-only Rust SQL. See [DATABASE_SAVE_LOAD.md](DATABASE_SAVE_LOAD.md).
<!-- docs-path-check: historical -->

PR #4052 implements #4021's source-link scaffolding. Selected-comic persistence
and the adoption API cutover belong to the dependent #4022.

Apply `q7c100000001` after `r40180000001` through the normal reviewed Alembic
migration process. This additive revision creates only `custom_cbl_source_links`
and its constraints/index; it does not rewrite Reading Plans, history, source
catalog entries, or existing custom lists. It does not execute production import,
backfill, or reader repair. The migration review gate remains applicable.

Rollback with `alembic downgrade r40180000001` only when no later revisions depend
on this revision. Downgrade removes source links and their captured provenance;
it leaves reader-owned lists, source facts and existing plan history intact.
Recreating links after downgrade must be reviewed because the old mapping is lost.

`tests/test_custom_cbl_source_link.py` exercises actual PostgreSQL transactions: <!-- docs-path-check: ignore -->
repeat/reopen, reader isolation, caller rollback, overlapping first adds, and
same-name source/manual-list collisions with preserved existing plan data.
