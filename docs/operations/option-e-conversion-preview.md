# Option E conversion preview and rollback rehearsal

Issue #3675 supplies a planner only. Production execution and list activation remain
manual-only under #3676 and require approval of a fresh exact preview.

Run from the repository root with the project Python environment:

```bash
uv run python -m scripts.plan_option_e_conversion \
  --database-url "$OPTION_E_PREFLIGHT_DATABASE_URL" --user-id 1 \
  --intent /private/reviewed-intent.json --mode preflight
```

Preflight uses a PostgreSQL-enforced read-only, repeatable-read transaction. Use a
read-only database credential. The command requires an explicit asyncpg URL and
never falls back to application environment credentials. Keep URLs and generated
artifacts private: reversible receipts include original provenance and notes.

To obtain the initial fingerprint, provide `{"source_fingerprint":"unreviewed"}`.
The refused stale-snapshot result includes the current `source_fingerprint`; copy
that value into a reviewed intent document after consulting the census. Every list
requires an explicit mode. Historical prerequisites with unknown classification
require an explicit decision; omission does not approve them.

An intent document has this shape (IDs below are illustrative):

```json
{
  "source_fingerprint": "sha256 from the current read-only snapshot",
  "lists": [{
    "list_id": 5,
    "mode": "loose",
    "gates": [[101, "hold"]],
    "skipped_issue_ids": [],
    "acknowledged_discrepancies": [{"issue_id": 102, "kind": "plan_only"}]
  }],
  "prerequisites": [{
    "dependency_id": 7,
    "action": "convert",
    "classification": "A",
    "provenance": "Reviewed stable reader requirement"
  }],
  "exclusions": [{"issue_id": 103}],
  "frontier_repairs": [{"thread_id": 9, "derived_issue_id": 104}]
}
```

Gate updates are partial; omitted gates and existing skips remain. Acknowledging a
plan-only entry preserves the current list; it does not adopt or discard Issues.
Resolve list membership separately through reviewed authoring before planning if
that is not the desired result. No timestamps, titles, annual labels or public
sources choose a winner. Multi-lane paired-plan evidence fails closed. Unpaired legacy plan IDs remain
fingerprinted audit evidence in the manifest counts; they do not block current
Reading List or natural-series execution, including readers without lists (#3676).
External-volume exclusions additionally require a provider, external volume ID and
exact `resolved_issue_ids`; the CLI checks those against current confirmed identity
mappings. Thread and Issue targets must belong to the reader.

For an explicitly local PostgreSQL database, the same intent can be rehearsed:

```bash
uv run python -m scripts.plan_option_e_conversion \
  --database-url "$OPTION_E_LOCAL_DATABASE_URL" --user-id 1 \
  --intent /private/reviewed-intent.json --mode rehearse --acknowledge-rollback
```

Rehearsal flushes proposed changes, reloads the shared evaluator inputs, compares
observed eligibility with the manifest, and rolls back even on errors. Remote hosts
are refused. There is no apply or commit command. Rollback rehearsals may consume
PostgreSQL sequence values; use a disposable local database. No Neon clone is used.
A valid manifest is a planning artifact, never production authorization. Inspect
`valid`, `refusals` and `rehearsal.matches_manifest`; a printed artifact alone is
not success. `--receipt-out` exports the reversible before-image plan separately.
