# User 1 X-Men / Fantastic Four reconciliation

Read-only Neon (project `delicate-sea-51036121`, branch `br-silent-violet-ayobfez5`,
database `neondb`) on 2026-10-12. Production was not mutated. Every conclusion is
tagged **(a)** proven by source data, **(b)** already-recorded reader intent, or
**(c)** genuinely ambiguous.

Josh approves `001` / `002` before they run. This directory is the change set.

## 1. Why X-Men and Fantastic Four have no canonical Reading Plans

User 1 already has ContinuityPlans for Mignolaverse (6, strict), Absolute Universe
(20, strict), Ultimate Universe (19, strict), JSA (32, strict), and Hickman
Fantastic Four Stage 1 (25, informational). There is no plan named Late-90s X-Men
or Fantastic Four 001 - Early Years **(a)**.

The imported projects exist as CBL lists and inert `cbl-order` rows:

| List | Name | Hash prefix | Entries | Group | `cbl-order` rows |
| --- | --- | --- | --- | --- | --- |
| 9 | `[1997-2000] X-Men Era Ten Aftermath (UXRO)` | `5a221581…` | 210 | 4 (193 memberships, `sequence_order` 0) | 14,489 |
| 22 | `Fantastic Four 001 - Early Years` | `d3f597e1…` | 288 | 187 (252 memberships, `sequence_order` 0) | 31,616 |

`reading_plan_sources` has no row for list ids 9 or 22 **(a)**. Absolute / Ultimate
later went through CBL adoption commit; these two stopped at DependencyGroup +
`cbl-order:source:*` materialization **(a)**.

Ownership is user 1 on both lists, both groups, and the owned issue mappings
**(a)**. Optional entries: none recorded. CBL entries have no optional flag, and
no plan membership existed to carry `reader_optional` **(c)**.

Explicit hard restrictions that already exist and stay the Roll authority:

- Magneto War canonical deps 1577–1581 (semantic notes; source thread 312
  `X-Men: The Magneto War` issue 2357 = ComicVine TPB 688335) **(b)**
- Hunt for Xavier 1848–1852 **(b)**
- UXRO semantic-note canonical deps (e.g. 1869 GX #48 → Cable #64; 1863/1864
  Liberators; 1867 X-Force annual → #85) **(b)**
- Null-note canonical 1292 Uncanny #360 → X-Men #80; 1293 X-Men #87 → Magneto
  Rex #1 **(b)**
- FF Annual thread 18545 blocked by dep 2678 “Lee/Kirby Fantastic Four reading
  spine” FF (1961) #18 — already-recorded parent connection without merging
  annuals **(b)**

Step 14D classified the broader UXRO chronology as `reading_plan_order` (selected
sequencing, not independent necessity) **(c)** whether those semantic UXRO notes
should remain canonical blockers after cutover. This change set does not delete
them.

Informational plans are the recorded intent of “never adopted as a strict
ContinuityPlan.” CBL adjacency is source order, not a new inferred gate **(a)**.
Remaining ambiguity: Josh may later want those two lists strict **(c)**. Until
that is recorded, membership + already-recorded canonical deps is what the data
justifies.

## 2. Fantastic Four split: one series thread

Canonical thread **3166** `Fantastic Four (1961)` and split thread **18560**
`Fantastic Four (1970)` both map to ComicVine series 2045 and hold consecutive
numbers #1–102 and #103–231 with no overlap **(a)**.

| | 3166 (keep) | 18560 (reattach then delete empty thread) |
| --- | --- | --- |
| Issues | 102, pos 1–102, nums 1–102 | 125, pos 1–125, nums 103–231 |
| Read / unread | 19 / 83 | 0 / 125 |
| `issues_remaining` | stale 87 | 125 |
| Next unread | 23029 = #16 | 115395 = #103 |
| Mapping | 67 → identity 12970, conf 1.0 | 378 → same identity, conf 0.95 |

Issue rows are reassigned (`thread_id=3166`, `position = position + 102`).
Ids, `status`, `read_at`, ratings, events, and issue-level Dependencies stay.
Mapping 378 is dropped (unique `(thread_id, external_identity_id)`). 3166 next
unread stays #16. Combined totals: 227 issues, 208 remaining.

Out of scope: thread 3145 `Fantastic Four` (next ~#600) and completed
16706/16707 **(a)**.

Magneto War thread 312 (TPB 688335) and CBL single 18660 (ComicVine 126243) are
different publications **(a)** and are not merged **(c)** if a reader later
treats them as the same event.

## 3. Annuals, specials, Giant-Size stay their own threads

Not merged, not auto-gated:

- 18545 Fantastic Four Annual (1963) — 15 issues; blocked by recorded dep 2678
  until FF (1961) #18 is read **(b)**
- 18565 Giant-Size Fantastic Four (1974) — 3 issues; no unread canonical
  prereq **(a)**
- 18666 Giant-Size Super-Stars (1974) — 1 issue; no unread canonical prereq **(a)**
- X-Men annuals / specials in the 18 (Unlimited, Holiday, Cable 1999, Magneto
  War 1999 single, X-Force 1999, Dr. Doom '98, Champions '98, Dracula '98,
  GX 1999, X-Men 1999, Uncanny 1999) — own threads; connect through
  informational plan membership; Roll-gated only where a recorded canonical
  dep already exists **(a)** / **(b)**

No automatic merging. No mandatory gating for every appearance.

## 4. Fresh Roll eligibility (user 1, before cutover deploy)

Live queued active non-clone threads: **319** (Borat’s 75d530a workspace-style
snapshot had 320; one thread has left the queue since). Denormalized
`is_blocked=false`: **34**, matching Borat.

| Bucket | Count | After honest canonical refresh |
| --- | --- | --- |
| Flag + unread canonical dep | 50 | stay blocked |
| Flag + unread `cbl-order` only | 18 | become eligible unless merge removes the thread |
| Flag + no live unread dep (stale) | 217 | become eligible |
| Flag false + no live dep | 34 | stay eligible |
| Flag false + unread canonical | 0 | none newly blocked |

Borat predicted **52** by flipping only the 18 `cbl-order` flags and leaving
the 217 stale. Honest canonical refresh **without** the FF merge:
**269 eligible / 50 blocked**. After `001` merge, thread 18560 leaves the
queue and #103 is same-thread behind #16, so **268 eligible / 50 blocked /
318 queued**.

Newly blocked comics: **none**. Every current eligible frontier has no unread
canonical prerequisite.

### 4a. The 18 `cbl-order`-only flags (become eligible; no unread canonical prereq)

Live set differs from Borat’s 18: **dropped** 98 X-Men #80 and 3152 Magneto Rex
#1 (they now also have canonical deps 1292 / 1293); **added** 18565 Giant-Size
FF #2 and 18666 Giant-Size Super-Stars #1 **(a)**.

| Thread | Title / next | Why it becomes eligible |
| --- | --- | --- |
| 114 | Doom Patrol #9 | only inert `cbl-order`; same-thread #8 already read |
| 305 | Uncanny X-Men #360 | only inert `cbl-order`; UXRO list adjacency is not a recorded canonical dep |
| 3171 | Geiger #5 | only inert `cbl-order` |
| 3177 | Promethea #13 | only inert `cbl-order` |
| 18560 | FF (1970) #103 | only inert `cbl-order`; **after 001 this thread is gone** — #103 waits on combined-series order behind #16, not as its own Roll pick |
| 18565 | Giant-Size Fantastic Four #2 | no recorded canonical prereq; stays its own publication |
| 18595 | X-Men Unlimited #26 | no recorded canonical prereq |
| 18646 | Generation X Holiday Special #1 | no recorded canonical prereq |
| 18655 | Cable 1999 #1 | no recorded canonical prereq |
| 18660 | X-Men: Magneto War (1999) #1 | CBL single, not TPB 312; no unread canonical prereq on this issue |
| 18666 | Giant-Size Super-Stars #1 | no recorded canonical prereq |
| 18673 | X-Force 1999 #1 | no recorded canonical prereq |
| 18689 | X-Men / Dr. Doom '98 #1 | no recorded canonical prereq |
| 18699 | X-Force / Champions '98 #1 | no recorded canonical prereq |
| 18719 | Generation X / Dracula '98 #1 | no recorded canonical prereq |
| 18720 | Generation X 1999 #1 | no recorded canonical prereq |
| 18721 | X-Men 1999 #1 | no recorded canonical prereq |
| 18722 | Uncanny X-Men 1999 #1 | no recorded canonical prereq |

Informational plan adoption does not re-block any of these.

### 4b. Stale `is_blocked` with no live unread dependency (217)

Same actual prerequisite for every row: **none**. `Thread.is_blocked` was never
refreshed after historical blockers were read or after the canonical evaluator
landed. Families: Hellboy / B.P.R.D. / Abe Sapien / Lobster Johnson, JSA-adjacent
specials, Astro City shorts, some Ultimate mid-runs, WildC.A.T.s, cosmic
one-shots. Full id/title list: `stale_blocked_no_live_dep.json`.

Notable: Wildcats (89), JSA (1999–2006) (18818), The Ultimates (3185), Ultimate
X-Men (3193), Fantastic Four thread 3145 (different series; not the 1961/1970
split). Wild Hunt is not in this stale set; it remains in the 34 currently
eligible.

### 4c. Remain blocked — actual unread canonical prerequisite

50 threads. Representative recorded prereqs (not the 18-flag set):

- Cable #64 ← Generation X #48 (dep 1869, UXRO note) **(b)**
- X-Men #80 ← Uncanny #360 (dep 1292) **(b)**
- Magneto Rex #1 ← X-Men #87 (dep 1293) **(b)**
- X-Men: The Magneto War TPB ← X-Men #85 (dep 1577) **(b)**
- FF Annual #1 ← FF (1961) #18 (dep 2678) **(b)**
- Absolute Cassandra Cain #1 ← Absolute Catwoman #3 (dep 1723727) **(b)**
- Ultimate / Annihilation / Fourth World / ClanDestine / Deadpool recorded
  convergences **(b)**

Informational X-Men/FF plans do not add to this set. Strict thread-entry
compile is not applied to lists 9 and 22.

## 5. Apply order

1. Review this report.
2. Apply `001_ff_series_thread_merge.sql` on an approved connection.
3. Dry-run then apply `002` via `scripts/adopt_cbl_informational_plan.py` against
   a local clone URL (`ADOPT-CBL-INFORMATIONAL-NO-INFERRED-GATES`).
4. Refresh user 1 blocked status after 001 if denormalized flags should match
   the honest 268/50 picture before deploy.
5. Do not apply `scripts/reader_order_migration.py` for `x-men-era-ten` or
   `fantastic-four-early-years`.

Rollback: `001_ff_series_thread_merge_rollback.sql`, then delete the two
informational ContinuityPlans by name as documented in `002`.
