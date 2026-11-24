# Reading List authoring

Reading List authoring is served by native Rust at `/api/v2/reading-lists`. The
former `/api/v1/custom-cbls` surface was retired with the Python API; custom CBLs
are Reading Lists under the current runtime.

## Write contract

`POST /api/v2/reading-lists` and `PUT /api/v2/reading-lists/{list_id}` accept:

- `mode`: `strict` or `loose`; omission preserves the existing mode (new lists
  default to loose).
- `entry_intents`: a map from member Issue ID to `{gate, skipped}`. Gates are
  `none`, `hold` or `after_previous`. Omitted members retain their intent; new
  members default to none/unskipped. Supplying an intent replaces both values for
  that member.
- `checkpoint_issue_ids` / `checkpoint_targets`: existing checkpoint metadata,
  independent of positional gates and preserved across old-client saves.
- `confirmed_predecessor_changes`: PUT-only acknowledgement of a rejected preview.
  POST rejects any present value with HTTP 422
  `reading_list_confirmation_put_only`.

An update that changes stored positional requirements, including mode-only and
gate-only edits, can return HTTP 409 with
`detail.code = reading_list_predecessor_confirmation_required` and
`detail.predecessor_changes`. Display the changes and resubmit the same write with
those Issue-ID relationships as `confirmed_predecessor_changes`. A changed diff
requires fresh confirmation. Rejected previews persist nothing. Successful PUT
responses include `predecessor_changes` and bounded strict-list coverage warnings.
GET returns `warnings: []` and does not rerun global authoring validation.

Previews describe stored authoring constraints, including globally excluded
Issues, consistent with cycle validation. Eligibility evaluation later ignores
globally excluded entries. List-local skipped entries are omitted from stored-order
checks and previews.

## Validation and error shapes

All list writes for a reader serialize on the reader row. Before commit,
validation checks natural series order, overlapping strict/loose lists, positional
gates and **explicit `origin=reader` prerequisites only**. Read Issues participate.
Historical/unclassified and `origin=converted` rows are inert audit data and never
enter canonical validation.

List CRUD uses `reading_graph::cycle_conflict`:

- A canonical cycle returns HTTP 409 with a string `detail` naming the cycle path
  and stating that nothing changed.
- An invalid internal snapshot returns HTTP 422 with the mapper's detail string.
- Ownership/membership and enum validation happen before the write; missing lists
  return 404; database uniqueness/foreign-key failures follow the native error
  boundary.

The separate custom-CBL apply/overlap/adoption operations retain their structured
HTTP 422 `reading_list_cycle` contract (`detail.code` / `detail.path`). Do not
present that response shape as the list CRUD cycle contract.

## Single-engine boundary

Authoring persists reader intent; it does not compile list adjacency into
Dependencies or change global read state. The reader endpoint always projects
availability from the canonical Rust evaluator.

The owner's 2026-11-23 correction requires one canonical engine for automatic
Roll, with no `OPTION_E_ENABLED` / `OPTION_E_APPROVED_PREVIEW` gate and no legacy
fallback ([#3676](https://github.com/JoshCLWren/comic-pile/issues/3676),
[#5525](https://github.com/JoshCLWren/comic-pile/issues/5525)). The checked-in
runtime still contains those obsolete branches; that is an implementation
discrepancy, not a supported authoring or deployment mode. See
[Reading List runtime](../READING_LIST_RUNTIME.md).

Direct manual exact-issue reads and ratings remain independent of automatic-Roll
eligibility and do not mutate pending Roll, die or queue state until saved.

## Frontend authoring flow

The list builder exposes strict/loose modes, per-entry waits, list-local skips,
409 preview/confirmation, coverage warnings and actionable cycle feedback. Issue
search returns canonical library issues. ArrowUp/ArrowDown move between result
buttons, Enter adds the focused Issue, and Escape returns to search. Added entries
remain unsaved until Save; changing the query hides stale results.

CI runs `pnpm --filter frontend run check:api-types` to enforce schema/client
freshness. Generated contracts, not this narrative, remain the wire authority.
