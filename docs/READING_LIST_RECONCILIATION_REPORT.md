# Read-only Custom CBL and Reading Plan reconciliation

Option E issue #3660 supplies a census, not a conversion decision. Run from the
repository root with an explicit PostgreSQL asyncpg URL and owner ID:

```bash
uv run python -m scripts.report_custom_cbl_plan_reconciliation \
  --database-url "$CENSUS_DATABASE_URL" --user-id 1 > reconciliation.json
```

Add `--summary` for readable project counts and detailed discrepancy evidence.
The report uses a single repeatable-read, read-only transaction. It never applies
migrations, repairs frontiers, changes reader state, or selects a winning source.
The database must already include the additive Option E list-intent migration.
Treat the output as private reader data; do not publish it in public issue comments.

Pairing requires the durable `reading_plan_sources.custom_cbl_list_id` link.
Matching names and timestamps cannot establish authority. Unpaired projects and
many-to-many source links remain unresolved. JSON includes stable list, entry,
plan, occurrence and source identities, memberships in both directions, position
and lane conflicts, duplicates, raw plan nodes, provenance, checkpoint and
optional/skip evidence, and current list mode/gate/skip fields. Skipped entries
remain in the census. Unknown legacy metadata remains evidence for review.

The Absolute 105/76, Julix 466/464 and JSA 57/58 scenarios are regression fixtures,
not production counts. Producing a report does not authorize conversion; reviewed
manifests and fresh owner approval belong to later Option E issues.
