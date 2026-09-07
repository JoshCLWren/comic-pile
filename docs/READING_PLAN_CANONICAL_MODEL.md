# Canonical Reader Execution Model - Decision Record

**Issue:** #1619 (child of #1612)  
**Original decision:** 2026-08-22  
**Reconciled:** 2026-09-07 under #2363 and #2366  
**Status:** Accepted, corrected  
**Decision owner:** JoshCLWren

## Context

`main` maintained two overlapping ordering concepts:

* **`continuity_plans`** (`ContinuityPlan` in `app/models/continuity_plan.py`): rich JSON document with `nodes` (`issue` | `crossover` | `thread`), `lanes` (ordered parallel sections), and `ordering_mode` (`informational` | `strict_sequential`).
* **`reading_orders`** (`ReadingOrder` + `ReadingOrderItem` in `app/models/reading_order.py`): a flat, thread-level ordered list.

Keeping both as peers recreates the competing-source-of-truth problem from #257: one system controls visible order while another controls blocking, with no single owner for what the reader intends next.

#1612 requires one reader-owned **Reading Plan** that can express ordered issues, series/runs, crossovers, sequential and parallel sections, informational ordering independent from blocking, explicit hard dependencies only when chosen, checkpoints/convergence, roles/provenance, and progress without raw graph editing.

The later CBL work in #1615 introduced another ambiguity by treating `DependencyGroupMembership.sequence_order` as an adopted source-backed order that Roll could consume directly. That would make ordered dependency-group membership a peer execution model beside the canonical Reading Plan. This 2026-09-07 reconciliation resolves that conflict.

## Decision

**`continuity_plans` remain the canonical reader-owned Reading Plan.**

Legacy `reading_orders`, CBL source lists, dependency-group membership order, and external template order are compatibility/source representations. They may feed or preserve evidence for a Reading Plan, but they do not independently own the reader's intent.

* The canonical reader-owned type is `ContinuityPlan` / `ContinuityPlanWrite` / `ContinuityPlanResponse`.
* Legacy `reading_orders` remain readable/importable compatibility data.
* A third peer ordering resource is forbidden.
* `DependencyGroupMembership.sequence_order` may preserve source/crossover ordering evidence and source position, but it is not an independent answer to what the reader intends to read next.
* New reader-facing ordering features extend or feed the canonical Reading Plan. They do not create a parallel execution model.

## Responsibilities

### Reading Plan

The Reading Plan owns reader intent:

* which material the reader chose to include or exclude;
* the reader's chosen order and parallel structure;
* roles/optionality and reader overrides;
* source/provenance snapshots needed to explain imported choices;
* explicit hard boundaries, checkpoints, convergence, or other constraints chosen by the reader.

The user-facing product should open and edit this concept when the reader asks what they are reading or wants to extend an existing project.

### CBL and other external sources

A CBL is source evidence and an import/adoption input.

* The CBL controls its own source order.
* The reader controls membership and whether/how that source is adopted into their Reading Plan.
* CBL source positions and provenance may remain stored in normalized source data and/or `DependencyGroupMembership.sequence_order` for traceability.
* After adoption, the reader-owned Reading Plan is the authority for the reader's chosen material and order.
* A source refresh produces a reviewable diff. It must not silently overwrite the adopted Reading Plan.

`sequence_order` therefore does **not** become a second Reading Plan and Roll must not treat it as an independent reader-intent source.

### Ordering versus blocking

Ordering is not automatically blocking.

A CBL can provide a source sequence without every adjacent source entry becoming a hard prerequisite. Adoption preserves the chosen order in the Reading Plan. Only explicit hard plan semantics compile into eligibility constraints.

This preserves #1613 and #257:

* informational order creates zero hard rules;
* strict sequential order may compile adjacent hard constraints;
* checkpoints/convergence compile only the constraints required by those explicit plan semantics;
* source adjacency, lane count, issue number, publication date, `Issue.position`, and `sequence_order` alone do not manufacture hard dependencies.

### Continuity rules and dependencies

Continuity rules are execution constraints, not a user-facing competing plan.

* Plan-owned hard semantics compile into rules with ownership/provenance so they can be replaced safely when the plan changes.
* Genuine standalone prerequisites may exist independently of a Reading Plan.
* Legacy dependencies must be classified during migration rather than blindly converted into plan order or preserved as permanent execution truth.
* Legacy CBL pairwise dependency expansion is not a valid representation of source order.

### Roll

Roll is the runtime selection authority.

Roll must ask one eligibility path what may be selected. That path evaluates the applicable hard constraints derived from the reader's Reading Plans plus legitimate standalone prerequisites. Roll must not independently reconcile Reading Plans, legacy Reading Orders, CBL `sequence_order`, dependency-group order, and legacy dependencies as separate sources of reader intent.

Once Roll selects an item, a second user-facing readiness gate must not re-litigate the same decision. This preserves the intended direction of #2104 without removing eligibility enforcement prematurely.

## Canonical contract

Source: `app/schemas/continuity_plan.py:ContinuityPlanWrite`

* **Issue-level entries without losing run context.** Nodes of type `issue` reference `Issue.id`; thread and crossover nodes remain supported.
* **Sequential order:** per-lane `position` with uniqueness enforced per lane. `strict_sequential` may require one ordered lane where appropriate.
* **Parallel lanes/sections:** lanes retain explicit order and node positions.
* **Optionality/roles, checkpoints/convergence:** these belong to the reader-owned plan and must not be inferred from source adjacency.
* **Ordering is not blocking.** Informational plans create zero hard rules.
* **Hard semantics compile to constraints.** The persisted/derived runtime representation used by Roll must be defined and audited under #2366 before further implementation resumes.

## Migration / compatibility strategy

1. **No silent semantic change.** Existing Reading Plans, Reading Orders, CBL evidence, memberships, read history, and continuity rules are not rewritten merely because this decision is clarified.

2. **Reading Orders remain readable.** They are compatibility/import data, not a second active source of reader intent.

3. **Reading Order adoption is explicit.** Adopting a legacy Reading Order creates/updates a Reading Plan without mutating the source order.

4. **Plan to Reading Order projection is export/compatibility only.** It must never become two-way synchronization between competing intent stores.

5. **CBL adoption feeds the Reading Plan.** Preview/reconciliation remains read-only. Commit applies only reader-approved material and records enough source position/provenance to explain the adoption. The final reader-owned intent is represented by the Reading Plan.

6. **`sequence_order` is source/crossover ordering evidence.** It may be kept for source provenance, crossover rendering, migration, and audit. It is not independently consulted as the reader's plan once canonical adoption exists.

7. **Roll consumes one eligibility result.** The implementation details are subject to the #2366 current-state audit because current production still contains legacy-backed constraints and partially implemented CBL behavior.

8. **Migration is incremental.** Production legacy dependencies are not deleted until equivalent intended behavior is represented canonically, verified through Roll, and covered by a rollback-safe migration.

## Consequences for open recovery work

* #1615 must be corrected so CBL adoption creates/updates canonical Reading Plan intent rather than establishing `sequence_order` as a peer execution model.
* #2127 must not be implemented from its current assumption that ordered dependency-group membership is sufficient as the final active reader order.
* #2128 must open the resulting Reading Plan after adoption rather than a separate source-backed reading-order product surface.
* #2129 must not migrate production onto `sequence_order` as a replacement execution authority before the canonical adoption/runtime path is proven.
* #2104 remains blocked until Roll's one eligibility path is verified.
* B.P.R.D. is the first end-to-end acceptance case under #2366.

## Alternatives rejected

* **Evolve `reading_orders` to rich plan semantics.** This preserves two overlapping concepts and loses richer plan semantics.
* **Make ordered dependency-group membership the active reader plan.** This recreates the competing-source problem and conflicts with #1619.
* **Introduce a third `reading_plans` resource.** Explicitly forbidden by #1619.
* **Encode every source adjacency as a hard dependency.** This violates the ordering-versus-blocking boundary and recreates the legacy CBL dependency explosion.
