# Undo snapshot delta lookup (issue #3218)

## What changed

`get_latest_delta_snapshot` selected the newest supported unconsumed delta by
loading every snapshot payload in a session and scanning `_version` in Python.
Snapshots now carry queryable classification metadata so the lookup is one
indexed `SELECT ... LIMIT 1`:

- `snapshots.snapshot_kind`: `delta` | `session_start` | `legacy_full` | `unknown`
- `snapshots.schema_version`: integer payload version, `NULL` when unversioned
- Composite index `ix_snapshot_session_delta_lookup` on
  `(session_id, snapshot_kind, schema_version, created_at, id)`

Classification lives in `app/services/snapshot_contract.py::classify_snapshot`
and mirrors the supported undo contract exactly: a payload is a consumable
delta only when `_version` equals `SNAPSHOT_VERSION` (2). Versioned but
unsupported payloads stay classified as `delta` rows with their own version so
they remain queryable without becoming undo targets. Session-start checkpoints
keep their `description = 'Session start' AND event_id IS NULL` identity.
Non-object payloads classify as `unknown`. Payload format is unchanged.

Writers setting the columns: `app/services/rate_service.py`
(delta + legacy full), `comic_pile/reading_session.py` (session start), and
`scripts/clone_prod_to_local.py` (export/import round-trip, with
`classify_snapshot` fallback for exports predating the columns).

## Additive rollout

Migration `f2a3b4c5d6e7` only adds nullable columns, backfills them, and
creates the index. Deploy order is safe in either direction:

1. Deploy code first: new writers populate the columns; old readers ignore
   them and keep the full-stack scan.
2. Run the migration: the backfill (`WHERE snapshot_kind IS NULL`) classifies
   every existing row, including `NULL`, non-object, unversioned, and
   unsupported-version payloads, without dropping any row.

No retention, start-restoration, payload-format, or user-facing undo behavior
changes. Consumed snapshots keep the existing lifecycle (deleted on apply);
no new undo state was introduced.

## Legacy fallback

Rows written by pre-migration code during the rollout window carry a `NULL`
kind. When the indexed path misses, the repository scans only those
unclassified rows newest-first, bounded by
`LEGACY_DELTA_FALLBACK_SCAN_LIMIT` (500) payloads. Classified rows are covered
by the indexed path, so supported deltas are never skipped silently; scanning
past the bound emits a warning. Once the backfill has run, the fallback probe
returns zero rows.

## Downgrade handling

Downgrade drops the index and both columns. Payloads are untouched, so older
code resumes the full-stack Python scan with identical undo semantics. Rows
written while the columns existed keep their JSON payloads intact.

## Coordination with #3194

#3194 owns undo UX and history aggregation (button placement, stale state,
counts, labels). This change is storage/query only: the undo API wire
contract, snapshot list responses, and restore-start behavior are unchanged,
so there is no overlap with its UI/history fixes.

## Verification

- `tests/test_snapshot_delta_lookup.py`: mixed-stack parity (legacy,
  session-start, v2, unsupported, consumed, tied timestamps, cross-session),
  10k-stack bounded retrieval (statement count, `LIMIT` presence, `EXPLAIN`
  index use), writer classification, migration backfill, bounded fallback.
- Existing suites `tests/test_delta_undo_stack.py`,
  `tests/test_delta_undo_regressions.py`, `tests/test_undo.py`, and
  `tests/test_session_snapshots.py` cover stack safety, isolation, and
  restore-start behavior.
