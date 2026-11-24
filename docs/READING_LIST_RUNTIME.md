# Reading List runtime

Reading Lists are the canonical owner-scoped record of reading order and live Roll
eligibility. They are implemented in native Rust and served under `/api/v2`; there
is no Python Reading List or custom-CBL runtime any more.

## Where the runtime lives

- `native/roll-service/src/reading_list.rs` owns list read/create/update/delete and
  the `GET /api/v2/reading-lists/{list_id}/reader` projection.
- `native/roll-service/src/custom_cbl.rs` owns the remaining authoring operations on
  `/api/v2/reading-lists`: issue search, export, Reading Plan applications, overlap
  decisions and adoption commits.
- `native/roll-service/src/reading_constraints.rs` validates the complete graph, and
  `native/roll-service/src/reading_eligibility.rs` derives eligibility from that
  validated snapshot.
- `native/roll-service/src/option_inputs.rs` loads the owner-scoped inputs the
  evaluator consumes.

Authoring always runs the shared graph validator inside the write transaction before
commit. A persisted cycle or stranded prerequisite therefore fails the write instead
of poisoning later reads.

## One eligibility answer

`reading_eligibility::evaluate` derives the first unread, non-collection-excluded
Issue in each active Thread by natural position and ID. The snapshot validates the
complete constraint set before exposing candidates: unresolved references,
stranded prerequisites and cycles fail closed, inactive prerequisite sources are
retained, and concrete blocker IDs and provenance are preserved.

Roll/skip, manual selection, Roll bootstrap, stale picks, safe queue repositioning
and Queue pagination consume that result. Durable snooze evidence is filtered by
live candidates rather than cached blocked flags. Pending-roll recovery uses the
same blockers and natural-series frontiers; a recovery link is readable only when
the current pool and session filters also allow it. Snooze/skip exclusions are
applied before the die cap. SQL selects eligible Thread IDs before identity joins,
so multiple identity mappings cannot consume another Thread's slot. Offered Issue
IDs, numbers and unread counts come from the derived frontier without rewriting
compatibility pointers or cached `is_blocked` fields.

Queue's position ordering, continuation boundary and response flags use the same
eligibility authority. Position cursors record the execution mode; an activation
change rejects an old-mode cursor rather than silently reinterpreting its blocked
grouping. Collection exclusions use stable Issue/Thread identities and normalized
volume IDs, including ComicVine numeric and `4050-` spellings; titles never infer
identity.

## Owner-approved rollout setting

Evaluated eligibility is a rollout setting, not a per-request feature flag and not
an API-version marker. `native/roll-service/src/option_e_setting.rs` parses it once
at startup into `AppState::option_e`:

| Variable | Effect |
| --- | --- |
| `OPTION_E_ENABLED` | Must be truthy (`1`, `true`, `yes`, `on`, `t`, `y`). |
| `OPTION_E_APPROVED_PREVIEW` | Must be non-blank; records the owner approval reference. |

The approval reference is an audit marker, not independently verified
authorization.

When the setting is effective, Roll, Queue, thread list and detail, Roll bootstrap,
thread issues, ordering and lifecycle handlers use the canonical evaluator. When it
is not effective, those handlers keep the legacy stored `threads.is_blocked`
authority and add no evaluator statement. Handlers must not read the environment
directly; tests inject the resolved value. Production activation is an operator
decision that requires fresh owner-approved read-only acceptance across reader
cohorts, not merely a deployment.

The Reading List reader endpoint is always canonical: it evaluates the current
owner's graph and reports `execution_mode: "option_e"` even when the rollout setting
is off for the rest of the runtime.

## Prerequisites and exclusions

Only deliberately reader-authored Issue-to-Issue requirements (`origin=reader`)
participate in canonical execution. Unclassified historical rows and
`origin=converted` generated/plan-compiled edges remain inactive audit data: the
owner-scoped loader and the shared cycle validator both exclude them, so an
unrelated legacy cycle cannot veto a canonical Reading List write. A genuinely
intended historical restriction must be explicitly re-authored as a reader-owned
prerequisite.

A list-local skip is metadata only; the Issue remains available to other lists, its
Thread and Roll. A collection exclusion removes an Issue from every List and from
Roll eligibility and survives Thread removal. Exclusion writes validate the
resulting complete graph under the reader lock and roll back a write that would
strand a prerequisite.

## Reader writes and undo

Enabled-mode rating is bound to the exact Issue on the originating roll event. It
revalidates ownership, unread state, the current derived frontier and session
filters before marking that Issue read. A changed or unidentified pending offer
requires cancellation and a new roll; an issue-number string never migrates or
infers read history in this mode. Normal explicit ratings update only the rated
Issue and its Thread's compatibility projections. Undo captures the actual Issue
pre-state even when the original Thread tracking metadata is absent, preserving both
unread exclusions and the original stored counter/pointer on restoration.

## Reader projection and explanations

`GET /api/v2/reading-lists/{list_id}/reader` returns the current authored
membership and marks each entry `read`, `excluded`, `later`, `available`, `blocked`
or `inactive`. Ownership is checked before loading eligibility, and the reader
never repairs pointers or mutates progress.

Blocked entries carry an explanation naming every active gate and the required
unread Issues:

- `strict_order`, `hold` and `after_previous` name the list that enforces them.
- `prerequisite` distinguishes `Reader prerequisite` from `Converted prerequisite`.
- `reading_cycle` reports a constraint cycle instead of failing the whole page.
- An empty frontier reports `No available unread issue` when there is nothing to
  link.

Thread connection panels show only explicit reader prerequisites. Roll's waiting
summaries carry the same canonical `blocking_reasons`, including empty-frontier
explanations that have no prerequisite Issue to link. The single and batched
blocking-info endpoints and Thread detail project the same guarded result, and
`blocking_dependencies[].issue_id` supplies an exact link to the required Issue.

## Reading boundaries and plans

`GET /api/v2/reading-boundaries/{thread_id}` and `POST /api/v2/reading-boundaries`
are the canonical reading-boundary operations. They project the current evaluator
result for one owned series or a bounded batch, including the next Issue, live
blockers and current editor targets. The v2 response has no `historical` field and
never runs the legacy dependency query; only `origin=reader` prerequisites are
loaded.

The `/api/v1/reading-boundaries` operations were retired with the Python API. Their
historical associations remain in storage but are no longer exposed by an HTTP
operation or loaded by the canonical UI.

The transitional Reading Plan reader uses the same eligibility authority for the
Issues a plan represents while retaining its historical membership until that
surface is separately retired. A linked Reading List remains the authority for
effective availability; the plan's saved `ordering_mode` is display intent, not an
eligibility override.

## Validation

Database-backed Rust tests cover the runtime and fail with setup instructions when
`RUST_ROLL_TEST_DATABASE_URL` is unset:

- `native/roll-service/tests/reading_cycle_containment.rs` covers cycles,
  converted-edge containment and the reader projection.
- `native/roll-service/tests/thread_ordering_v1_http.rs` covers ordering, reader
  entries and blocker explanations.
- `native/roll-service/tests/reading_boundary_concurrency.rs` covers the
  boundaries capability and the setting-off path.
- `native/roll-service/tests/continuity_plans_v1_http.rs` and
  `native/roll-service/tests/thread_issues_v1_http.rs` cover plan and manual-pick
  behavior.
- Unit tests in `native/roll-service/src/queue.rs` and
  `native/roll-service/src/reading_constraints.rs` cover activation combinations,
  frontier derivation and concurrency.

Every native route module also requires a DB-backed HTTP test, enforced by
`node scripts/check_native_route_db_tests.mjs`.
