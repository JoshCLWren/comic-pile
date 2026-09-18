# Reading Graph Implementation Plan

**Date:** 2026-09-17  
**Status:** Proposed execution plan  
**Authority:** `docs/READING_GRAPH_ADR.md`  
**Inputs:** `docs/READING_GRAPH_PERSISTENCE_DESIGN.md`, corrected `docs/CBL_TEMPLATE_LIBRARY_AUDIT.md`, and the repaired `docs/READING_GRAPH_RUNTIME_AUDIT.md`

## Purpose

Persist the smallest implementation sequence for completing the Reading Plan / reading-order simplification without recreating the previous long recovery program.

This plan is intentionally short. It contains four implementation chunks. Each chunk should be executable as one focused issue or, only when evidence requires it, split into a very small number of independently shippable child issues.

Do not expand this into a multi-week numbered recovery program.

## Frozen architecture

The accepted architecture in `docs/READING_GRAPH_ADR.md` remains authoritative:

- `Thread` owns natural series issue order and current frontier state.
- `Issue` is the canonical executable comic node and owns global read state.
- `Dependency(source_issue_id -> target_issue_id)` is the canonical hard-blocking runtime edge.
- Natural Thread adjacency is not materialized as Dependency rows.
- Reading Plans are reader-owned collections and provenance over Issues and Dependencies, not a second execution engine.
- The same Issue and the same Dependency may participate in multiple Reading Plans.
- CBLs are external import/export templates and provenance, not runtime execution authority.
- Roll selects from active Thread frontiers and excludes any frontier Issue with an unread prerequisite.
- ContinuityRule, DependencyGroup ordering, Crossovers, and legacy Reading Orders must not remain independent runtime authorities after cutover.

## Gate before implementation

Two documentation gates must be trustworthy before implementation issues are cut from this plan:

1. The corrected CBL audit in PR #2545 must replace the inferred audit on `main`.
2. PR #2541 must be repaired so its runtime claims are grounded in current code and measured production data. In particular it must not infer active `DependencyGroupMembership.sequence_order` semantics where production has none, and it must convert only proven hard constraints into issue-level Dependencies.

The persistence design already merged through PR #2543 and is an input to this plan, not a separate implementation phase.

## Chunk 1: Normalize Reading Plan persistence

### Goal

Make Reading Plans directly reference canonical Issues and canonical Dependencies with ordinary relational joins, while preserving source/provenance metadata.

### Required outcome

- Reading Plan membership is normalized through a plan-to-Issue relation.
- Reading Plan hard-edge provenance is normalized through a plan-to-Dependency relation.
- One Issue may belong to many plans.
- One Dependency may be referenced by many plans without ownership conflict.
- CBL source path, revision, hash, and source position provenance can attach to a plan without becoming runtime authority.
- Global Issue read state remains unchanged.
- Existing plan display metadata may remain presentation-only where useful.

### Scope fence

- Do not switch Roll runtime in this chunk.
- Do not materialize natural Thread adjacency as Dependencies.
- Do not bulk-delete legacy data.
- Do not introduce polymorphic executable foreign keys or a graph database.
- Do not create another peer Reading Order resource.

### Completion proof

At minimum, prove:

- two plans can share one Issue,
- two plans can share one Dependency,
- deleting or editing one plan does not delete another plan's shared edge,
- convergence is representable as multiple incoming Dependencies,
- read state remains global and is reflected consistently across overlapping plans.

## Chunk 2: Collapse runtime onto Thread frontiers plus issue Dependencies

### Goal

Make one execution path authoritative for Roll eligibility.

### Target runtime

For each active Thread:

1. identify `next_unread_issue_id`,
2. inspect incoming issue-level Dependencies for that Issue,
3. if any source Issue is unread, the Thread is blocked,
4. otherwise its frontier Issue is eligible for Roll.

### Required outcome

- Convert only proven current hard `ContinuityRule` semantics into canonical issue-to-issue Dependencies.
- Treat convergence as multiple incoming Dependencies.
- Preserve genuine standalone prerequisites.
- Remove ContinuityRule / DependencyGroup ordering / legacy Reading Order semantics from Roll authority once equivalent intended behavior is proven.
- Keep reader-facing blocking explanations consistent with the same Dependency data.

### Scope fence

- Do not convert CBL or display adjacency into blockers merely because it is ordered.
- Do not reactivate the historical bulk `cbl-order:source:*` Dependency rows as canonical truth.
- Do not require historical dependency cleanup as a prerequisite to cutover if those rows can remain inert.
- Do not create a second shadow execution engine that survives beyond verification.

### Acceptance cases

- Starman #55 blocks the intended start of JSA.
- X-Men / Cable / X-Force crossover prerequisites block only where explicit hard issue edges require it.
- A target with two unread prerequisites remains blocked until both source Issues are read.
- A normal series advances by Thread position/frontier without adjacent Dependency rows.
- Roll never serves a frontier Issue with an unread prerequisite.

## Chunk 3: Complete the CBL template library using the existing schema

### Goal

Make the configured CBL Git mirror fully browsable and adoptable through the existing CBL source tables, with no new indexing subsystem unless future measurement proves one necessary.

### Measured constraints from the corrected audit

The corrected local audit measured:

- 1,706 `.cbl` files,
- 1,701 parseable lists,
- 333,605 ordered entries,
- approximately 8 seconds to parse the full mirror,
- 667,172 sequential identity-upsert awaits in the current full-sync path for only 85,467 distinct external identities.

The existing `cbl_sources`, `cbl_source_lists`, and `cbl_source_entries` schema is sufficient at this scale.

### Required outcome

- Batch and de-duplicate external identity persistence so a full mirror sync is practical.
- Canonicalize repository identity before the first full sync so `/mnt/bigdata/CBL-ReadingLists` and `JoshCLWren/CBL-ReadingLists` cannot create duplicate source universes.
- Resolve the orphan B.P.R.D. source row deliberately rather than losing it as an incidental sync side effect.
- Run a measured dry run and then a real full-mirror sync after the above hazards are fixed.
- Paginate/filter discovery so the UI can browse all persisted templates, including directory/publisher path organization.
- Preserve the existing adoption model: preview/reconcile, reader decision, commit into a Reading Plan with source provenance.

### Scope fence

- No `cbl_file_index` table.
- No duplicate content-metadata table.
- No TSVECTOR search table without a demonstrated query problem.
- No direct filesystem dependency for normal production UI requests. The Git clone is the source; the normalized database tables are the production projection used by the UI.
- CBL ordering is template order, not automatic runtime blocking.

## Chunk 4: Simplify the reader-facing product surface

### Goal

Present Reading Plans as the one reader-facing concept for reading projects/orders and make imported CBL material understandable and editable without exposing internal architecture nouns.

### Required outcome

- Reading Plan detail becomes the primary reader view.
- Reuse the strongest parts of the current Crossover detail experience for progress and ordered material presentation.
- Show natural Thread/series lanes using Issue position, with exceptional cross-series hard dependencies as the graph links that matter.
- Show what is available now versus blocked next.
- Support CBL browse/search/preview/adopt from the clone-backed library.
- Preserve the ability to adapt an imported plan without mutating its source template.
- Export a plan to CBL only when a linear representation is faithful, or clearly identify lossy flattening when the reader chooses it.

### Product language

Prefer reader language:

- Reading Plan / reading order
- blocked by
- available now
- source template

Do not make users reason about:

- ContinuityRule,
- convergence-rule objects,
- DependencyGroup sequence authority,
- compiler ownership markers,
- legacy Reading Orders as a competing product.

## Separate defects

Independent bugs discovered while auditing should remain independent issues. For example, the generated frontend OpenAPI document currently omits the live `/api/v1/custom-cbls` routes. Fix that as a normal defect, not as part of this architecture sequence.

## Definition of complete

This architecture simplification is complete when all of the following are true:

- Reading Plans persist through normalized Issue and Dependency relationships.
- Multiple Reading Plans can safely overlap and share hard edges.
- Roll has one eligibility authority based on Thread frontier plus issue-level Dependencies.
- ContinuityRule and DependencyGroup ordering are no longer runtime authorities.
- Normal Thread sequencing does not require Dependency rows.
- The full CBL mirror is available through the existing normalized source tables and is usable from the UI.
- CBL import/export remains template/provenance behavior rather than runtime authority.
- The primary reader workflow no longer exposes competing Reading Plan / Reading Order / Crossover execution concepts.

Historical cleanup can follow after this state is proven. Deleting every old compatibility row is not part of the critical path.
