# Reading List runtime

Reading Lists are the canonical owner-scoped record of reading order and live
**automatic-Roll** eligibility. They are implemented in native Rust and served
under `/api/v2`; there is no Python Reading List or custom-CBL runtime.

## Binding product contract

The owner's 2026-11-23 correction in
[#3676](https://github.com/JoshCLWren/comic-pile/issues/3676) and
[#5525](https://github.com/JoshCLWren/comic-pile/issues/5525) requires **one
canonical engine, no Option E mode**. The Reading List evaluator is the only
execution model. There is no supported enabled/disabled switch, approval
environment gate, legacy eligibility fallback or preview mode.

The checked-in runtime still contains the obsolete `OPTION_E_ENABLED`,
`OPTION_E_APPROVED_PREVIEW`, `AppState::option_e` and
`reject_option_e_preview` branches. That is an implementation discrepancy tracked
by #3676/#5525, not approved product behavior. Do not set those variables, document
them as an activation procedure, or turn the legacy engine back on. Removing the
branches is runtime work outside this documentation reconciliation.

## Where the runtime lives

- `native/roll-service/src/reading_list.rs` owns list read/create/update/delete and
  the `GET /api/v2/reading-lists/{list_id}/reader` projection.
- `native/roll-service/src/custom_cbl.rs` owns issue search, export, Reading Plan
  application and overlap-decision operations.
- `native/roll-service/src/issue_identity.rs` owns CBL adoption commits.
- `native/roll-service/src/reading_constraints.rs` validates the complete canonical
  graph, and `reading_eligibility.rs` derives automatic-Roll eligibility.
- `native/roll-service/src/option_inputs.rs` loads the owner-scoped inputs.

Authoring runs the shared graph validator inside the write transaction before
commit. A canonical cycle or stranded reader prerequisite fails the write instead
of poisoning later reads.

## Automatic Roll eligibility

`reading_eligibility::evaluate` derives the first unread, non-excluded Issue in
each active Thread by natural position and ID. The snapshot validates canonical
constraints before exposing candidates: unresolved references, stranded
prerequisites and cycles fail closed. Concrete blocker IDs and provenance are
preserved.

Roll/skip, Roll bootstrap, stale picks, safe queue repositioning and Queue
pagination consume that result. Durable snooze evidence is filtered by live
candidates rather than cached blocked flags. Pending-roll recovery uses the same
canonical blockers and natural-series frontiers. Snooze/skip exclusions are applied
before the die cap. SQL selects eligible Thread IDs before identity joins, so
multiple identity mappings cannot consume another Thread's slot.

Queue ordering and response flags use the same eligibility authority. Collection
exclusions use stable Issue/Thread identities and normalized volume IDs, including
ComicVine numeric and `4050-` spellings; titles never infer identity.

## Manual reading is not automatic Roll

Direct manual **Read now**, **Rate**, **Mark read** and **Mark unread** actions act
on an exact owned Issue regardless of automatic-Roll eligibility. They do not use
`thread.is_blocked`, Reading List gates, prerequisites, queue membership, snooze
or missing ComicVine mapping as permission vetoes.

The direct write is `PATCH /api/v2/issues/{issue_id}` with `source: "direct"` and
an idempotency key. Opening the shared issue card is read-only; nothing persists
until Save. The owner requires a direct manual read/rating not to change the die,
queue order or an existing pending random Roll offer. Only completion of a
genuine random Roll offer uses the separate automatic-Roll event semantics and
its die/queue effects.

**Known implementation discrepancy:** the direct handler still contains a
completed-Thread reactivation branch in `native/roll-service/src/issue_service.rs`
that can change queue placement. That conflicts with the owner's queue-isolation
requirement and must be repaired under #5525; it is not intended product behavior.

## Prerequisites and exclusions

Only deliberately reader-authored Issue-to-Issue requirements (`origin=reader`)
participate in canonical execution and validation. Unclassified historical rows
and `origin=converted` generated/plan-compiled edges remain inactive audit data:
the owner-scoped loader and shared cycle validator exclude them, so an unrelated
legacy cycle cannot veto a canonical Reading List write. A genuinely intended
historical restriction must be explicitly re-authored as a reader-owned
prerequisite.

A list-local skip is metadata only; the Issue remains available to other lists,
its Thread and automatic Roll. A collection exclusion removes an Issue from every
List and from automatic-Roll eligibility and survives Thread removal. Exclusion
writes validate the resulting canonical graph under the reader lock and roll back
a write that would strand a reader prerequisite.

## Reader projection and explanations

`GET /api/v2/reading-lists/{list_id}/reader` always evaluates the canonical graph
and reports `execution_mode: "option_e"`. That field names the evaluator contract;
it is not a runtime mode switch. Ownership is checked before loading eligibility,
and the reader never repairs pointers or mutates progress.

Blocked entries carry an explanation naming every active gate and required unread
Issue:

- `strict_order`, `hold` and `after_previous` name the enforcing list.
- `prerequisite` identifies a reader-authored prerequisite. Converted or unknown
  historical rows are not reported as active blockers.
- `reading_cycle` reports a canonical constraint cycle rather than returning a
  partial successful page.
- An empty frontier reports `No available unread issue` when there is nothing to
  link.

Thread connection panels show only explicit reader prerequisites. Roll waiting
summaries and retained blocking-info reads use the same guarded canonical result.

## Reading boundaries and plans

`POST /api/v2/reading-boundaries` is the only reading-boundary operation. It
accepts `thread_ids` containing 1–200 owned Thread IDs and returns the current
canonical next Issue, live blockers and editor targets for the batch. The v2
response has no `historical` field and loads only `origin=reader` prerequisites.
There is no `GET /api/v2/reading-boundaries/{thread_id}` route.

The `/api/v1/reading-boundaries` operations were retired with the Python API.
Historical associations remain in storage but are not exposed by a current HTTP
operation or loaded by the canonical UI.

The transitional Reading Plan reader uses the same eligibility authority for the
Issues a plan represents while retaining historical membership until that surface
is separately retired. A linked Reading List remains the authority for effective
availability; the plan's saved `ordering_mode` is display intent, not an
eligibility override.

## Validation

Database-backed Rust tests cover the runtime and fail with setup instructions when
`RUST_ROLL_TEST_DATABASE_URL` is unset:

- `native/roll-service/tests/reading_cycle_containment.rs` covers canonical
  cycles, converted-edge containment and the reader projection.
- `native/roll-service/tests/thread_ordering_v1_http.rs` covers ordering, reader
  entries and blocker explanations.
- `native/roll-service/tests/reading_boundary_concurrency.rs` covers the batch
  boundary capability.
- `native/roll-service/tests/continuity_plans_v1_http.rs` and
  `thread_issues_v1_http.rs` cover plan and manual-pick behavior.
- Unit tests in `native/roll-service/src/queue.rs` and
  `reading_constraints.rs` cover frontier derivation and concurrency.

Tests that exist only to select the obsolete enabled/disabled engine are legacy
implementation evidence, not the desired product contract. Every native route
module also requires a DB-backed HTTP test, enforced by
`node scripts/check_native_route_db_tests.mjs`.
