# Reading List authoring

Reading List authoring is served by native Rust at `/api/v2/reading-lists`. The
former `/api/v1/custom-cbls` surface was retired with the Python API; custom CBLs
are Reading Lists under the current runtime.

## Write contract

`POST /api/v2/reading-lists` and `PUT /api/v2/reading-lists/{list_id}` accept:

- `mode`: `strict` or `loose`; omission preserves the existing mode (new lists default to loose).
- `entry_intents`: a map from member Issue ID to `{gate, skipped}`. Gates are `none`, `hold`,
  or `after_previous`. Omitted members retain their intent; new members default to none/unskipped.
  Supplying an intent replaces both values for that member; omitted values use those defaults.
- `checkpoint_issue_ids` / `checkpoint_targets`: existing checkpoint metadata, independent of
  positional gates and preserved across old-client saves.
- `confirmed_predecessor_changes`: PUT-only acknowledgement of a rejected preview. POST rejects
  any present value with HTTP 422 `reading_list_confirmation_put_only`.

Any update that changes stored positional requirements (including mode-only and gate-only edits)
returns HTTP 409 with `detail.code = reading_list_predecessor_confirmation_required` and
`detail.predecessor_changes`. Each change names the affected Issue and its before/after source
Issues. Display the changes for reader confirmation, then resubmit the same write with those
Issue-ID relationships as `confirmed_predecessor_changes`. A changed Issue-ID diff requires a new
confirmation. Display names and array ordering do not participate in consent matching. Rejected
previews do not persist metadata, membership, gates, or skips. Successful PUT responses also
include `predecessor_changes` and `warnings` for strict lists that omit unread Issues from a
partially represented Thread. Coverage excludes skipped entries, including when the only placement
for a Thread is skipped. Omitted Issues receive no new constraints. Warnings are bounded to ten
Threads plus a remaining-Thread count; each includes the omitted count and at most five sample
names (each name/title truncated to 80 characters), followed by a remaining-Issue count.

Warnings are write-time diagnostics returned by POST/PUT only. GET returns `warnings: []`; it does
not run global authoring validation. Reopening a list does not imply that coverage was rechecked.

Previews describe **stored authoring constraints**, including globally excluded Issues, consistent
with cycle validation. Eligibility evaluation later ignores globally excluded entries; a constraint
can therefore appear in this preview without currently blocking Roll. Retaining and confirming
those stored relationships protects against latent cycles and silent retargeting when exclusions
are removed. List-local skipped entries are omitted from both stored-order checks and previews.

All list writes for a reader serialize on the reader row. Before commit, validation checks the
complete resulting graph: natural series order, overlapping strict/loose lists and gates, and
currently enforced explicit/historical dependencies. Read Issues participate in cycle validation.
Collection exclusions resolve by owned Issue, Thread, canonical volume, or confirmed external
volume mapping. An excluded prerequisite source fails closed. Cycles return HTTP 422 with
`reading_list_cycle`, a readable path, and edge origins. No historical dependency is classified,
retired, or rewritten by this API; cycle diagnostics explicitly label unknown historical provenance
rather than inferring reader authorship from an absent generated marker. Inert `cbl-order:` rows
are not execution inputs. Each structured cycle-path edge also carries `prerequisite_origin`
(`reader`, `converted`, or null for non-prerequisite edges) and `provenance` (an array). Each edge
additionally carries `source_issue_name` and `target_issue_name`, the canonical Thread-title plus
issue-number for its endpoints, so clients can name every cycle node — including Issues that are
not members of the edited list (overlapping lists, series order, prerequisites). The authoring
adapter marks historical rows as `converted` with `historical classification unknown` provenance;
this is not proof of approved conversion or reader authorship.

Snapshot identity/reference failures indicate persisted-state corruption and intentionally surface
as server errors, rather than a user-edit 422. Ordinary request errors are validated earlier:
ownership/membership and enum validation, database uniqueness/foreign keys, explicit missing-list
404, stranded-prerequisite 422, and cycle 422. The API does not accept client snapshots or IDs for
new entry identities; those internal invariants cannot be authored through this write contract.

## Activation boundary

Authoring persists reader intent; it does not compile list adjacency into Dependencies or change
global read state. `GET /api/v2/reading-lists/{list_id}/reader` always projects availability from
the canonical Rust evaluator.

Roll, Queue, thread list and detail, Roll bootstrap, thread issues, ordering and lifecycle handlers
use that same evaluator only when the owner-approved rollout setting is effective
(`OPTION_E_ENABLED` truthy plus a non-blank `OPTION_E_APPROVED_PREVIEW`, parsed once into
`AppState::option_e`). When it is not effective, those handlers keep the legacy stored
`threads.is_blocked` authority. Enabling the setting is a separate, owner-approved operational
decision, not an authoring-side flag.

## Frontend authoring flow

The list builder exposes strict/loose modes, per-entry waits and list-local skips,
409 preview/confirmation, strict-mode coverage warnings, and actionable 422 cycle feedback (#3668).
Issue search returns canonical library issues. After searching, ArrowUp/ArrowDown move between
result buttons, Enter adds the focused issue, and Escape returns to search. Enter in the search
field with results already visible moves focus to the first result without adding an issue or
resubmitting. Added entries remain unsaved until Save; changing the query hides stale results.

CI runs `pnpm --filter frontend run check:api-types` with explicit `ENVIRONMENT=test` to enforce
schema/client freshness. This setting does not depend on `.env.test` being present or on the
runner's inherited environment.

See [Reading List runtime](../READING_LIST_RUNTIME.md) for eligibility, blockers and the reader
projection.
