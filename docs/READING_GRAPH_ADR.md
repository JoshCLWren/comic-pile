# ADR: Reader execution is Threads + Issues + issue dependencies

**Decision date:** 2026-09-16  
**Status:** Accepted  
**Decision owner:** JoshCLWren  
**Supersedes:** the runtime/storage portions of `docs/READING_PLAN_CANONICAL_MODEL.md`

## Context

ComicPile accumulated several overlapping representations of reading order and blocking:

- `Thread` plus ordered `Issue.position` and `next_unread_issue_id`
- issue-level `Dependency` rows
- `ContinuityPlan` JSON nodes, lanes, checkpoints, and convergence metadata
- `ContinuityRule` as a second generalized edge system
- `DependencyGroup` / crossover membership and historical `sequence_order`
- legacy `ReadingOrder` resources
- imported CBL source lists and user-authored custom CBL lists

The product language also drifted. Crossovers, Reading Orders, and Reading Plans became separate nouns even though the reader experiences them as the same kind of thing: an ordered reading project that may overlap and interact with other ordered reading projects.

Production data confirms that the runtime model can be simpler:

- current user Reading Plans are issue-node based;
- current persisted Continuity Rules are issue-to-issue;
- Thread progression already identifies the natural next unread issue in a series;
- the existing `Dependency` model is already a directed issue-to-issue prerequisite edge;
- historical CBL expansion created a very large number of dependency rows, showing that source order must not be naively expanded into redundant execution state.

ComicPile does not need a graph database or Postgres graph extension for this domain. The graph is small, relational, and constrained enough to model directly with ordinary Postgres tables.

## Decision

ComicPile's reader execution model is a directed graph whose executable nodes are Issues and whose explicit blocking edges are issue-level Dependencies.

### 1. Threads own natural series sequence and series state

A `Thread` owns an ordered set of `Issue` rows. `Issue.position` and `Thread.next_unread_issue_id` determine the natural series frontier.

For a normal series progression:

```text
Cable #63 -> Cable #64 -> Cable #65
```

ComicPile does not need dependency rows for every adjacent pair. The Thread already answers which issue is next.

Thread state may be active, completed, paused, or otherwise reader-controlled, but natural series order remains a Thread responsibility.

### 2. Dependencies are exceptional hard blockers between Issues

The canonical executable hard constraint is:

```text
source_issue_id -> target_issue_id
```

Meaning: the source issue must be read before the target issue is eligible.

Example:

```text
X-Men #95 -> Cable #75
```

Cable may naturally advance to #75, but Roll must not offer #75 while X-Men #95 is unread.

Multiple incoming dependencies mean all prerequisites must be satisfied. No special convergence runtime primitive is required.

```text
B -> D
C -> D
```

means D is blocked until both B and C are read.

### 3. Roll consumes one eligibility rule

Roll begins from each active Thread's natural frontier, normally `next_unread_issue_id`.

An issue is eligible when:

1. it is the current readable issue for its Thread; and
2. it has no unread prerequisite issue through the canonical dependency graph.

Roll does not independently evaluate CBL source order, crossover membership order, legacy Reading Orders, `DependencyGroupMembership.sequence_order`, or a second readiness API.

### 4. Reading Plans are user-owned reading projects, not a second runtime graph

The user-facing product noun is **Reading Plan**.

A Reading Plan is a named reader-owned project that can:

- include many Issues;
- overlap with other Reading Plans;
- preserve presentation/order information;
- reference hard Dependencies used by that plan;
- preserve source and import provenance;
- track progress from global Issue read state.

Crossovers and Reading Orders are not separate execution concepts. Existing product surfaces and historical data may identify a plan as a crossover or reading order for provenance or presentation, but they do not get separate runtime semantics.

Reading Plans remain independent. Entangled plans must not be collapsed into one mega-plan.

Example:

```text
Starman Reading Plan
    Starman #55
          |
          v
JSA Reading Plan becomes able to start
```

The plans remain separate, while the executable constraint resolves to issue-level prerequisite edges at their actual frontier.

### 5. Issues have global read state

Reading an Issue marks that Issue read everywhere it appears.

If JSA #5 appears in both a JSA Reading Plan and a DC event Reading Plan, reading JSA #5 once advances progress in both. Plan membership, position, provenance, and surrounding context are plan-local; Issue read state is not.

### 6. Executable edges may have many plan provenance links

One issue-to-issue Dependency may be relevant to multiple Reading Plans. That is valid and must not be treated as an ownership conflict.

The preferred normalized shape is conceptually:

```text
dependencies
  id
  source_issue_id
  target_issue_id

reading_plan_dependencies
  reading_plan_id
  dependency_id
```

The executable edge exists once. Zero, one, or many Reading Plans may reference it.

Do not encode single-owner semantics in a dependency note. Do not require two plans that share the same edge to create duplicate executable edges.

A polymorphic provenance table is not the default design. Prefer ordinary foreign-key join tables until a demonstrated non-Reading-Plan owner requires generalization.

### 7. Reading Plan membership should be relational

The target persistence model should represent plan-to-Issue membership using ordinary relational rows rather than making a JSON document the only canonical representation of membership.

Conceptually:

```text
reading_plans
reading_plan_issues
reading_plan_dependencies
reading_plan_sources
```

Exact column names and migration mechanics are deliberately left to the persistence audit, but database referential integrity is preferred over polymorphic or JSON-only ownership where practical.

### 8. CBLs are import/export templates

A CBL is a recipe or template for a Reading Plan. It is not Roll authority and it is not a second active reader-state model.

ComicPile should support:

- browsing/searching the configured CBL Git clone from the UI;
- selecting a CBL as a source template;
- reconciling template entries to canonical ComicPile Issues;
- importing all or part of a CBL into a Reading Plan;
- changing the resulting Reading Plan without mutating the source template;
- retaining source repository/path/revision/position provenance;
- detecting source updates and presenting a reviewable diff;
- exporting a Reading Plan to CBL when its current representation can be flattened into CBL order.

The configured local Git clone is a template library. Persisted CBL source tables may act as an index/cache of that library, but a tiny manually synchronized subset must not define the visible universe of available templates.

Source CBL adjacency does not automatically create hard dependency edges. Import/adoption chooses membership and order; only actual hard ordering requirements become executable Dependencies.

### 9. ContinuityRule is transitional

`ContinuityRule` currently duplicates executable edge semantics and adds generalized node and satisfaction types. The target model does not retain it as a peer runtime authority.

Existing useful rule semantics must be reduced to issue-level dependencies before removal. In particular:

- `item_read` issue-to-issue rules map directly to Dependencies;
- convergence is represented by multiple incoming Dependencies;
- historical crossover-node semantics must be audited before deletion, but current production data does not justify preserving crossover nodes as an executable type;
- provenance currently stored through rule notes must move to normalized plan/source relationships where needed.

No runtime cutover is authorized by this ADR alone. The audit issues created from this decision must identify exact reads, migration requirements, and delete/replace boundaries first.

### 10. Legacy crossover and reading-order structures are compatibility/provenance only

`DependencyGroup`, crossover membership, legacy `ReadingOrder`, custom CBL resources, and historical source-order artifacts may remain temporarily for migration, display, import/export, or provenance.

They must not regain independent Roll authority.

The useful reader-facing presentation from the existing Crossover UI may be reused for Reading Plans. That does not require preserving Crossover as a separate execution concept.

## Runtime invariant

The canonical runtime question is deliberately boring:

> For each active Thread, take its current unread Issue. Do not serve that Issue if any canonical prerequisite Issue is unread.

That rule is the center of the execution architecture.

## Acceptance examples

The simplified architecture must preserve these cases:

1. A Thread naturally advances issue by issue without creating adjacency Dependency rows.
2. Cable's next issue can be blocked by an unread X-Men issue.
3. Reading that X-Men prerequisite makes Cable's next issue eligible without changing Cable's natural sequence.
4. Starman #55 can gate the beginning of the separate JSA Reading Plan.
5. One Issue can belong to several Reading Plans.
6. One Dependency can be referenced by several Reading Plans without conflict.
7. Multiple incoming prerequisite edges require all source Issues to be read.
8. Reading an Issue updates progress in every Reading Plan containing it.
9. Roll never serves an Issue whose prerequisite edge is unsatisfied.
10. Importing or refreshing a CBL never silently overwrites a reader-modified Reading Plan.

## Consequences

This decision favors deletion and normalization over adding another abstraction layer.

Expected cleanup direction:

- preserve Thread/Issue natural progression;
- restore `Dependency` as the single executable hard-edge primitive;
- normalize Reading Plan membership and dependency provenance;
- remove `ContinuityRule` from runtime after equivalent intended constraints are migrated;
- remove `DependencyGroupMembership.sequence_order` from any execution path;
- retire legacy Reading Order/Crossover execution semantics after replacement UI and migration are proven;
- replace the current Custom CBL vs source-CBL split with a coherent template import/export experience;
- keep historical bulk CBL-generated dependencies inert until safe deletion can be proven rather than making their cleanup a prerequisite to architectural progress.

## Non-goals

This ADR does not:

- authorize destructive production migration;
- prescribe a graph database or graph extension;
- require materializing every natural Thread adjacency as a Dependency;
- require merging entangled Reading Plans;
- define final UI layout;
- define exact migration SQL;
- lift architecture hold #2363 by itself.

## Follow-up work

The next work is intentionally limited to three documentation-only audits, each delivered as a persisted repository document through a PR:

1. runtime simplification audit;
2. Reading Plan persistence migration design;
3. CBL template-library audit.

Those audits must treat this ADR as the frozen architecture contract. They may identify implementation work, but they must not implement it or reopen the product decision.
