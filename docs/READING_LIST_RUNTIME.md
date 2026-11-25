# Reading List runtime

Reading Lists are the canonical owner-scoped record of reading order and live Roll
eligibility. They are implemented in native Rust and served under `/api/v2`; there
is no Python Reading List or custom-CBL runtime.

## Where the runtime lives

- `native/roll-service/src/reading_list.rs` owns list read/create/update/delete and
  the `GET /api/v2/reading-lists/{list_id}/reader` projection.
- `native/roll-service/src/custom_cbl.rs` owns the remaining authoring operations
  on `/api/v2/reading-lists`: issue search, export, Reading Plan applications,
  overlap decisions, and adoption commits.
- `native/roll-service/src/reading_constraints.rs` validates the complete graph.
- `native/roll-service/src/reading_eligibility.rs` derives availability from that
  validated snapshot.
- `native/roll-service/src/option_inputs.rs` loads the owner-scoped inputs the
  evaluator consumes.

Authoring runs the shared graph validator inside the write transaction before
commit. Only deliberately reader-authored Issue-to-Issue requirements
(`origin=reader`) have execution authority. Converted, generated, and unclassified
historical rows remain audit data and are excluded from both loading and cycle
validation, so an inert legacy cycle cannot veto a canonical Reading List write.

## One eligibility answer

`reading_eligibility::evaluate` derives the first unread, non-collection-excluded
Issue in each active Thread by natural position and ID. The snapshot validates the
complete authoritative constraint set before exposing candidates. A persisted
reader-authored cycle is contained to its affected Threads: healthy Threads keep
their frontiers, while cyclic Threads report a `reading_cycle` blocker with the
exact Issues needed for repair.

The canonical surfaces consume this authority; per-surface activation is
described below. The Roll pool first takes the top-`die` eligible window, then
removes this browser's temporary snoozes. It never backfills from below the die,
so the effective pool can only shrink. Collection exclusions use stable
Issue/Thread identities and normalized volume IDs, including ComicVine numeric and
`4050-` spellings; titles never infer identity.

## Owner-approved rollout setting

Evaluated eligibility is a rollout setting, not a per-request feature flag and not
an API-version marker. `native/roll-service/src/option_e_setting.rs` parses it once
at startup into `AppState::option_e`:

| Variable | Effect |
| --- | --- |
| `OPTION_E_ENABLED` | Must be truthy (`1`, `true`, `yes`, `on`, `t`, `y`). |
| `OPTION_E_APPROVED_PREVIEW` | Must be non-blank; records the owner approval reference. |

The approval reference is an audit marker, not independently verified
authorization. Handlers must not read the environment directly; tests inject the
resolved value.

Current behavior is not uniform across every surface:

- The Reading List reader endpoint always evaluates the canonical graph and
  reports `execution_mode: "option_e"`, even when the rollout setting is off.
- Queue, Thread list/detail, ordering, and lifecycle projections use the setting to
  choose canonical or legacy stored `threads.is_blocked` authority.
- `POST /api/v2/reading-boundaries` returns `evaluator: "unavailable"`, no next
  Issue, and no blockers when the setting is off.
- Roll offer and bootstrap always load and evaluate canonical inputs, even when
  the setting is off. The setting changes some active-thread projections but does
  not restore a stored-flag Roll fallback. This is a recorded runtime discrepancy,
  not the intended setting-off contract.

Reading List execution is current canonical behavior. The rollout setting controls
only the per-surface compatibility projections listed above; this document does
not establish the live deployed value. Changing that value remains an operator
decision requiring fresh owner-approved read-only acceptance across reader cohorts,
not merely a deployment.

## Prerequisites and exclusions

Only explicit reader-authored prerequisites participate in canonical execution.
A genuinely intended historical restriction must be explicitly re-authored as a
reader-owned prerequisite; documentation must not infer authorship from an absent
generated marker.

A list-local skip is metadata only; the Issue remains available to other lists,
its Thread, and Roll. A collection exclusion removes an Issue from every List and
from Roll eligibility and survives Thread removal. Exclusion writes validate the
resulting complete authoritative graph under the reader lock and roll back a write
that would strand a prerequisite.

## Reader writes and undo

Direct manual Read/Rate is allowed for any exact owned Issue, including blocked,
excluded, later, or inactive Issues. `PATCH /api/v2/issues/{issue_id}` with
`source: "direct"` (or omitted) does not step the die or apply Roll queue
advancement. A direct unread can reactivate a completed Thread and assign it a
queue position; that is separate from Roll advancement. Only a completion with
`source: "roll_offer"` applies Roll rating effects.

Roll-offer rating is bound to the exact Issue on the originating event. It
revalidates ownership, unread state, and pending-offer identity, but eligibility
never gates completion: a changed frontier, queue, or blocked state does not veto
rating the exact offered Issue. An otherwise no-op repeat is rejected, and an
issue-number string never substitutes for an unidentified pending offer. Undo
captures the actual Issue pre-state, preserving unread exclusions and the
original stored counter/pointer on restoration.

## Reader projection and explanations

`GET /api/v2/reading-lists/{list_id}/reader` returns the current authored
membership and marks each entry `read`, `excluded`, `later`, `available`, `blocked`,
or `inactive`. Ownership is checked before loading eligibility, and the reader
never repairs pointers or mutates progress.

Blocked entries carry an explanation naming every active gate and required unread
Issues:

- `strict_order`, `hold`, and `after_previous` name the enforcing List.
- `prerequisite` identifies a reader-authored requirement.
- `reading_cycle` reports a contained constraint cycle instead of failing the
  whole page.
- An empty frontier reports `No available unread issue` when there is nothing to
  link.

Converted prerequisites are not loaded, so a `Converted prerequisite` explanation
is not reachable in the canonical reader projection.

## Reading boundaries and plans

`POST /api/v2/reading-boundaries` is the canonical bounded batch operation. With
the rollout setting effective it projects the current evaluator result, including
next Issue, live blockers, and editor targets. With the setting off it returns the
legacy-compatible unavailable projection described above.

`GET /api/v2/reading-boundaries/{thread_id}` and the v1 reading-boundary operations
are retired. Their historical associations remain in storage but are not exposed
by a current HTTP operation or loaded by the canonical UI.

The transitional Reading Plan reader uses the same eligibility authority for the
Issues a plan represents while retaining historical membership until that surface
is separately retired. A linked Reading List remains the authority for effective
availability; the plan's saved `ordering_mode` is display intent, not an
eligibility override.

## Recorded authoring contract discrepancy

Core Reading List POST/PUT currently map a reader-authored cycle to HTTP `409`
with a plain `detail` message. The frontend builder still expects the established
structured HTTP `422` `reading_list_cycle` payload with a cycle path. This is an
unresolved runtime/frontend contract defect: repair it in the owning product work
rather than presenting either response as the intended final contract.

## Recorded product/runtime discrepancies

These implementation gaps do not redefine the expected product contract:

- A one-candidate pool still creates a random offer and shows **Begin**, while
  manual QA requires **Read Now** without a die roll.
- Completing a Roll rating returns to the idle die view instead of automatically
  rolling the next comic as the manual-QA contract requires.
- The current native service still creates six-hour server sessions and stores
  pending selection in PostgreSQL, while [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405)
  establishes sessionless Roll with browser-owned pending state. Treat the server
  implementation as unresolved compatibility behavior, not the intended final
  boundary.

## Validation

Database-backed Rust tests cover the runtime and fail with setup instructions when
`RUST_ROLL_TEST_DATABASE_URL` is unset:

- `native/roll-service/tests/reading_cycle_containment.rs` covers cycles,
  converted-edge containment, and the reader projection.
- `native/roll-service/tests/thread_ordering_v1_http.rs` covers ordering, reader
  entries, and blocker explanations.
- `native/roll-service/tests/reading_boundary_concurrency.rs` covers boundary
  capability and the setting-off path.
- `native/roll-service/tests/continuity_plans_v1_http.rs` and
  `native/roll-service/tests/thread_issues_v1_http.rs` cover plan and manual-pick
  behavior.
- Unit tests in `native/roll-service/src/roll_pool.rs`,
  `native/roll-service/src/queue.rs`, and
  `native/roll-service/src/reading_constraints.rs` cover no-backfill snoozes,
  activation combinations, frontier derivation, and concurrency.

Every native route module also requires a DB-backed HTTP test, enforced by
`node scripts/check_native_route_db_tests.mjs`.
