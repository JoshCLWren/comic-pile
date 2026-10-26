# Roll eligibility serving options

**Status:** Independent review. Not an accepted decision, migration, or implementation specification.  
**Date:** 2026-10-25  
**Does not supersede:** [Reading List execution ADR](READING_LIST_EXECUTION_ADR.md). That document remains the authority for reading-order rules and forbids a stored frontier or cached `is_blocked` flag from becoming a second authority.  
**Evidence:** Live Option E evaluator, the Roll request path, and the two five-request production samples recorded around PRs [#4188](https://github.com/JoshCLWren/comic-pile/pull/4188) and [#4191](https://github.com/JoshCLWren/comic-pile/pull/4191). Those samples are not a controlled benchmark.

This review answers one question: how Roll should obtain the set of Issue IDs it may offer, given the canonical Option E rules. Every option below is a candidate. None is authorized for production schema or data changes by this document.

## Recommendation

**Adopt Option B+ as the next serving design.** Keep `app/services/reading_list_evaluator.py::evaluate()` as the only rule implementation. Replace the repeated owner-scoped loader with one or two slim SQL statements. Store compact per-thread snooze backoff so Roll stops replaying snooze events and session history. Roll and Cancel remain pure consumers.

Do not build a trigger-maintained `roll_eligible_issues` table until the measurement gates below fail. Triggers cannot call the Python evaluator. A correct trigger would have to recompute the whole reader in SQL, which is a second copy of the rules the accepted ADR exists to keep singular.

## Facts the options have to respect

These are observations, not design preferences.

**Frontier semantics.** `evaluate()` returns one frontier per active Thread: the first unread, non-excluded Issue ordered by `Issue.position`, then Issue ID. Blockers attach only to that frontier. Roll then keeps frontiers that are unblocked, queued, and outside the session and snooze filters. An Issue-ID set has to be that frontier set. Storing every unblocked Issue in a Thread would change which comics Roll can offer.

**Where the time goes.** Before PR #4191, five production `POST /api/v1/roll/` requests used 36 SQL statements and middleware wall times of 1,136.62 / 987.42 / 936.95 / 925.41 / 1,021.39 ms (median 987.42 ms). After PR #4191, five requests used 25 statements and 529.13 / 615.52 / 635.59 / 641.42 / 608.30 ms (median 615.52 ms). Response assembly fell to 3 queries and about 7–29 ms. Candidate-pool selection, once the snapshot already existed, was one query and about 3–7 ms. The `die_exclusions` stage was 15 queries and about 335–521 ms.

**What `die_exclusions` includes.** `derive_effective_roll_excluded_thread_ids()` calls `get_execution_eligibility()` and then reads snooze events plus every session start. The trace does not split snapshot hydration from backoff math. A stored eligible-Issue table can remove only the snapshot portion of that stage.

**Snooze shape.** Current-session snooze and skip already live on the session row. Cross-session backoff is derived from snooze and unsnooze events, `Thread.last_activity_at`, and later session start times (`comic_pile/snooze_backoff.py`). Cancel clears the pending offer. It does not change eligibility, and a maintenance mechanism must not treat it as an eligibility write.

**Rule location.** The canonical walk, overlap exceptions, holds, `after_previous`, prerequisites, and the cycle validator live in Python. A PostgreSQL trigger runs inside the modifying transaction. It cannot call that interpreter.

**Scale context from the accepted ADR's 2026-10-13 census.** About 320 active Threads and 18 Reading Lists with 1,055 entries for the primary reader. The eligible set is at most one Issue per active Thread. These counts are context, not a target.

## Ranking

| Rank | Option | Verdict |
| --- | --- | --- |
| 1 | B+ | Build this. Slim read, existing evaluator, compact snooze state. |
| 2 | G | Shadow only, and only if B+ misses the latency budget. |
| 3 | J | Last resort. Python writes current membership. A trigger only marks the reader dirty. |
| 4 | A | Remains the correctness oracle. |
| 5 | F | Reject for now. The favorite in the design note, and the wrong maintenance mechanism. |
| 6 | H | Reject for serving. Async refresh can offer a stale Issue. |
| 7 | D | Reject. Cheap read, no per-element foreign key, full-array write amplification. |
| 8 | E | Reject. Real Issue foreign keys, then a full membership copy on every edit. |
| 9 | C | Wrong shape. Per-Thread blocker documents are a second model. |

Option J is not in the original design note. It is the only stored-table design that keeps a single rule writer.

## Option A: On-demand Python evaluator

**Mechanism.** Each Roll and bootstrap loads owner Threads, all owned Issues including already-read Issues, lists, entries, exclusions, reader prerequisites, identities, and overlap decisions, then calls `evaluate()`. The result is reused inside one transaction. Separate requests load it again.

**Reasons to keep it.** The algorithm is the accepted authority. There is no projection to drift. Roll and Cancel write no eligibility state. It matches the ADR without an amendment.

**Reasons it is not the hot path.** The production samples still spend the bulk of Roll in `die_exclusions`, which reloads that snapshot and then reconstructs snooze backoff. Nothing about the request changed the reading order. The work repeats anyway.

**Verdict.** Keep A as the parity oracle and the fallback until B+ is measured. Stop using the current multi-query loader as the long-term read path.

## Option B: One consolidated snapshot fetch, then Python

**Mechanism.** As in [#4192](https://github.com/JoshCLWren/comic-pile/issues/4192), fetch the owner inputs with one SQL statement, or a few independent CTEs, and pass them to the unchanged evaluator. Avoid a Cartesian product.

**Reasons to build it.** It removes repeated client round trips and ORM hydration while leaving the proven rule implementation alone. No new table becomes a serving authority. No ADR amendment is required.

**Reasons it may not be enough.** The statement still reads the owner's reading state on every Roll. One query can be expensive to plan, transfer, or decode. The evaluator does not need every already-read Issue that appears in no list and no prerequisite. Snooze history is a separate cost this option does not touch.

**Verdict.** Necessary tactical step, and the read half of the recommendation. Measure bytes, planning time, decode time, and complete HTTP latency. Do not treat "one query" as success by itself.

## Option B+: Slim snapshot plus compact snooze state

**Mechanism.** Option B, narrowed to the columns `evaluate()` actually uses: unread frontier candidates, list entries with status, reader prerequisites with endpoint status, exclusions, overlap decisions, and confirmed volume identity. Separately, persist compact per-thread backoff (`snooze_count` after the reset boundary, latest snooze time, and whether a later unsnooze cleared it). Recompute that row on every write that moves `Thread.last_activity_at`, because backoff counts snoozes after that boundary. The writers are snooze, unsnooze, rate, undo (`app/api/undo.py` restoring an undo snapshot), and snapshot restore (`app/repositories/reading_session_repository.py` and `app/repositories/undo_snapshot_repository.py`). At selection time, compare the row with the count of sessions started after the latest snooze. Current-session snooze and skip stay filters on the session row.

**Reasons this is the recommendation.**

- One rule implementation remains. The accepted ADR does not have to be amended.
- Roll and Cancel do not recompute or write eligibility.
- The measured hotspot is input loading and exclusion reconstruction, not the in-memory walk and not the candidate query.
- Session start does not rewrite an eligible-Issue set. Backoff is a comparison against a small row.
- A forgotten application update cannot revive historical compiled dependencies, because those rows are still not inputs to `evaluate()`.

**Reasons to doubt it.** The Python walk still runs on every Roll. If a production-shaped reader shows that the walk or the slim payload, rather than the current loader and snooze scan, is the remaining cost, B+ is the wrong final form. That is a measurement question, not a reason to skip B+.

**Verdict.** Build and measure this first. The adoption go is the combined design in measurement slice 3: eligible Issue IDs match today's oracle and median Roll wall on a production-shaped reader is under 250 ms. A loader-only result under 250 ms is not required, and a loader-only result between 250 and 615 ms does not decide this verdict. No-go for the combined design if its median is worse than the post-#4191 615 ms sample.

## Option C: Versioned per-Thread frontier records

**Mechanism.** Store one current or versioned row per Thread: next Issue ID, eligibility, blocker references, and counts. Rate and order edits update the row. Roll and Queue read it.

**Reasons to consider it.** Queue and blocked-detail screens want an explanation, not only an Issue ID. A per-Thread row can serve that without joining back through the list walk.

**Reasons to reject it.** The requested read surface is an Issue ID set. Thread titles, covers, queue position, and blocker text are derivable when a screen needs them. Storing them ties the projection to today's UI and creates another document that can disagree with `evaluate()`. Explanations for the offered Issue can be computed from canonical inputs at display time.

**Verdict.** Wrong interface. If a projection is ever stored, store frontier Issue IDs only.

## Option D: Append-only `bigint[]` snapshots

**Mechanism.** On each relevant source change, compute the full eligible Issue array and insert a new `(user_id, revision, eligible_issue_ids)` row. Roll reads the latest revision.

**Reasons to consider it.** The read is a single indexed row. The shape matches an Issue-centric result. Revisions are a literal history of the set. `bigint[]` checks the element type.

**Reasons to reject it.** PostgreSQL does not enforce a foreign key from each array element to `issues(id)`. A foreign key on `user_id` does not prove each Issue belongs to that reader. Deleting an Issue leaves a dangling historical ID unless a special policy exists. Every rate, snooze, or list edit rewrites the whole array. Roll does not need that history.

**Verdict.** Reject. The cheap read does not pay for the missing per-element integrity and the write amplification.

## Option E: Append-only normalized snapshot membership

**Mechanism.** Append a snapshot header and one child row per eligible Issue, with a real foreign key to `issues(id)`. Roll reads the latest header's members.

**Reasons to consider it.** Issue existence and duplicate membership are declarative. Membership is indexable. Historical revisions remain queryable. A reader can `array_agg` the latest members when the API wants an array.

**Reasons to reject it.** Each mutation copies the entire eligible set. Two hundred eligible IDs across one thousand revisions is two hundred thousand membership rows before indexes. Two scalar foreign keys still do not prove the Issue belongs to the snapshot's owner. Readers must never observe a header without its members, so the write has to be one transaction with a latest-revision rule. The product has no requirement to query "what was eligible at revision N."

**Verdict.** Reject unless a concrete audit question appears that existing reading events cannot answer. Even then, a compact change log is the smaller record.

## Option F: Trigger-maintained current membership

**Mechanism.** `roll_eligible_issues(user_id, issue_id)` holds only the current eligible Issue IDs. Triggers on canonical tables add and remove rows, or recompute the reader, inside the modifying transaction. Roll selects the set and joins to Threads only for presentation.

**Reasons to consider it.** This is the smallest serving shape that still uses ordinary rows, uniqueness, and foreign keys. It does not copy a full snapshot on every edit. Roll's read is a primary-key lookup. Maintenance sits in the database, so a new application write path cannot forget a Python refresh call. The design note favors this option.

**Reasons to reject it for now.**

- The trigger cannot call `evaluate()`. Faithful maintenance means a SQL copy of strict order, loose lists, holds, `after_previous`, approved volume overlap, prerequisites, and exclusions. The cycle validator must use the same overlap rule. Two implementations will drift.
- The affected set of a single rating is the reader's whole frontier, not a local neighborhood. Safe trigger behavior is a full reader recompute, which is the write amplification this option claims to avoid, plus the second evaluator.
- A naive trigger on session writes treats Cancel as an eligibility change. Cancel only clears the pending pointer.
- Cross-session backoff changes when a new session starts. Roll creates or reuses the session before selection. A trigger that folds snooze into this table recomputes eligibility because a Roll started.
- `REFERENCES users(id)` plus `REFERENCES issues(id)` does not prove ownership. Issues belong to readers through Threads.
- The accepted ADR forbids a stored frontier as authority. Shipping F requires an ADR amendment and a parity proof. It does not require them before the slim-read experiment.

**Verdict.** Reject as the next architecture. Revisit only as Option J, after B+ and a shadowed Option G miss their gates.

## Option G: SQL function or view

**Mechanism.** Implement the canonical rules in SQL and expose a set-returning function or view. Roll obtains Issue IDs in one statement. Nothing is stored, so nothing can be stale.

**Reasons to consider it.** There is no invalidation protocol, no trigger coverage list, and no second stored authority. Transaction visibility is ordinary PostgreSQL snapshot behavior. If the function is cheap at one reader's scale, it is simpler than any maintained table.

**Reasons to wait.** The function is still a second implementation until it replaces the Python evaluator outright. List order, holds, and overlap exceptions are sequential walks. They can be written with window functions, and they are exactly the part most likely to disagree with `evaluate()`. One round trip does not imply a short execution. The production samples do not show the in-memory walk as the dominant cost.

**Verdict.** The right experiment after B+, not instead of it. Shadow the function against the Python oracle on Julix strict order, JLI/JLE overlap, X-Men `after_previous`, Ultimate/Absolute holds, the Starman to JSA prerequisite, and one full reader snapshot. Promote it only on identical frontier sets and a p95 execution under 50 ms. If it wins, delete the Python walk. Do not leave both as writers.

## Option H: Materialized view or async projection

**Mechanism.** Either refresh a materialized view, or have a trigger write an outbox event and a worker recompute the set. Roll reads the last completed projection.

**Reasons to consider it.** A slow recompute moves off the request that edited a list. An import or backfill can coalesce.

**Reasons to reject it for serving.** A standard materialized view refreshes more than the affected reader and is not an incremental, per-statement maintenance mechanism. An async worker adds lag, retry, and crash recovery. Roll can offer an Issue that the committed canonical data no longer allows. Fail-closed fallback means the request computes eligibility anyway, which returns the design to A, B, or G on the important path.

**Verdict.** Reject for the serving path. An outbox is acceptable later only as an operational rebuild signal, with Roll refusing a dirty reader rather than serving the previous set.

## Option J: Python-written membership, dirty-only trigger

**Mechanism.** Not in the original note. One application function, inside the writer's transaction, locks a per-reader revision row, runs `evaluate()`, and applies a set difference to `roll_eligible_issues(user_id, thread_id, issue_id)`. A statement-level trigger on canonical tables sets `dirty` and does not compute rules. Roll reads revision and membership in one statement and returns nothing when the reader is dirty. It does not recompute. Cancel and Roll write no membership rows.

Ownership is a composite foreign key through `threads(user_id, id)` and `issues(thread_id, id)`.

**Reasons to consider it.** Forgotten write paths cannot serve a stale set, because a dirty reader fails closed. Remembered write paths pay the cost at rate or list-edit time, so a clean Roll is a small read. The rule text stays in Python. The trigger is too small to hide a second graph walk. Full reader recompute is acceptable because the set is at most one Issue per active Thread.

**Reasons it is not next.** It adds a table, a lock protocol, a rebuild command, and an ADR amendment before anyone has shown that B+ is too slow. Fail-closed Roll is a production incident if a write path leaves the reader dirty. The concurrency protocol has to be tested: one statement must observe either the old complete set or the new complete set, and a rate transaction must hold the revision row before it mutates canonical data.

**Verdict.** Last resort, after the SQL-function slice misses its gate. Do not start with the table.

## Snooze, history, and ownership

Keep current-session snooze and skip out of any membership table. They are properties of the open session. Compact the cross-session backoff into its own row. Recompute it on snooze, unsnooze, rate, undo, and snapshot restore, because each of those can move `Thread.last_activity_at` and bring a cleared streak back. Selection combines that row with the frontier set. That removes the historical event scan without making session start rewrite eligible Issues.

Do not keep an append-only copy of the full eligible set. If debugging later needs a trail, record compact change events. Existing reading events document what the reader did. They are not a replay log for old rule versions.

Any future membership table must prove the Issue belongs to the reader. Two independent foreign keys do not. Physical deletes need an explicit `RESTRICT` or `CASCADE` choice. Soft-deleted Issue identity is a separate product decision and is not implied by this review.

## Measurement gates

Run these in order against read-only production-shaped data or an isolated dataset. A correctness mismatch stops the sequence. The 250 ms figure belongs only to the combined B+ gate. It is not a pass condition for the loader alone, because snooze reconstruction is a separate cost.

1. **Slim loader, evaluator unchanged.** Eligible Issue IDs match the current oracle. Record median Roll wall time while snooze reconstruction stays as it is today. No-go if that median is worse than the post-#4191 615 ms sample. A median from 250 ms through 615 ms continues to slice 2. It means the loader is not a regression, and it does not validate B+. The loader is not required to land under 250 ms before slice 2 starts.
2. **Compact snooze row, shadow only.** Excluded Thread IDs match `derive_cross_session_excluded_thread_ids()` across session boundaries. The shadow must include snooze, then rate, then undo, and a snapshot restore that writes an earlier `Thread.last_activity_at`. Restoring that boundary can revive a streak the stored row cleared on rating, so the compact row and the event-history derivation have to agree after the restore. No-go on any mismatch.
3. **Combined B+.** Slim loader, compact snooze row, and the unchanged evaluator together. Go when eligible Issue IDs still match and median Roll wall on a production-shaped reader is under 250 ms. A combined median from 250 ms through 615 ms is not a pass and does not authorize Option G or Option J. No-go when the combined median is worse than 615 ms.
4. **SQL function in shadow.** Start only when slice 3 misses its go. Identical frontier sets for the named reading orders and one full reader snapshot, with p95 execution under 50 ms. No-go on any ID mismatch or on a function that is not clearly cheaper than the combined B+ measurement.
5. **Option J, still not serving.** Start only when slice 4 also misses its gate. Roll and Cancel write zero membership rows. Rate and list edits commit the canonical change and the set difference together, or roll both back. Concurrent rate and Roll never observe a partial set or another reader's Issue. No-go on any drift.

## ADR amendment, only after a stored set is earned

Before any stored frontier is allowed to serve Roll, amend [READING_LIST_EXECUTION_ADR.md](READING_LIST_EXECUTION_ADR.md) so that all of the following are explicit:

- The table stores frontier Issue IDs only. It stores no edges, no blocker documents, and no compiled ContinuityRules.
- Either Python `evaluate()` or a single replacement SQL function is the only rule writer. The other is deleted at cutover.
- Historical and converted dependency rows, `Thread.is_blocked`, and `next_unread_issue_id` stay non-authoritative.
- Roll and Cancel are not writers. A dirty reader fails closed.
- Snooze and session skip stay outside the table.
- Equivalence means the same frontier Issue IDs as `evaluate()`, including conjunctive multi-list blockers.

That amendment is the cutover gate. It is not permission to compile Reading Plan order into dependency edges again.
