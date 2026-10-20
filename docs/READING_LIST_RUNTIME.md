# Guarded Reading List execution

Option E's runtime adapter is separate from its production activation. Deploying
this code leaves legacy execution active. Issue #3673 supplies the adapter;
#3675 supplies the reviewed conversion plan, and #3676 owns production conversion
and activation after fresh owner approval. The accepted
[Reading List ADR](READING_LIST_EXECUTION_ADR.md) remains authoritative.

## Activation boundary

`ReadingExecutionSettings` reads these process environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPTION_E_ENABLED` | `false` | Explicit runtime switch. |
| `OPTION_E_APPROVED_PREVIEW` | empty | Reference to the actual fresh owner-approved production preview/receipt. |

An enabled configuration without a production preview reference fails validation.
The activation switch is **app-wide**, and each request still evaluates only the
signed-in reader's owned lists, natural Issue positions, exclusions and explicit
reader-authored prerequisites. An operator-provided approval reference is an audit
marker, not independently verified authorization. Do not enable production until
fresh read-only acceptance covers all reader cohorts, not merely one owner/list.

Local API and Chromium tests use isolated PostgreSQL databases and an explicitly
non-production fixture reference. Those fixtures are not production approval.

## One decision before weighting

`get_execution_eligibility` returns `None` in legacy mode without loading the
Reading List graph. In enabled mode it loads one owner-scoped detached result
and shares it through the request-owned async session and transaction. A later
transaction does not reuse the old result. Relevant flushed Issue, Thread,
list, prerequisite, exclusion or identity writes invalidate it; session/event
bookkeeping alone does not cause another graph load.

The snapshot validates the complete constraints before exposing candidates.
Unresolved references, stranded prerequisites and cycles fail closed. It derives
the first unread, non-collection-excluded Issue by position and ID, includes
inactive prerequisite sources, and retains concrete blocker IDs/provenance.
Explicit `origin=reader` requirements remain effective regardless of note text.
The Dependency Builder's `POST /api/v1/dependencies/` path persists new
reader-authored edges with `origin=reader`, so authoring, thread details, Queue,
and Roll use the same prerequisite. This does not reclassify existing rows.
Unclassified historical rows and `origin=converted` generated/plan-compiled
edges are inactive audit data; they cannot override today's canonical Reading
Lists. A genuinely intended independent historical restriction must be explicitly
authorized as a reader-owned prerequisite. No provenance classification is required
to ignore outdated generated restrictions.

Roll/skip, manual selection, both bootstrap versions, stale picks, safe queue
repositioning and Queue pagination consume that result. Durable snooze evidence
is filtered by live candidates, not cached blocked flags. Pending-roll recovery
uses the same blockers and natural-series frontiers; a recovery link is readable
only when the current pool and session filters also allow it. Snooze/skip exclusions
are applied before the die cap. SQL selects eligible Thread IDs before identity
joins, so multiple identity mappings cannot consume another Thread's slot.
Offered Issue IDs, numbers and unread counts come from the derived frontier,
without rewriting compatibility pointers or cached `is_blocked` fields.

Queue's position ordering, continuation boundary and response flags use the
same eligibility authority. Position cursors record the execution mode; an
activation change rejects an old-mode cursor rather than silently reinterpreting
its blocked grouping. Empty eligible sets remain valid SQL sort expressions.
Collection exclusions use stable Issue/Thread identities and normalized volume
IDs, including ComicVine numeric and `4050-` spellings; titles never infer identity.

## Reader writes and undo

Enabled-mode rating is bound to the exact Issue on the originating roll event.
It revalidates ownership, unread state, the current derived frontier and session
filters before marking that Issue read. A changed or unidentified pending offer
requires cancellation and a new roll; an issue-number string never migrates or
infers read history in this mode. Normal explicit ratings update only the rated
Issue and its Thread's compatibility projections. Undo captures the actual Issue
pre-state even when the original Thread tracking metadata is absent, preserving
both unread exclusions and the original stored counter/pointer on restoration.

Exclusion creation and deletion validate the resulting complete graph under the
reader lock before commit. A stranded prerequisite, unresolved reference or
cycle rejects and rolls back the write instead of poisoning future runtime reads.

## Validation and rollback

`tests/test_option_e_runtime.py` exercises real PostgreSQL and API paths for
strict/loose behavior, stale flags/pointers, exclusions, session filters,
prerequisite provenance, snapshot sharing/invalidation, app-wide activation with reader isolation,
empty Queues, cursor mode boundaries, identity fan-out, durable snooze/recovery,
exclusion-write rejection, exact-offer rating and undo. The pure evaluator
and existing Roll/Queue regressions cover the underlying reading scenarios.

Turning the execution switch off returns those readers to legacy selection;
deploying this adapter performs no data conversion, edge compilation, historical
cleanup, read-state change or migration. Ordinary reader commands still persist
their explicitly requested ratings and reads. Data rollback and receipt validation belong to
the separately approved conversion/activation procedure. Runtime deployment is
not evidence that production parity or the ADR's trust milestone has passed.

## Reader explanations

Thread connection panels show only explicit reader prerequisites in enabled mode;
untyped and converted legacy edges remain stored audit data and are not labeled
as current blockers. Disabling the switch restores the legacy connection view.

The single and batched `getBlockingInfo` endpoints and Thread detail now project
that same guarded result. Every named list restriction and prerequisite is kept;
`blocking_dependencies[].issue_id` supplies an exact link to the required issue.
Roll's waiting summaries also include the canonical `blocking_reasons`, including
empty-frontier explanations that have no prerequisite Issue to link.

`GET /api/v1/custom-cbls/{list_id}/reader` returns the complete current authored
membership, rather than the historical Reading Plan copy. Each entry distinguishes
read, available, blocked, later in natural series order, collection-excluded and
inactive states. List-local skips remain explicit metadata and do not hide global
availability. With execution disabled, unread entries are labeled `legacy`; opening
the reader never activates stored strict modes or gates. Ownership is checked
before loading eligibility. These reads do not repair pointers or mutate progress.

The custom CBL editor's **Read this list** control opens this current-list reader.
Available issues can be marked read directly, and read issues can be marked unread.
These explicit writes use the existing Issue APIs; all affected reader, Roll, Queue
and explanation caches refresh because one global read can release another series.
Issue tags reuse the Thread's direct/inherited tag display and source navigation.
The transitional Reading Plan reader uses the same authority for its represented
issues, while retaining its historical membership until separately approved retirement.
