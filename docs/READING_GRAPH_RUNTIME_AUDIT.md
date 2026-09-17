# Reading Graph Runtime Audit

This document audits the current Roll runtime blocking logic against the frozen architecture in
`docs/READING_GRAPH_ADR.md` (issue #2536).

It is documentation only. No runtime, schema, migration, or data change is authorized here, and
architecture hold #2363 is not lifted.

**Production measurement date:** 2026-09-17, against the Neon production database via read-only
`SELECT` statements. Every count below was re-measured for this revision; no count is inherited from
an earlier audit. Where an earlier audit's finding was reproduced, that is stated explicitly.

`docs/READING_GRAPH_PERSISTENCE_DESIGN.md` does not exist on this branch or on `main`, so this audit
does not rely on it.

---

## 1. Measured production facts

### 1.1 ContinuityRule population

3,317 rows total. Every row is `issue -> issue`. There are **no** crossover-typed rules in
production, in either the source or the target position.

| `source_type -> target_type` | Rows |
| :--- | ---: |
| `issue -> issue` | 3,317 |
| `crossover -> issue` | 0 |
| `issue -> crossover` | 0 |
| `crossover -> crossover` | 0 |

| `satisfaction_type` | Rows |
| :--- | ---: |
| `item_read` | 3,187 |
| `converged` | 130 |
| `all_members_read` | 0 |
| `checkpoint` | 0 |
| `selected_members_read` | 0 |

Supporting shapes:

- `checkpoint_issue_id IS NOT NULL`: **0 rows**.
- `continuity_rule_selected_members`: **0 rows**.
- Convergence payloads: 125 rules carry exactly one target, 5 carry two. Every payload element has
  `"type": "issue"`; no payload references a crossover.
- All 130 `converged` rules are self-referential (`source_id = target_id`). The `ck_continuity_rule_not_self`
  constraint permits this only for `converged`. The `source_id` on a convergence rule is therefore
  decorative — `app/services/continuity_graph.py:_evaluate_rule` reads the prerequisites from
  `convergence_targets`, never from `source_id`.

This reproduces the earlier audit's finding: production contains only issue-to-issue `item_read` and
`converged` rules, and no crossover-based rules.

### 1.2 ContinuityRule provenance

A database trigger, `trg_sync_legacy_dependency_to_continuity_rule` on `dependencies`, mirrors every
inserted or updated `Dependency` row into a matching `item_read` ContinuityRule carrying
`legacy_dependency_id`. This trigger is the reason the two tables overlap at all, and it is
essential context for the cutover.

| Origin | `satisfaction_type` | Note class | Rows |
| :--- | :--- | :--- | ---: |
| Mirrored from a Dependency row | `item_read` | `cbl-order*` | 1,228 |
| Mirrored from a Dependency row | `item_read` | `(null)` | 808 |
| Mirrored from a Dependency row | `item_read` | other semantic note | 344 |
| Rule-native (no Dependency row) | `item_read` | `continuity-plan:*` | 806 |
| Rule-native (no Dependency row) | `item_read` | other | 1 |
| Rule-native (no Dependency row) | `converged` | `continuity-plan:*` | 130 |

2,380 rules are mirrors of Dependency rows. 937 rules are rule-native, and 936 of those carry a
`continuity-plan:*` note, so the Reading-Plan-owned population is effectively the rule-native
population.

### 1.3 DependencyGroup ordering

| Measure | Value |
| :--- | ---: |
| `dependency_groups` | 155 |
| `dependency_group_memberships` | 3,521 |
| Memberships with non-null `sequence_order` | **0** |
| Groups with any ordered member | **0** |
| Issue-level memberships | 3,437 |
| Thread-level memberships | 84 |

This reproduces the earlier production inspection exactly. **`DependencyGroupMembership.sequence_order`
is not an active production runtime semantic.** No group in production declares an order.

The consequence is mechanical. `load_snapshot` builds `crossover_ordered_issue_ids` only from
memberships where `sequence_order IS NOT NULL` (`app/services/continuity_graph.py:241-254`). With
zero such rows, that map is empty for every group, `issue_crossover_positions` is empty, and
`crossover_order_blockers` returns `[]` for every issue. The crossover-ordering branch of Roll
blocking is live code that currently produces no blockers on production data.

The largest crossover group, `Late-90s X-Men Reading Order` (group 4, 215 memberships), has zero
ordered members. **The claim in the previous revision of this audit that the X-Men/Cable case relies
on `sequence_order` was wrong.** Section 6.2 shows the mechanism that actually supplies those edges.

No edges may be invented from empty `sequence_order`. There is nothing to materialize.

### 1.4 Dependency population

92,900 rows, partitioned cleanly by `note`:

| Note class | Rows | Mirrored into a ContinuityRule |
| :--- | ---: | ---: |
| `cbl-order:source:*` | 90,520 | **0** |
| `cbl-order*` (non-`source`) | 1,228 | 1,228 |
| `(null)` | 814 | 814 |
| Semantic note | 338 | 338 |

The 90,520 `cbl-order:source:*` rows were bulk-created on 2026-08-31 within a four-minute window
(`11:44:11Z` to `11:48:33Z`), before the mirroring trigger existed, which is why none of them has a
ContinuityRule. This bulk CBL population is 97.4% of the Dependency table and is the central safety
concern for the cutover (section 5).

### 1.5 Thread and blocked-state totals

15,147 threads; 11,769 have a `next_unread_issue_id`; 647 carry `is_blocked = true`.

---

## 2. Exact current Roll/blocking call graph

### 2.1 Roll consumes only the denormalized flag

Roll never computes blocking. It reads `Thread.is_blocked`.

`app/api/roll.py:173` calls `get_bounded_roll_pool_rows`, which delegates to
`comic_pile/queue.py:get_roll_pool_rows`. The pool filter is
`.where(Thread.is_blocked.is_(False))` at `comic_pile/queue.py:502`. The frontier is joined at
`comic_pile/queue.py:497` as `and_(Issue.id == Thread.next_unread_issue_id, Issue.status == "unread")`.

Other `is_blocked` consumers on Roll surfaces: `comic_pile/queue.py:341`, `:356`, `:446`, `:570`, and
`app/api/roll.py:1417`, `:1477`, `:1485`, `:1507`, `:1521`. Manual thread override rejects a blocked
thread at `app/api/roll.py:943`.

`Thread.next_unread_issue_id` is read for the selected thread at `app/api/roll.py:260-266` and
`:275`, and for the override path at `:968-975`.

One Roll query touches `DependencyGroupMembership`: the `route_labels_subq` at
`app/api/roll.py:1386-1401`. It aggregates `DependencyGroup.name` for display only. It is a
`SELECT` of group names, it does not filter the pool, and it does not read `sequence_order`. This is
presentation, not runtime authority.

### 2.2 The flag is refreshed by a single evaluator

`comic_pile/dependencies.py:_get_blocked_thread_ids_uncached` (line 27) is the only function that
decides blocked state. Everything else consumes its output:

- `refresh_user_blocked_status` (line 497) writes `Thread.is_blocked` in bulk.
- `update_thread_blocked_status` (line 486) writes a single thread.
- `get_blocked_thread_ids` (line 65) is the cached read wrapper.

Refresh callers: `app/api/issue.py` (lines 499, 590, 621, 667, 779, 844, 902 — every issue read-state
change), `app/api/rate.py:526`, `app/api/session.py:1200`, `app/api/dependency.py:469` and `:560`,
`app/services/thread_service.py:535`, and
`app/services/source_backed_reader_order_migration.py:600` and `:825`.

### 2.3 What `legacy_dependency_blocking_enabled` actually means

This flag does **not** mean what its name suggests, and the previous revision of this audit
misread it. From `comic_pile/dependencies.py:27-36`:

```python
async def _get_blocked_thread_ids_uncached(user_id: int, db: AsyncSession) -> set[int]:
    _invalidate_continuity_snapshot(user_id, db)
    if not get_app_settings().legacy_dependency_blocking_enabled:
        # After cutover, compiled ContinuityRule rows are the only Roll authority.
        # sequence_order must not contribute to eligibility.
        return await get_continuity_rule_blocked_thread_ids(user_id, db)
    continuity_blocked_ids = await get_continuity_blocked_thread_ids(user_id, db)
    legacy_blocked_ids = await _get_legacy_blocked_thread_ids_uncached(user_id, db)
    return legacy_blocked_ids | continuity_blocked_ids
```

| Flag value | Authorities evaluated |
| :--- | :--- |
| `True` (default, `app/config.py:163-170`) | ContinuityRules **plus** crossover `sequence_order` ordering (`issue_readiness`), unioned with raw Dependency rows |
| `False` | ContinuityRules **only** (`issue_rule_readiness`); raw Dependency rows are dropped entirely, and `sequence_order` is excluded |

Setting the flag to `False` **removes** the Dependency table from Roll authority and makes
`ContinuityRule` the sole authority. That is the opposite of the ADR target, which makes Dependency
canonical and retires ContinuityRule. **The cutover must not set this flag to `False`.** It is a
switch between two pre-ADR designs, not an ADR cutover switch.

`scripts/reader_order_migration.py:427-430` confirms the intent: the flag was built to hand Roll to
compiled ContinuityRules, not to Dependencies.

No deployment configuration sets `LEGACY_DEPENDENCY_BLOCKING_ENABLED`; only `comic_pile/dependencies.py`,
`app/config.py`, `scripts/reader_order_migration.py`, and recovery docs reference it. The Pydantic
default `True` therefore applies in production.

**Production value verified against data, not config.** Reconstructing each candidate set in SQL:

| Candidate set | Threads |
| :--- | ---: |
| ContinuityRules only (flag `False`) | 617 |
| Raw Dependency rows only | 411 |
| Union of both (flag `True`) | 645 |
| Persisted `Thread.is_blocked = true` | 647 |

The union has zero members missing from the persisted set. Rules-only would leave 30 persisted
blocked threads unexplained. Production therefore runs with the flag `True`. The two persisted
threads outside the union are stale flags awaiting the next refresh, not a third authority.

### 2.4 Explanations use a parallel path with matching gates

Reader-facing explanations do not reuse the blocked-set functions. `app/services/thread_service.py:658`
calls `comic_pile/dependencies.py:get_blocking_explanations` (line 305), which composes
`_continuity_blocking_explanations` (line 208) and `_legacy_blocking_explanations` (line 120). The
batch variant is `get_blocking_explanations_batch` (line 320).

These read the same flag at lines 228, 271, 314, and 330, and select the same
`issue_rule_readiness` / `issue_readiness` pair. The path is separate but the gating is consistent,
so explanations and eligibility agree today. The cutover must change both, or explanations will
describe blockers Roll no longer enforces.

---

## 3. Runtime authority classification

| Authority | Evidence | ADR classification | Target state |
| :--- | :--- | :--- | :--- |
| `Thread.next_unread_issue_id` | `comic_pile/queue.py:497`; `app/api/roll.py:260-266` | Survives unchanged | Canonical series frontier |
| `Dependency` rows | `comic_pile/dependencies.py:39-61` | Becomes the sole hard edge | Canonical executable edge |
| `ContinuityRule` (`item_read`, `converged`) | `app/services/continuity_graph.py:346-424` | Transitional | Reduces to Dependency rows (section 4) |
| `ContinuityRule` (`all_members_read`, `checkpoint`, `selected_members_read`) | `app/services/continuity_graph.py:359-388` | Non-production compatibility semantics | Zero production rows; disposition required before table deletion, not before cutover |
| `DependencyGroupMembership.sequence_order` | `app/services/continuity_graph.py:441-489`; `:241-254` | Legacy/dead | Zero production rows; already inert. Remove the code path; nothing to migrate |
| `DependencyGroup` name labels on Roll | `app/api/roll.py:1386-1401` | Presentation/provenance | Unaffected by cutover |
| `legacy_dependency_blocking_enabled` | `comic_pile/dependencies.py:30` | Legacy/dead | Delete the branch; do not flip it (section 2.3) |
| `trg_sync_legacy_dependency_to_continuity_rule` | `dependencies` table trigger | Transitional | Drop after ContinuityRule leaves runtime |
| Reading Plans / `ContinuityPlan` | `docs/READING_GRAPH_ADR.md` §4 | Provenance | Authoring only; never a runtime authority |

No legacy `ReadingOrder` table participates in the current blocked-set calculation. The only
`ReadingOrder`-adjacent runtime code is
`app/services/source_backed_reader_order_migration.py`, which calls the evaluator rather than
supplying an authority to it.

---

## 4. Production ContinuityRule to Dependency reduction

Only two rule forms exist in production, so only two reductions are required.

### 4.1 `item_read` (3,187 rows)

`_evaluate_rule` blocks the target while the single `source_id` issue is unread
(`app/services/continuity_graph.py:351-353`):

```text
A -> B
```

becomes:

```text
Dependency(A, B)
```

2,380 of these rules are already mirrors of existing Dependency rows, so they need nothing. 807 are
rule-native and have no Dependency row.

### 4.2 `converged` (130 rows)

`_evaluate_rule` blocks the target while any entry in `convergence_targets` is unread
(`app/services/continuity_graph.py:371-383`). Under the ADR this is not a primitive; it is several
incoming edges. For a rule on D with targets B and C:

```text
B -> D
C -> D
```

becomes:

```text
Dependency(B, D)
Dependency(C, D)
```

The 130 rules expand to 135 edges (125 single-target, 5 two-target). ADR §2 already states that
multiple incoming dependencies require all prerequisites, which is exactly the `converged`
semantics, so this reduction is lossless. The 125 single-target rules are degenerate convergences
already equivalent to a plain `item_read` edge.

### 4.3 Measured gap

| Reduction | Edges required | Already present as a Dependency row | Must be persisted |
| :--- | ---: | ---: | ---: |
| Rule-native `item_read` | 807 | 0 | 807 |
| `converged` expanded | 135 | 0 | 135 |
| **Total** | **942** | **0** | **942** |

942 Dependency rows fully close the gap. That is the entire data-side scope of the cutover.

### 4.4 Non-production compatibility semantics

`all_members_read`, `checkpoint`, and `selected_members_read` are implemented in `_evaluate_rule` and
exercised by tests, but have **zero production rows**, zero `checkpoint_issue_id` values, and zero
`continuity_rule_selected_members` rows. Crossover-typed source and target nodes likewise have zero
production rows.

These are listed here as **non-production compatibility semantics requiring disposition before the
`continuity_rules` table is deleted**. They are not migration requirements and no conversion is
designed for them. Designing crossover or checkpoint conversions now would be speculative work
against data that does not exist. The previous revision of this audit claimed to "prove" that every
rule form collapses; that conflated theoretical model capability with production fact. The accurate
claim is narrower: every rule form **present in production** collapses, as shown in 4.1 and 4.2.

---

## 5. Historical Dependency safety boundary

The cutover makes Dependency rows authoritative. 97.4% of that table is historical CBL bulk output,
so "make Dependency authoritative" must not mean "make all 92,900 rows authoritative".

| Class | Rows | Disposition at cutover |
| :--- | ---: | :--- |
| Canonical edges derived from proven hard rules (the 942 from section 4.3) | 942 | Persist; authoritative |
| Legitimate standalone prerequisites: semantic-note and null-note rows, all mirrored into rules and already live | 1,152 | Keep; authoritative |
| Adopted CBL order already promoted to rule authority (`cbl-order*`, non-`source`, all mirrored) | 1,228 | Keep; authoritative |
| Historical CBL adjacency (`cbl-order:source:*`, never mirrored) | 90,520 | **Must remain inert** |

The boundary is clean and machine-checkable: a row is canonical if and only if
`note IS NULL OR note NOT LIKE 'cbl-order:source:%'`. The 90,520 excluded rows are exactly the rows
with no ContinuityRule mirror, so "has a rule mirror or is newly persisted by section 4.3" is an
equivalent and independently verifiable test.

### 5.1 The one measured behavior change

These historical rows are not currently inert. Because the flag is `True`,
`_get_legacy_blocked_thread_ids_uncached` joins the whole Dependency table, so CBL adjacency rows
block threads today:

| Set | Threads |
| :--- | ---: |
| Blocked by raw Dependency rows (all classes) | 411 |
| Blocked by raw Dependency rows excluding `cbl-order:source:*` | 383 |
| Blocked by `cbl-order:source:*` rows | 38 |
| Blocked **only** by `cbl-order:source:*` rows | 28 |

Excluding the historical class therefore unblocks 28 threads. Full comparison of the current
evaluator against a Dependency-only evaluator over the canonical set:

| Set | Threads |
| :--- | ---: |
| Current effective blocked set (rules ∪ raw Dependencies) | 645 |
| Proposed canonical Dependency-only blocked set | 617 |
| Threads that would unblock | 28 |
| Threads that would newly block | **0** |

Zero new blocks means the cutover cannot surprise the reader with a comic that suddenly becomes
unavailable. The 28 unblocking threads are all annuals, one-shots, and first issues — `Marvel
Two-in-One Annual (1976) #1`, `Giant-Size Fantastic Four (1974) #2`, `X-Men: Magneto War (1999) #1`,
`Generation X Holiday Special (1998) #1`, and similar. These are CBL source adjacency artifacts, not
reader-authored prerequisites, and unblocking them is the intended correction rather than a
regression. ADR §8 is explicit that source CBL adjacency does not create hard dependency edges.

Deleting the 90,520 rows is **not** on the critical path. They become inert the moment the evaluator
filters to the canonical set, which matches the ADR's direction to keep historical bulk CBL
dependencies inert until safe deletion can be proven separately.

---

## 6. Acceptance-case evidence

### 6.1 Starman #55 gates the JSA Reading Plan

Dependency 2580, `Starman #55 -> JSA (Robinson / Goyer / Johns) All-Star Comics #1`, note
`"Launch the Robinson/Goyer/Johns JSA path alongside Starman after Starman #55."` It is mirrored into
ContinuityRule 2097 (`item_read`, `legacy_dependency_id = 2580`).

Source `Starman #55` is unread. The target is thread 18539's `next_unread_issue_id`, and that thread
carries `is_blocked = true`. The edge is already a Dependency row in the canonical class, so it
survives the cutover untouched and continues to block from both authorities.

### 6.2 X-Men / Cable / X-Force crossover blocking

The mechanism is **Dependency rows**, not `sequence_order`. Group 4 `Late-90s X-Men Reading Order`
has 215 memberships and zero ordered members, so it contributes nothing to eligibility.

The live edges are explicit `UXRO Era Ten`-noted Dependency rows, each mirrored into an `item_read`
rule:

| Dependency | Edge | Source status |
| ---: | :--- | :--- |
| 1869 | `Generation X #48 -> Cable #64` | unread |
| 1870 | `Cable #64 -> Uncanny X-Men #365` | unread |
| 1878 | `Cable #71 -> Uncanny X-Men #372` | unread |
| 1882 | `Uncanny X-Men #377 -> Cable #76` | unread |
| 1883 | `Cable #76 -> X-Men #97` | unread |
| 1885 | `Uncanny X-Men #378 -> Cable #77` | unread |
| 1886 | `Cable #77 -> X-Men #98` | unread |
| 1889 | `Uncanny X-Men #379 -> Cable #78` | unread |
| 1890 | `Cable #78 -> X-Force #101` | unread |

This is the ADR §2 example (`X-Men #95 -> Cable #75`) already persisted in the canonical form. All
rows are in the canonical class, so the cutover preserves this case exactly. The risk described in
the previous revision — losing reading order when `sequence_order` is removed — does not exist,
because no `sequence_order` value exists to lose.

### 6.3 Convergence with multiple prerequisites

Five production rules carry two prerequisites each. Example: rule 714501, target
`Astro City: Silver Agent #1`, targets issues 52322 and 52323, note `continuity-plan:21`. Others
gate `Secret Origins #33`, `Justice League America #31`,
`Planetary/The Authority: Ruling the World #1`, and `Silver Surfer / Warlock: Resurrection #1`.

None has a Dependency row today. After section 4.2 persists both edges per rule, the target is
blocked while either prerequisite is unread — identical to `_evaluate_rule`, which accumulates every
unread convergence target. This is section 4.3's measured contribution and is included in the
"zero newly blocked" result.

### 6.4 Normal same-Thread progression

No Dependency row is required for `Cable #63 -> #64 -> #65`. `get_roll_pool_rows` joins
`Issue.id == Thread.next_unread_issue_id` with `Issue.status == "unread"`
(`comic_pile/queue.py:497`), so ordinary advancement comes from `Issue.position` and
`next_unread_issue_id` alone. Of 92,900 Dependency rows, the canonical set retains 2,380 plus 942
new rows — 3,322 edges against 11,769 active frontiers — confirming that adjacency is not
materialized and must not become so.

---

## 7. Smallest safe cutover

Four steps. Each is independently verifiable, and the measurements in sections 4.3 and 5.1 already
supply the expected result for every one.

**Step 1 — Persist the 942 canonical edges.** Insert one Dependency row per rule-native `item_read`
rule (807) and one per `converged` prerequisite (135), associating each with its owning Reading Plan.
The mirroring trigger will create matching rules, which is harmless because those edges are already
rule authority. No existing row is modified and no row is deleted.

**Step 2 — Verify the Dependency-only calculation in shadow mode.** Compute the blocked set from
Thread frontier plus incoming Dependency rows restricted to
`note IS NULL OR note NOT LIKE 'cbl-order:source:%'`, and compare against the live evaluator. The
expected result is already measured: 617 blocked, 0 newly blocked, 28 unblocked, all 28 being CBL
adjacency artifacts as listed in section 5.1.

**Step 3 — Switch the single blocking calculation.** Replace the body of
`_get_blocked_thread_ids_uncached` with the canonical query and delete the
`legacy_dependency_blocking_enabled` branch rather than flipping it (section 2.3). Apply the same
change to `get_blocking_explanations` and `get_blocking_explanations_batch` so explanations keep
matching eligibility (section 2.4). Roll itself needs no change: it already reads only
`Thread.is_blocked` and `next_unread_issue_id`.

**Step 4 — Remove ContinuityRule and DependencyGroup runtime authority.** After Step 3 verifies,
delete `app/continuity_blocking.py`'s blocked-set helpers, the `crossover_order_blockers` path, and
`_continuity_blocking_explanations`, then drop `trg_sync_legacy_dependency_to_continuity_rule`.
Retaining the `continuity_rules` and `dependency_group_memberships` tables for provenance is fine;
the ADR requires only that they stop being Roll authorities.

Not on the critical path: deleting the 90,520 historical rows (they are inert once Step 3 filters
them), resolving the three non-production rule forms in section 4.4 (required only before the
`continuity_rules` table is dropped), and any `sequence_order` migration (there is no data to
migrate).

The end state is the ADR runtime invariant:

```text
Thread.next_unread_issue_id
        +
incoming canonical Dependency rows
        =
Roll eligibility
```
