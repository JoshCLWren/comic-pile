# Reading List authoring

Reading List authoring is served by native Rust at `/api/v2/reading-lists`. The
former `/api/v1/custom-cbls` surface was retired with the Python API; custom CBLs
are Reading Lists under the current runtime.

## Write contract

`POST /api/v2/reading-lists` and `PUT /api/v2/reading-lists/{list_id}` accept:

- `mode`: `strict` or `loose`; omission preserves the existing mode (new lists
  default to loose).
- `entry_intents`: a map from member Issue ID to `{gate, skipped}`. `gate` is
  required and must be `none`, `hold`, or `after_previous`; `skipped` defaults to
  `false`. Omitted members retain their intent; new members default to
  none/unskipped. Supplying an intent replaces both values for that member.
- `checkpoint_issue_ids` / `checkpoint_targets`: existing checkpoint metadata,
  independent of positional gates and preserved across old-client saves.
- `confirmed_predecessor_changes`: PUT-only acknowledgement of a rejected preview.
  POST rejects any present value with HTTP `422`
  `reading_list_confirmation_put_only`.

Any update that changes stored positional requirements (including mode-only and
gate-only edits) returns HTTP `409` with
`detail.code = reading_list_predecessor_confirmation_required` and
`detail.predecessor_changes`. Each change names the affected Issue and its
before/after source Issues. Display the changes for reader confirmation, then
resubmit the same write with those Issue-ID relationships as
`confirmed_predecessor_changes`. A changed Issue-ID diff requires a new
confirmation. Display names and array ordering do not participate in consent
matching. Rejected previews do not persist metadata, membership, gates, or skips.
Successful PUT responses also include `predecessor_changes` and `warnings` for
strict lists that omit unread Issues from a partially represented Thread. Coverage
excludes skipped entries, including when the only placement for a Thread is
skipped. Omitted Issues receive no new constraints. Warnings are bounded to ten
Threads plus a remaining-Thread count; each includes the omitted count and at most
five sample names (each name/title truncated to 80 characters), followed by a
remaining-Issue count.

Warnings are write-time diagnostics returned by POST/PUT only. GET returns
`warnings: []`; it does not run global authoring validation. Reopening a list does
not imply that coverage was rechecked.

Previews describe stored authoring constraints, including globally excluded
Issues, consistent with cycle validation. Eligibility evaluation later ignores
globally excluded entries; a constraint can therefore appear in a preview without
currently blocking Roll. Retaining and confirming those stored relationships
protects against latent cycles and silent retargeting when exclusions are removed.
List-local skipped entries are omitted from both stored-order checks and previews.

## Graph validation

All list writes for a reader serialize on the reader row. Before commit, validation
checks the complete resulting authoritative graph: natural series order,
overlapping strict/loose lists and gates, and explicit `origin=reader`
prerequisites. Read Issues participate in cycle validation. Converted, generated,
and unclassified historical dependency rows are inert audit data and do not enter
the canonical loader or validator.

Collection exclusions resolve by owned Issue, Thread, canonical volume, or
confirmed external volume mapping. An excluded prerequisite source fails closed.
Inert `cbl-order:` rows are not execution inputs.

### Current cycle-response discrepancy

Core Reading List POST/PUT currently returns HTTP `409` with a plain
`Reading constraint cycle: ... Nothing was changed.` detail. The frontend builder
still expects the established structured HTTP `422` `reading_list_cycle` payload
with `detail.path`, edge origins, provenance, and endpoint names. This is an
unresolved runtime/frontend contract defect, not the intended final authoring
contract. Repair it in the owning product work; do not silently document the 409
as a completed migration or instruct clients to depend on it long term.

Snapshot identity/reference failures indicate persisted-state corruption and
intentionally surface as server errors rather than user-edit 422s. Ordinary
request errors are validated earlier: ownership/membership and enum validation,
database uniqueness/foreign keys, explicit missing-list 404, stranded-prerequisite
422, and the current cycle response described above. The API does not accept
client snapshots or IDs for new entry identities.

## Activation boundary

Authoring persists reader intent; it does not compile list adjacency into
Dependencies or change global read state.
`GET /api/v2/reading-lists/{list_id}/reader` always projects availability from the
canonical Rust evaluator.

The owner-approved rollout setting (`READING_LISTS_ENABLED` truthy plus a non-blank
`READING_LISTS_APPROVED_PREVIEW`, parsed once into `AppState::reading_lists`) controls several
Queue/Thread/boundary projections, but current Roll offer/bootstrap behavior is
not a uniform setting-off fallback. See
[Reading List runtime](../READING_LIST_RUNTIME.md#owner-approved-rollout-setting)
for the exact per-surface behavior and recorded discrepancy. Enabling the setting
is a separate owner-approved operational decision, not an authoring-side flag.

## Frontend authoring flow

The list builder exposes strict/loose modes, per-entry waits and list-local skips,
409 preview/confirmation, strict-mode coverage warnings, and cycle feedback
(#3668). Issue search returns canonical library issues. After searching,
ArrowUp/ArrowDown move between result buttons, Enter adds the focused issue, and
Escape returns to search. Enter in the search field with results already visible
moves focus to the first result without adding an issue or resubmitting. Added
entries remain unsaved until Save; changing the query hides stale results.

CI runs `pnpm --filter frontend run check:api-types` to enforce schema/client
freshness. The generator does not read `ENVIRONMENT`; do not claim a test-only
environment override that the workflow does not set.

See [Reading List runtime](../READING_LIST_RUNTIME.md) for eligibility, blockers,
manual Read/Rate freedom, and the reader projection.
