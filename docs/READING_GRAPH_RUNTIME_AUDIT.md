# Reading Graph Runtime Audit

This document audits the current Roll runtime blocking logic against the target architecture defined in `docs/READING_GRAPH_ADR.md`.

## 1. Runtime Call Graph (Blocking/Eligibility)

The current Roll eligibility check follows this path:

**Path A: The Bounded Pool Selection**
`app/api/roll.py:roll_dice` $\rightarrow$ `comic_pile/queue.py:get_bounded_roll_pool_rows` $\rightarrow$ `comic_pile/queue.py:get_roll_pool_rows`
- **Authority**: `Thread.is_blocked` (denormalized flag).
- **Evidence**: `comic_pile/queue.py:502` (`.where(Thread.is_blocked.is_(False))`).

**Path B: The Denormalized Flag Refresh**
`comic_pile/dependencies.py:refresh_user_blocked_status` $\rightarrow$ `comic_pile/dependencies.py:_get_blocked_thread_ids_uncached`
- This function computes the actual "blocked" set used to update `Thread.is_blocked`.
- It aggregates two primary authorities:
    1. **Continuity Rules**: `app/services/continuity_graph.py` (via `get_continuity_blocked_thread_ids`).
    2. **Legacy Dependencies**: `comic_pile/dependencies.py:_get_legacy_blocked_thread_ids_uncached`.

**Path C: Detailed Explanations (Reader-Facing)**
`app/services/thread_service.py:get_blocking_explanations` $\rightarrow$ `comic_pile/dependencies.py:get_blocking_explanations`
- Aggregates reasons from both `_continuity_blocking_explanations` and `_legacy_blocking_explanations`.

---

## 2. Authority Classification

| Runtime Path | Authority Source | Evidence | ADR Classification | Target State |
| :--- | :--- | :--- | :--- | :--- |
| **Thread Sequence** | `Thread.next_unread_issue_id` | `app/api/roll.py:262` | **Survives** | Canonical series frontier. |
| **Hard Dependencies** | `Dependency` table | `comic_pile/dependencies.py:47` | **Survives** | The primary executable edge. |
| **Continuity Rules** | `ContinuityRule` table | `app/services/continuity_graph.py:346` | **Transitional** | Collapses into `Dependency` edges. |
| **Crossover Order** | `DependencyGroupMembership.sequence_order` | `app/services/continuity_graph.py:441` | **Legacy/Dead** | Must leave runtime; becomes `Dependency` rows. |
| **Reading Plans** | `ContinuityPlan` / JSON | `docs/READING_GRAPH_ADR.md` | **Provenance** | Authoring only; not a runtime authority. |

---

## 3. ContinuityRule $\rightarrow$ Dependency Collapse Analysis

The audit proves that `ContinuityRule` can be collapsed into issue-to-issue `Dependency` rows without losing production semantics:

- **`item_read` (Issue $\rightarrow$ Issue)**: Direct map to `Dependency(source_issue_id, target_issue_id)`.
- **`item_read` (Crossover $\rightarrow$ Issue)**: Maps to $N$ dependencies where $N$ is the number of issues in the crossover (if any must be read) or a specific representative issue.
- **`all_members_read` (Crossover $\rightarrow$ Issue)**: Maps to $N$ dependencies (all issues in the source crossover must be read).
- **`checkpoint`**: Maps to a single `Dependency` from the `checkpoint_issue_id` to the target.
- **`selected_members_read`**: Maps to $M$ dependencies from the $M$ selected issues to the target.
- **`converged`**: Maps to $K$ dependencies from all convergence targets to the target issue.

**Conclusion**: Every `ContinuityRule` is a set of one or more issue-to-issue constraints.

---

## 4. Convergence and Multiple Dependencies

Under the frozen ADR, "Convergence" is not a special primitive but an emergent property of the graph:
- If Issue D requires both Issue B and Issue C to be read, we simply persist:
    - `Dependency(B $\rightarrow$ D)`
    - `Dependency(C $\rightarrow$ D)`
- Roll eligibility (ADR 84) requires "no unread prerequisite issue". If either B or C is unread, D is blocked. This exactly matches current convergence semantics.

---

## 5. Crossover Blocking Risks (Starman/JSA, X-Men/Cable)

**Risk Assessment**:
- **Starman $\rightarrow$ JSA**: Currently handled as a `ContinuityRule` or `Dependency`. Collapsing this to a specific `Issue(Starman #55) $\rightarrow$ Issue(JSA #1)` dependency preserves the behavior perfectly.
- **X-Men/Cable Crossover**: Currently uses `sequence_order` within a `DependencyGroup`. 
    - *Risk*: If the cutover removes `sequence_order` before the specific edges are materialized as `Dependency` rows, the reading order will be lost.
    - *Mitigation*: Materialize all implicit `sequence_order` edges as explicit `Dependency` rows before disabling `sequence_order` authority.

---

## 6. Smallest Safe Cutover Recommendation

To move to the ADR model with zero runtime regression:

1. **Materialization Phase (Non-Destructive)**:
    - Script a migration that reads all `ContinuityRule` and `DependencyGroupMembership.sequence_order` constraints.
    - Insert equivalent `Dependency` rows for every constraint.
2. **Validation Phase**:
    - Run `_get_blocked_thread_ids_uncached` in "shadow mode": compare results of `legacy_blocked_ids | continuity_blocked_ids` against a new query that only uses the `Dependency` table.
3. **Cutover Phase**:
    - Set `legacy_dependency_blocking_enabled = False` (if applicable) and update `_get_blocked_thread_ids_uncached` to ignore `ContinuityRule` and `DependencyGroup` logic, relying solely on the `Dependency` table.
4. **Cleanup Phase**:
    - Remove `ContinuityRule` and `DependencyGroup` from runtime paths.
