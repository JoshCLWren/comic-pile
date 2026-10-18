# ADR: Reading Lists are the authority for reading sequence and live Roll eligibility

**Status:** Accepted (design decision; implementation pending)  
**Date:** 2026-10-13  
**Decision owner:** JoshCLWren  
**Supersedes:** [Reading Graph ADR](READING_GRAPH_ADR.md) as the target runtime/storage architecture; [2026-10-12 Roll eligibility contract](roll-eligibility-contract.md) where it requires compiling explicit checkpoint edges or rejects strict list order. Existing runtime remains in force **until** the guarded Option E cutover.  
**Design basis:** Independent Opus architecture review, revised 2026-10-13, and production read-only evidence.  
**Implementation coordination:** [#2366](https://github.com/JoshCLWren/comic-pile/issues/2366). **This ADR is the authority for replacement work; do not extend the retiring Reading Plan compiler.**

## Context and decision

ComicPile duplicates reading intent across Custom CBLs, Reading Plans, plan JSON, plan memberships, ContinuityRules, dependency rows and cached Thread flags. Import and plan-save paths compile lossy copies, and obsolete enforced edges can survive later edits. Roll can consequently be blocked by rules no longer visible in the edited list.

**Adopt Option E:** a reader-owned **Reading List**, the existing issue's natural series position, and stable explicit **Prerequisites** are the only execution inputs. One live evaluator returns the eligibility of the first unread issue in each active Thread. The queue, Roll, list reader, thread page and explanations consume that single answer. **No compilation to dependency edges, generalized continuity runtime, or cached `is_blocked` as authority.**

Existing Custom CBLs become Reading Lists. They are **not regenerated from public sources** and are not discarded in favor of older Reading Plan copies. The user sees their intended sequences, not migration constructs.

## Minimal data contract

- **Issues and Threads:** Keep stable Issue and Thread IDs, `Issue.position`, global read/unread state, ratings, events, identity mappings, queue positions and read history. Derive the frontier from the first unread, non-collection-excluded issue in each Thread ordered by position and ID; a stored `next_unread_issue_id` can be a temporary compatibility projection, never a conflicting authority.
- **Reading Lists:** Evolve `custom_cbl_lists` with `mode = strict | loose` and `custom_cbl_entries` with `gate = none | hold | after_previous`, `skipped` and stable `issue_id`. Keep existing order and source provenance. No third gate type, no multiple-lane runtime, no per-list read state.
- **Prerequisites:** Only deliberately reader-authored Issue-to-Issue requirements (`origin=reader`) participate in canonical execution. They survive list edits and deletion. Historical `origin=NULL` and generated `origin=converted` rows remain available for audit but have no authority over Reading Lists. A reader can explicitly adopt an existing historical pair through validated prerequisite authoring. Neither list save nor import may generate runtime prerequisites as a side effect.
- **Collection exclusions:** A small durable user-owned exclusion table, targeting an external series/volume identity, a Thread, or an Issue. Do not infer exclusions from mere absence in a list. They survive Thread removal and prevent Roll, CBL import and release sync from adopting or offering deliberately excluded material (e.g., Absolute Flash and Absolute Green Lantern). Only the reader can remove one.
- **List-local skip:** `skipped=true` means only that list ignores this issue; other lists, its Thread, and Roll may still offer it. A globally excluded issue is ignored by every list and skipped as a frontier candidate. Refuse an exclusion that strands an explicit prerequisite until the reader resolves that prerequisite.

### Inactive storage rollout

The additive storage slice (#3662) exposes stored mode, gate and skip values in list
responses and preserves them when older clients replace membership. Defaults are
loose, none and false. These fields do not activate eligibility or accept new
authoring intent through the legacy write API; owner-scoped writes, cycle validation
and reorder confirmation belong to #3667. Roll remains on its existing authority
until the guarded adapter and production acceptance stages.

### Modes and loose-list gates

- **Strict:** every remaining entry waits for all earlier remaining entries. At most its first unread remaining entry is available from that list. This fits the Julix Mignolaverse and JLI/JLE reading orders. Warn if the list omits unread issues from a partially represented Thread; do not silently gate omitted material.
- **Loose:** lists express placement; separately progressing series are not blocked by plain adjacent entries. This fits X-Men and Ultimate/Absolute except explicit events and crossover boundaries.
- **`after_previous`:** the gated issue waits for the nearest prior remaining entry in that list to be read. Reordering can change the predecessor and requires a visible “now waits on” confirmation before saving.
- **`hold`:** for the milestone entry at position `p`, require all remaining entries above it to be read. Every remaining entry **below** that milestone stays blocked until all preceding entries **including the milestone** are read. Formal rule: with `u` the earliest unread remaining position, the hold issue is blocked when `u < p`; for a later entry at `q`, with the latest preceding hold at `k < q`, it is blocked when `u <= k`. A hold applies only inside its list.

A list containing the same Issue as another list shares the one global read state. Eligibility is **conjunctive**: any active list blocker or prerequisite blocks an issue. A loose list cannot cancel a strict list. Explain **every** active blocker by named unread issues and its provenance.

### No annual or crossover inference

Where annuals and specials already live in their parent Threads, preserve their `Issue.position`. Where they have their own Threads, preserve identity and curated list placement. A strict list interleaves them automatically. A loose list needs explicit positional gates or existing prerequisites **only if reader intent calls for them**. Issue labels (Annual, Special, Giant-Size) never automatically create blockers. Multi-series crossovers may use ordered `after_previous` entries and explicit stable prerequisites. Starman #55 (Issue **26360**) before All-Star Comics (1999) #1 (Issue **117189**) is a real stable prerequisite, regardless of list edits.

## Execution and validation contract

```python
@dataclass(frozen=True)
class Blocker:
    kind: Literal["strict_order", "hold", "after_previous", "prerequisite"]
    list_id: int | None
    waiting_on_issue_ids: tuple[int, ...]

@dataclass(frozen=True)
class ThreadEligibility:
    thread_id: int
    next_issue_id: int | None
    blockers: tuple[Blocker, ...]

async def load_reading_snapshot(db, user_id) -> ReadingSnapshot: ...
def evaluate(snapshot: ReadingSnapshot) -> dict[int, ThreadEligibility]: ...
```

`evaluate` is deterministic, user-scoped, pure, and shared by Roll/Queue/explanations; dice weighting and queue priority follow eligibility filtering. Mark-read/rate updates Issue state and does not materialize list constraints.

**Global cycle prevention:** Before any edit that can change the execution graph, topologically validate the union of series-order edges, strict-list adjacency, loose `after_previous`, `hold` milestone edges, and explicit prerequisites. Validate all lengths of cycles, including A->B->C->A across three lists and cycles among already read issues. Reject writes with a human-readable cycle path and origins. A stranded prerequisite is a separate hard error. Apply to list CRUD, modes/gates, prerequisites, exclusions, Thread ordering, issue adoption/import, and release sync. Automated writes fail closed with diagnostics. Reordering gated entries requires confirmation of changed waiting-on relationships.

## Guarded replacement, NOT an immediate production instruction

**Phase 0: read-only production census.** Generate durable reports, not inferred cleanup:
1. Every list-versus-plan discrepancy (both directions and ordering), unpaired lists/plans, excludes/skips, provenance and extra lanes.
2. Every derived-vs-stored Thread frontier mismatch, including shell Threads and intervening unread issues.
3. Every *explicitly reader-authored* prerequisite and its current impact, separately from legacy/compiled dependency artifacts that must not block Option E. Identify missing deliberate prerequisites (e.g., Starman #55 before JSA), cycles, separate-Thread annuals without gates and collection exclusions. No provenance classification requirement for the historical archive.

On 2026-10-13 production, the known baseline included 18 Custom CBLs with 1,055 entries, 24 bad stored frontiers, 1,146 non-`cbl-order` dependencies (780 cross-Thread), and approximately 74,259 inert `cbl-order` rows. These are dated observations, **not** a target count. Absolute Custom CBL has 105 entries while its plan membership has 76; Mignolaverse has 466 vs 464. Do not resolve any difference by `updated_at`, a public source, or an issue title.

**Phase 1: canonical intent + shadow evaluator.** Use each owner's existing lists, explicit mode/gates, intentional exclusions and stable reader prerequisites. Do not copy or reconcile older Reading Plan membership into current lists. Run the pure evaluator in shadow without changing Roll; report both frontier and eligibility divergence and identify any deliberate exceptions still stored only as historical dependencies.

**Phase 2: guarded production reconciliation.** Current owner-authored Reading Lists already hold the intended sequences. Explicitly author only genuinely required independent prerequisites and verified positional gates/exclusions; do not convert all historical edges or require unknown-origin classifications. Keep legacy records as inactive audit data. Preflight and validate every owner's applicable constraints and a full before/after eligibility diff before app-wide activation. Fail closed on invalid canonical graphs, unexpected offers, or unresolved intentional bridges. Production edits require owner authorization, already granted for #3676, and fresh evidence.

**Phase 3: app-wide activation.** One engine applies to every reader using their own lists, natural series positions, exclusions, and explicitly authored prerequisites. Historical/converted edges are never loaded as Option E constraints, so no individual legacy retirement decision is needed. Verify all reader cohorts and named reading examples, then enable the app-wide switch with a rollback boundary and check every user-facing eligibility surface.

**Trust milestone:** Priority real-world workflows (Julix Mignolaverse, JLI/JLE annuals, X-Men crossover, Ultimate/Absolute holds, Starman -> JSA) each pass evaluated “what can I roll next and why?” examples, with 15-20 human-checked offers/blocks per list, no unexplained converted prerequisite blocking a frontier, no excluded title offered/imported, and Roll/Queue/thread/list agreement. All touched frontiers eventually must meet this bar.

**Phase 4: remove superseded machinery.** Only after all lists are activated, archived originals are verified, and two weeks pass without eligibility drift/rollback: remove Reading Plans, plan JSON/membership/source-placement, ContinuityRules, rule compilation, plan adoption, obsolete crossover/reading-order execution, inert generated edges, redundant API/editor surfaces, and finally `is_blocked` and stored frontier as authorities. Retain CBL browser/import, identity reconciliation, release tracking, issues, ratings, queues, Thread/Issue order, and useful read-only explanations. Do not delete Alembic migration history.

## Factory-sized work and authority boundaries

- Split into narrowly testable issues, typically one bounded service, adapter or schema concern with focused tests; avoid a giant “implement Option E” ticket.
- Read-only census, pure evaluator, validators, non-destructive schema changes, shadow reporting and UI foundations are factory-executable when dependencies are ready.
- **Manual-only:** approving changes to genuine reader intent and exclusions, resolving conflicting authored orders, app-wide production activation and destructive retirement. Do not require manual approval of historical provenance merely to ignore obsolete compiled edges.
- No concurrent factory jobs rewriting the same Roll authority or migration engine. Use explicit sequencing and a single coordinator.
- Do **not** patch the old plan compiler, add checkpoint types, or reintroduce list-adjacency materialization while implementing this ADR.
- The older Reading Graph ADR, canonical Reading Plan PRD and 2026-10-12 eligibility contract describe the **currently deployed/legacy** system until switched; they must not be used to justify new design work contrary to this accepted target.

## Required behavioral regression fixtures

1. **Ordinary Thread:** first unread then next issue; unchanged list save yields identical eligibility.
2. **Julix strict:** only first unread included issue is offered; crossing from Hellboy to Abe Sapien waits for preceding issue; list-local skip does not globally exclude the skipped issue.
3. **JLI/JLE strict:** annual in separate Thread must wait for its curated position, including Annual #2 far later; embedded annual follows `Issue.position` without a gate.
4. **Ultimate/Absolute loose + holds:** series advance independently before `One Year In`; milestone becomes eligible only after all entries above; material below remains blocked **while milestone itself unread**; later `Two Years In` works independently.
5. **X-Men loose crossover:** `after_previous` orders crossover chapters without blocking unrelated series.
6. **Starman/JSA:** source 26360 -> target 117189 persists unchanged under list reorder/delete.
7. **Overlap:** any blocking list or stable prerequisite wins; one read state; cycle through three lists, series order and hold is rejected with explicit path.
8. **Exclusions:** Absolute Flash/Green Lantern unavailable to Roll, import and release sync, survive Thread deletion/reimport; list-local skip never globally hides comics.
9. **Safety:** no annual-label gate inference; full list reconciliation; all 24 frontiers accounted for; class A prerequisites retained; unexpected conversion diff aborts; no explanation-less blocked Roll offers.

## Consequences

**Benefits:** One reader-intent list, no compiler, no ratcheting edges, no double authority, simpler explainability, and a concrete path to deleting roughly 17k–20k obsolete lines after validation.

**Costs:** Guarded production reconciliation, explicit verification of intentional exception prerequisites, global cycle validation, and one app-wide activation. Strict lists intentionally offer at most one next issue within that list. Partial Thread coverage in lists requires a warning rather than a misleading guarantee.

**Rejected:** Retaining the existing Reading Plan graph/compilation, replacing its compiler with another edge compiler, inferring hard annual/crossover rules from labels, rebuilding all reader sequences from external CBLs, and treating an unchanged Roll state at technical cutover as success.

**Explicitly out of scope:** Adding further gate types, a graph database, a general workflow engine, or speculative schema layers.

### Read now selection acceptance

App-wide activation must exercise Queue **Read & Rate** (the `set-pending` API), not only dice Roll and override. Manual selection records the exact canonical Issue ID and number in its roll event, regardless of cached Thread frontier or blocked flags. Rating must consume that same offered Issue; undo restores its unread state. A successful selection response alone is insufficient acceptance evidence. Session skips and durable snooze backoff remain enforced before offering a manual selection; an explicit current-session unsnooze is recorded durably. Set current issue → rate and prerequisite recovery Read now → rate must also bind the exact canonical Issue, without consulting retired frontier flags or generated dependencies.
