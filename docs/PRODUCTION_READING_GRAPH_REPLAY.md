# Production reading-graph golden replay

This fixture is a **read-only snapshot of the actual production reader's Option E inputs**, not a synthetic subset or a dump of current Roll results.

## Artifacts

- scripts/export_prod_reading_graph.py executes one read-only repeatable-read transaction. No modifications, uploads or staging tables in production.
- tests/fixtures/production_reading_graph_v1.json is a compact, versioned anonymous fixture: current real Threads, positions, statuses, queuedness, ordered list entries, gate/skip flags, reader prerequisites, historical evidence, exclusions, and confirmed Comic Vine volume mappings.
- tests/fixtures/production_reading_expectations_v1.json is **independently specified reader intent**. It is never produced by Roll or the exporter.
- tests/test_production_reading_graph.py loads rows with their actual issue and Thread identifiers into the existing **isolated PostgreSQL** test transaction, then exercises eligibility, Queue/Roll, rating, and future-state transitions.

Compact fixture arrays are laid out as follows:

| Key | Column order |
| --- | --- |
| threads | id, title, format, issues_remaining, total_issues, next_unread_issue_id, queue_position, status, is_blocked, queue_position_is_manual, queue_order_key |
| issues | id, thread_id, issue_number, position, status |
| lists | id, name, mode |
| entries | id, list_id, issue_id, position, gate, skipped, is_checkpoint, checkpoint_target_issue_ids |
| dependencies | id, source_issue_id, target_issue_id, origin, classification, redacted evidence kind |
| exclusions | id, provider, external_volume_id, thread_id, issue_id |
| overlaps | id, list_id, continuing_external_identity_id, waiting_external_identity_id |
| identities | id, provider, entity_type, external_id |
| thread_identity_mappings | id, thread_id, external_identity_id, status |
| catalog_series | id, canonical_external_identity_id |
| catalog_issues | id, canonical_external_identity_id, catalog_series_id |

No original reader ID, email, credentials, free-form text notes, rating or event history is retained. The test creates its own dynamically assigned user ID. Comic/Reading List titles are retained as publicly meaningful labels.

The inert generated legacy edges (origin NULL and generated cbl-order notes) are not imported: they are **74,246** historical entries, not execution rules. Their stable count and ordered MD5 fingerprint are kept to detect changes without making the checked-in fixture thousands of lines larger. Converted and documented legacy edges stay available as *evidence*, never promoted into reader prerequisites. Reader-owned requirements retain their execution semantics.

## Re-export / review

From the repository root, with a **read-only** PostgreSQL connection in DATABASE_URL:

~~~bash
uv run python scripts/export_prod_reading_graph.py --reader-id "$READING_FIXTURE_USER_ID" --check
# To propose a deliberate new version:
uv run python scripts/export_prod_reading_graph.py --reader-id "$READING_FIXTURE_USER_ID"
git diff -- tests/fixtures/production_reading_graph_v1.json
~~~

Both modes enforce SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY. Do not store connection strings in the repository. Use the restored local database for test runs, not production. Running the tests requires a test database in TEST_DATABASE_URL with a name containing test and existing PostgreSQL access.

~~~bash
TEST_DATABASE_URL=postgresql+asyncpg://.../comic_pile_test uv run pytest tests/test_production_reading_graph.py -v
~~~

No regenerated expected Roll set should be accepted as a new oracle. Any change in fixture bytes, expected issue IDs or relevant statuses requires a source and user-intent review. The independent contract is deliberately narrow where user intent is settled.

## Different forms of parity

- **Schema parity:** database structure and model columns are compatible.
- **Current eligibility parity:** today's Roll frontier looks unchanged, **not sufficient**.
- **Future reading-order parity:** ratings/read transitions do not surface any issue before an independently approved required predecessor.
- **Reader-intent completeness:** unresolved source Reading List differences, deliberate boundaries and historical contradictions have each received a human classification. A zero-change migration proves **none** of this.

## Unresolved, not silently accepted

The production snapshot includes 20 authored lists, but the incident audit still reported **163 unread issues outside partial strict-list coverage**, **33 Reading List versus Reading Plan differences**, and converted historical relationships (including JLI) that can contradict newer strict lists. They require **independent classification** against sources and prior reader decisions; this test suite must not invent those classifications or silently turn every loose list strict. See issues #3676, #4198, #4199, and PR #4201. The checked-in contract lists the known unresolved categories explicitly. These are outstanding completeness blockers: do **not** sign off on full migration parity until they are cleared. CI passing the known-sequence tests proves those specific sequences, not all unscreened reading intent.
