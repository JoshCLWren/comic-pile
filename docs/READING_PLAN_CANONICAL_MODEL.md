# Canonical Reader Execution Model — Decision Record

**Issue:** #1619 (child of #1612)  
**Date:** 2026-08-22  
**Status:** Accepted  
**Deciders:** Factory 47

## Context

`main` maintained two overlapping ordering concepts:

* **`continuity_plans`** (`ContinuityPlan` in `app/models/continuity_plan.py`): rich
  JSON document with `nodes` (`issue` | `crossover` | `thread`), `lanes`
  (ordered parallel sections), and `ordering_mode` (`informational` |
  `strict_sequential`). Nodes are persisted verbatim in `nodes_json` /
  `lanes_json` and evaluated for liveness via `app/continuity_plan_readiness.py`.
* **`reading_orders`** (`ReadingOrder` + `ReadingOrderItem` in
  `app/models/reading_order.py`): a flat, thread-level ordered list
  (`position` 1-based). Projection `continuity_plan → reading_order` existed
  in `app/services/reading_order_projection.py` and had to reject or flatten
  non-thread nodes.

Keeping both as peers recreates the competing-source-of-truth problem from
#257: one system (positions, lanes) controls visible order while another
(DAG dependency edges / `ContinuityRule`) controls blocking, with no single
owner for "what the reader intends next."

#1612 requires one reader-owned **reading plan** that can express ordered
issues, series/runs, crossovers, sequential and parallel sections,
informational ordering independent from blocking, explicit hard dependencies
only when chosen, checkpoints/convergence, roles/provenance (future), and
progress/readiness — without raw graph editing.

## Decision

**Evolve `continuity_plans` into the canonical reader-owned reading plan.**
Treat legacy `reading_orders` as **compatible views / import sources**.

Option 1 from #1619 is adopted; option 2 (evolving reading_orders to plan
semantics) and a third peer ordering resource are both rejected.

* The canonical type is `ContinuityPlan` / `ContinuityPlanWrite` /
  `ContinuityPlanResponse` (`app/schemas/continuity_plan.py`).
* `reading_orders` remain readable via `GET /api/v1/reading-orders/` and
  `GET /api/v1/threads/{id}/reading-orders` and writable only through
  explicit compatibility paths.
* A third ordering resource is forbidden. New ordering features extend the
  canonical plan schema; they do not create a parallel table.

## Canonical contract

Source: `app/schemas/continuity_plan.py:ContinuityPlanWrite`

* **Issue-level entries without losing run context.** Nodes of type `issue`
  reference `Issue.id`; `label` resolution in `continuity_plan_readiness.py`
  joins `threads` to surface `"Series #N"` without duplicating series data
  into the plan. Thread and crossover nodes remain supported but are not
  required to represent an issue-level multi-series plan.
* **Sequential order:** per-lane `position` with uniqueness enforced per
  lane. `strict_sequential` additionally requires one lane with contiguous
  `0..len-1` positions.
* **Parallel lanes/sections:** `lanes` ordered by `order`; evaluation order
  is `(lane.order, node.position, node.id)` (`continuity_plan_readiness.py`).
* **Optionality/roles, checkpoints/convergence:** `ordering_mode` is the
  only blocking signal today; informational plans create **zero**
  `ContinuityRule` rows (`app/api/continuity_plan.py:_replace_compiled_rules`).
  Roles, optionality, and convergence are reserved schema extensions (see
  #1613, #1616, #1614) and must not be inferred from lane count or adjacency.
* **Progress/readiness:** `GET /api/v1/continuity-plans/{id}/readiness`
  returns per-node `is_readable`/`is_complete`, `blockers`, `diagnostics`,
  and bounded chains, sharing the same rule evaluation as
  `app/continuity_readiness.py`.
* **Ordering is not blocking (#257 boundary).** Within-series issue
  progression is ordinary `position` ordering inside `Issue`; it is never
  encoded as `ContinuityRule` or `Dependency` edges unless the reader
  chooses `strict_sequential`. See guardrail below.

## Migration / compatibility strategy

1. **No silent semantic change.** Persisted `continuity_plans.rows`
   (`nodes_json`, `lanes_json`) and `reading_orders` items load unchanged.
   Validation (`ContinuityPlanWrite.validate_structure`) rejects malformed
   payloads before persistence; existing rows are not rewritten.

2. **Reading orders remain readable.** List and thread-scoped endpoints
   continue to serve legacy data verbatim. Frontend surfaces that previously
   consumed reading orders must not need a second fetch to determine the
   reader's intended next position once they adopt the canonical plan.

3. **Adoption (reading_order → plan) is explicit and lossless.**
   `POST /api/v1/continuity-plans/from-reading-order` imports one owned
   `ReadingOrder` into a new plan with one lane, mapping items ordered by
   `ReadingOrderItem.position` to `thread` nodes with `position` 0-based.
   The source reading order is not mutated. Duplicate thread_ids in the
   source are rejected as 409 with structured `duplicate_thread` detail so
   the caller deduplicates before adoption. The adopted plan is the new
   owner of the order intent; the reading order remains only as the legacy
   backup.

4. **Projection (plan → reading_order) is export-only.**
   `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview`
   and `.../project` remain as deterministic export/migration tooling
   (`app/services/reading_order_projection.py`). They reject `non_thread_node`
   and `duplicate_thread` as conflicts before mutation and never feed back
   into the plan (no two-way sync). New features must not treat projection
   as the bridge between two sources of reader intent.

5. **Queue / Roll consume one contract.**
   Queue ordering is `Thread.queue_position`; roll eligibility is
   `Thread.is_blocked` derived from `ContinuityRule` rows. Informational
   plans write zero rules, so they never block; `strict_sequential` writes
   exactly one rule per adjacent pair, each tagged with
   `continuity-plan:{plan_id}` for owned-compilation accounting. Reading
   orders are never consulted by `app/api/queue.py` or `app/api/roll.py`.

6. **Within-series progression stays out of the blocking graph.**
   `Issue.position` inside a thread is informational ordering. No
   `ContinuityRule` or `Dependency` is inferred from adjacent issue
   positions unless the user explicitly created a strict sequential plan.
   This preserves the #257 boundary: canonical order is the plan's lanes,
   cross-content blocking is only explicit rule edges.

## Consequences

* New reader-facing ordering UI targets the canonical plan exclusively.
* Reading-order projection stays available but is documented as deprecated
  export tooling.
* Future extensions (roles, optionality, provenance, checkpoints) extend
  the plan node/edge schema, not reading_order items.
* Tests must assert: duplicate/conflicting entries are rejected, issue-level
  multi-series plans round-trip and remain executable via readiness,
  cross-series boundaries do not spuriously block, and legacy orders
  round-trip + adopt without data loss.

## Alternatives rejected

* **Evolve `reading_orders` to rich plan semantics.** Would require widening a
  flat thread table to issue/crossover/lane semantics and migrating JSON
  semantics into relational items; continuity plans already carry the richer
  shape.
* **Introduce a third `reading_plans` resource.** Explicitly forbidden by
  #1619; would recreate the two-sources problem with a third.
