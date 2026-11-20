# User 1 X-Men / Fantastic Four reconciliation

Read-only Neon (project `delicate-sea-51036121`, branch `br-silent-violet-ayobfez5`,
database `neondb`) on 2026-10-12. **Production was not mutated. Both prod changes
are held.** No Neon clones or branches: production read-only preflight only, with
reviewed transactional SQL and documented rollback.

Every conclusion is tagged **(a)** proven by source data, **(b)** already-recorded
reader intent, or **(c)** genuinely ambiguous.

Harvy reproduces the Roll forecast with `forecast_roll_eligibility.sql`
(same pair selection as `c25530000001` / `canonical_backfill._rule_native_pairs`).

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

**Never having adopted a strict plan is not evidence Josh chose informational
mode.** Informational adoption is held. Hard restrictions that already exist and
stay the Roll authority:

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

Optional entries: none recorded. CBL entries have no optional flag **(c)**.

Step 14D classified the broader UXRO chronology as `reading_plan_order` (selected
sequencing, not independent necessity) **(c)** whether those semantic UXRO notes
should remain canonical blockers after cutover. This change set does not delete
them.

## 2. Fantastic Four split: one series thread (goal approved, SQL rewritten, held)

Canonical thread **3166** `Fantastic Four (1961)` and split thread **18560**
`Fantastic Four (1970)` both map to ComicVine series 2045 and hold consecutive
numbers #1–102 and #103–231 with no overlap **(a)**.

| | 3166 (keep) | 18560 (reattach then delete empty thread) |
| --- | --- | --- |
| Issues | 102, pos 1–102, nums 1–102 | 125, pos 1–125, nums 103–231 |
| Read / unread | 19 / 83 | 0 / 125 |
| Issue ids | (existing) | **115395–115519** consecutive; `position = id - 115394` |
| `issues_remaining` | stale 87 | 125 |
| Next unread | 23029 = #16 | 115395 = #103 |
| Mapping | 67 → identity 12970, conf 1.0 | 378 → same identity, conf 0.95 |

`001_ff_series_thread_merge.sql` is one guarded transaction:

- **`SELECT … FOR UPDATE` first**: threads 3166/18560, their issues (and split
  ids 115395–115519), every `pg_constraint` FK child of `threads.id`, plus
  non-FK referencing rows (`events.selected_thread_id`, session snooze/skip
  JSON, `blocked_by_thread_ids`, polymorphic `continuity_rules` thread
  endpoints, `tag_assignments` `Thread` targets, plan `nodes_json` thread
  nodes). Guards run only after those locks are held.
- Preflight records `row_to_json` of thread 18560 and mapping 378 and asserts
  them equal to `001_ff_series_thread_merge_recorded.json`. Also asserts 3166
  restore fields (title, format, `reading_progress`, next unread, totals,
  queue, status, owner). Counts, no number overlap, consecutive split ids, and
  **every FK to `threads.id`**. Abort if anything unexpected appears, including
  polymorphic thread refs.
- Issue rows are reassigned (`thread_id=3166`, `position = position + 102`).
  Ids, `status`, `read_at`, ratings, events, and issue-level Dependencies stay.
- Mapping 378 is dropped. 3166 next unread stays #16. Combined totals: 227
  issues, 208 remaining. `reading_progress` is left as the recorded live value.
- **No persistent backup tables.**

Rollback (`001_ff_series_thread_merge_rollback.sql`) restores thread 18560 and
mapping 378 with `jsonb_populate_record` from that receipt, then asserts
`row_to_json` of the restored rows equals the recorded JSON. Split issues use
the deterministic mapping (`id BETWEEN 115395 AND 115519`, original
`position = id - 115394`). 3166 `reading_progress` is restored from the
recorded canonical receipt, not hard-coded. Both scripts `SET LOCAL TimeZone
= 'UTC'` so timestamptz receipts compare as `+00:00`.

Moved-issue references (dependencies, `reading_plan_issues`, events on ids
115395–115519) are fingerprinted from locked live rows at merge execution
and persisted into `prod_changeset_001_ff_moved_refs_receipt`. The
2026-10-12 preflight snapshot in `001_ff_series_thread_merge_recorded.json`
(`moved_issue_refs`, 23,625 `cbl-order` rows) is documentation only.
Rollback **reads that merge-time receipt** and refuses only on drift from
it (new, removed, or changed rows), not on the mere presence of the
pre-existing `cbl-order` rows. The receipt table is a one-row fingerprint,
not an issue backup.

Out of scope: thread 3145 `Fantastic Four` (next ~#600) and completed
16706/16707 **(a)**.

Magneto War thread 312 (TPB 688335) and CBL single 18660 (ComicVine 126243) are
different publications **(a)** and are not merged **(c)** if a reader later
treats them as the same event.

## 3. Annuals, specials, Giant-Size stay their own threads

Not merged, not auto-gated:

- 18545 Fantastic Four Annual (1963) — 15 issues; blocked by recorded dep 2678
  until FF (1961) #18 is read **(b)**
- 18565 Giant-Size Fantastic Four (1974) — 3 issues; no unread live prereq after
  cutover **(a)**
- 18666 Giant-Size Super-Stars (1974) — 1 issue; no unread live prereq after
  cutover **(a)**

No automatic merging. No mandatory gating for every appearance.

## 4. Corrected Roll eligibility (user 1, before FF merge, simulating `c25530000001`)

The previous report treated 217 blocked threads as stale because they have no
Dependencies **today**. That was wrong. Pending migration `c25530000001` backfills
native `item_read` ContinuityRules and converged prerequisites into canonical
Dependencies, then the evaluator refreshes `is_blocked`. Historical `cbl-order:%`
rows stay inert.

Live queued active threads: **320** (includes clone thread 1019018). Denormalized
`is_blocked=false` today: **34**.

| Bucket | Count | After backfill + blocked-status refresh |
| --- | --- | --- |
| Unread existing canonical Dependency | 50 | stay blocked |
| Unread native `item_read` to convert (not already canonical) | 189 | stay blocked |
| Unread native converged prereq to convert (not already canonical/item_read) | 29 | stay blocked |
| Flagged blocked, only inert `cbl-order` | 18 | newly available |
| Currently eligible, no unread live prereq | 34 | stay eligible |
| Currently eligible + unread live prereq | 0 | none newly blocked |

**268 blocked / 52 rollable.** Exactly **18 newly available**. **0 newly blocked.**
50 + 189 + 29 = 268. 34 + 18 = 52.

Reproduce: `forecast_roll_eligibility.sql` or
`app.services.roll_cutover_forecast.forecast_roll_eligibility`.

The approved FF merge is **not** in this forecast. After `001`, thread 18560
leaves the pool and #103 is same-thread behind #16, so the 18 become 17 and
rollable becomes 51 on 319 queued. That SQL is held.

### 4a. The 18 newly available — actual post-cutover prerequisite: none

Each frontier has unread `cbl-order` adjacency only. No unread canonical
Dependency, no unread native `item_read`, no unread converged prereq **(a)**.

| Thread | Title / next | Actual prerequisite after cutover |
| --- | --- | --- |
| 114 | Doom Patrol #9 | none (inert `cbl-order` only; same-thread #8 already read) |
| 305 | Uncanny X-Men #360 | none (inert UXRO `cbl-order` adjacency is not a live rule) |
| 3171 | Geiger #5 | none (inert `cbl-order` only) |
| 3177 | Promethea #13 | none (inert `cbl-order` only) |
| 18560 | FF (1970) #103 | none today; **after held `001` this thread is gone** — #103 waits on combined-series order behind #16 |
| 18565 | Giant-Size Fantastic Four #2 | none |
| 18595 | X-Men Unlimited (2000) #26 | none |
| 18646 | Generation X Holiday Special (1998) #1 | none |
| 18655 | Cable 1999 (1999) #1 | none |
| 18660 | X-Men: Magneto War (1999) #1 | none on this CBL single; TPB thread 312 is a different publication |
| 18666 | Giant-Size Super-Stars (1974) #1 | none |
| 18673 | X-Force 1999 (1999) #1 | none |
| 18689 | X-Men / Dr. Doom '98 (1998) #1 | none |
| 18699 | X-Force / Champions '98 (1998) #1 | none |
| 18719 | Generation X / Dracula '98 (1998) #1 | none |
| 18720 | Generation X 1999 (1999) #1 | none |
| 18721 | X-Men 1999 (1999) #1 | none |
| 18722 | Uncanny X-Men 1999 (2000) #1 | none |

### 4b. Remain blocked — actual unread live prerequisite

268 threads: 50 existing canonical + 189 native `item_read` the backfill
converts + 29 native converged the backfill converts. Representative recorded
prereqs **(b)**:

- Cable #64 ← Generation X #48 (dep 1869, UXRO note)
- X-Men #80 ← Uncanny #360 (dep 1292)
- Magneto Rex #1 ← X-Men #87 (dep 1293)
- X-Men: The Magneto War TPB ← X-Men #85 (dep 1577)
- FF Annual #1 ← FF (1961) #18 (dep 2678)
- Absolute Cassandra Cain #1 ← Absolute Catwoman #3 (dep 1723727)

The 189/29 are not stale flags. They are native ContinuityRules that
`c25530000001` persists as canonical edges.

### 4c. Newly blocked

**None** of today's 34 eligible frontiers has an unread canonical, item_read, or
converged prerequisite.

## 5. X-Men / FF identity resolution (do not adopt)

Full table: `cbl_identity_resolution.json`. Report CLI:
`scripts/report_cbl_source_identity_resolution.py` (read-only, explicit
`--database-url`).

| List | Entries | Unique confirmed **(a)** | Volume-resolved **(a)** | Duplicate copies **(c)** | Unmatched **(c)** |
| --- | --- | --- | --- | --- | --- |
| 9 Era Ten | 210 | 129 | 2 | 51 | 28 |
| 22 FF Early Years | 288 | 238 | 0 | 14 | 36 |

Volume-resolved (exactly one candidate Thread maps to the CBL ComicVine series):

- List 9 pos 90 `X-Men / Dr. Doom '98` #1 (CV 178128 / series 26316) → issue
  116603 on thread 18689; reject annual-on-98 issue 2359 **(a)**
- List 9 pos 129 `X-Men 1999` #1 (CV 156744 / series 60463) → issue 116775 on
  thread 18721; reject annual-on-98 issue 2360 **(a)**

Duplicate copies (same ComicVine issue on parallel owned threads; **never pick
lowest issue id**):

- Era Ten: X-Force 102 vs 16970; Uncanny 305 vs 16935; X-Men 98 vs 16975;
  Generation X 84 vs 16726; Excalibur 100 vs 16697; Team X 3147 vs 16873;
  Cable 76 vs 16650 **(c)** which copy is the reading copy
- FF Early Years: #1–10 on Masterworks 107 + 3166 + completed Vol.1 16706;
  #23/48/49/50 on 3166 + 16706 **(c)** floppy vs reprint vs completed clone

Unmatched (ComicVine ids known, no owned confirmed mapping; **not omitted**):

- Era Ten: Marvel Team-Up 1997 #1; Heroes Reborn: The Return #1–4; Wolverine
  #900; Gambit 1999 #1,2,5,8,9,12–15; Gambit 1999 one-shot; X-Man #50,59,60;
  Contest of Champions II #1–5; Astonishing X-Men 1999 #1–3; New Warriors 1999
  #5
- FF Early Years: Marvel Two-in-One (and Annuals) — 36 entries, mostly CV
  series 2696 / 2865

Genuine remaining ambiguity **(c)**: which duplicate copy to bind; whether
unmatched guest series should be added to the pile; whether Josh later wants
these lists strict. Existing canonical deps listed in section 1 stay the hard
restrictions **(b)**.

## 6. Apply order (all held)

1. Reproduce the forecast (`forecast_roll_eligibility.sql`).
2. Do **not** apply `001` until Josh reviews the rewritten guarded SQL.
3. Do **not** apply `002`. Identity resolution is incomplete.
4. Do **not** run `scripts/reader_order_migration.py` apply for `x-men-era-ten`
   or `fantastic-four-early-years`.
5. Do **not** create Neon clones or branches.
