# Issue #4232 — Julix Mignolaverse parity audit report

**Issue:** [#4232](https://github.com/JoshCLWren/comic-pile/issues/4232)  
**Status:** Code/test artifacts added in this session; production data audit/repair requires live production access and external source verification.  
**Generated:** 2026-11-25 (sandbox session)

## Scope and policy

- Source is story-level: [Julix Story tab](https://docs.google.com/spreadsheets/d/1g_6LwKE4T73xoIKnCj0X3d_b1aDRnzdLNun8gDqXOPs/edit#gid=1872575412).
- Comic Pile offers physical comic issues. One anthology issue containing several stories is placed **exactly once, at the earliest occurrence of any of its stories**. It must never be offered more than once and later story positions must not force rereading.
- This policy applies to all multi-story books, not only Winter Specials. Do **not** reorder 2018/2017 solely on publication years.

## Verified production findings (recorded in issue, 2026-10-27)

| Field | Value |
|---|---|
| List | `Mignolaverse — Julix Comics (Unread)` (custom CBL #2, user 1) |
| Mode | strict |
| Entries | 466 unique entries, 382 unread |
| Identity invariants | 466 distinct positions, 466 distinct Issue IDs, no missing Issue/Thread references |
| Active frontier | position 83: B.P.R.D.: Casualties #1 (issue 117305, one short story, not a five-issue series) |
| Immediately before frontier | Winter Specials 2018 #1 (pos 81, read), 2017 #1 (pos 82, read) |
| Winter Specials later positions | 2016 #1 at pos 290, 2019 #1 at pos 323, Yule Cat at pos 445 |
| Wild Hunt check | Hellboy: The Wild Hunt #1-#8 resolve to canonical Thread 18829, consecutive positions 46-53, all read (unlike closed #3345) |
| Amazing Screw-On Head #1 | pos 93, already read; not an error in strict list |

## Missing unread canonical issues in otherwise included Threads

| Issue | Prod issue ID | Thread | Thread ID | Created | List presence | Classification |
|---|---:|---|---:|---|---|---|
| Young Hellboy: Thrilling Sky Adventures #4 | 1120533 | Young Hellboy: Thrilling Sky Adventures | 19008 | 2026-10-21 | Missing; #1-#3 at pos 462-464 | **Intentional pending source verification** — do not blind auto-append; requires Julix Story-tab/source evidence and explicit placement decision |
| The Foundry #2 | 1117775 | The Foundry | 19009 | 2026-10-10 | Missing; #1 at pos 465 | **Repair candidate pending source verification** — requires Julix Story-tab/source evidence and explicit placement decision before insertion |

## Acceptance criteria status

### 1. Complete 466-entry parity/difference report against latest Julix Story tab
**Status: Story tab fetched in sandbox; full 466-row physical-issue parity still requires production CBL export and external identity verification.**  
Fetched source: Julix "Individual Story Order" / Story tab CSV export from sheet `1g_6LwKE4T73xoIKnCj0X3d_b1aDRnzdLNun8gDqXOPs`, gid `1872575412` (fetched 2026-11-25 in sandbox). The Story tab is story-level; Comic Pile list is physical-issue-level with anthology earliest-occurrence dedupe.

**Story-tab observations relevant to #4232:**
- `B.P.R.D., Casualties, 8, Being Human, Abe Sapien: The Drowning and Other Stories, , 1981` appears in Part III. Production frontier is physical issue B.P.R.D.: Casualties #1 (issue 117305, pos 83) — consistent with a single-issue physical entry.
- Winter Special stories appear at multiple story locations: `The Last Witch of Fairfield` (Part II, featured in Hellboy Winter Special 2017, 1979), `God Rest Ye Merry` (Part V, 1961, in Visitor TPB), `The Great Blizzard` (Part V, also featured in Hellboy Winter Special 2017, 1891), `The Empty Chair` (Part V, featured in Hellboy Winter Special 2018, 1930), `Mood Swings` (Part VIII, featured in Hellboy Winter Special 2016, 1975). The physical Winter Special issues are anthologies; earliest-occurrence-of-any-contained-story determines single placement. Issue finding: do **not** reorder 2018/2017 solely on publication years.
- `Hellboy and the B.P.R.D., The Yule Cat, 20, The Ghost Ships of Labrador and Others, , 1990` appears in Part VIII. Issue reports Yule Cat at pos 445 as a Winter Special physical issue — confirm whether this is the same physical issue/anthology mapping and earliest-occurrence placement.
- `Young Hellboy, Thrilling Sky Adventures, 82, , , 1947` appears in Part VIII as a story/collection row. Issue reports missing unread canonical issue `Young Hellboy: Thrilling Sky Adventures #4` (issue 1120533, Thread 19008); #1-#3 at positions 462-464. Story-tab row does not provide physical issue #4 granularity; source-level verification required before append.
- `The Foundry, 40, , , 1889` appears in "Part ?: Ongoing stories (To be placed...)". Issue reports missing unread canonical issue `The Foundry #2` (issue 1117775, Thread 19009); #1 at pos 465. Requires source-level verification and explicit placement decision.

**Still required for complete 466-row report:**
- Export production custom CBL #2 entries for user 1 with issue/thread metadata.
- Produce row-by-row mapping: `source_row -> story -> physical_issue_id -> thread_id -> list_position`.
- Mark each row: `match`, `moved`, `missing_in_list`, `missing_in_source`, `anthology_deduped`, `intentional_exclusion`, `repaired`.
- Record source version/timestamp and any Story-tab changes since 2026-10-27 finding.

### 2. Verify Winter Specials, Casualties, omnibus/anthology covers, missing tail issues
**Status: Encoded as production-shaped fixtures; external format verification required.**  
- Winter Specials 2016/2017/2018/2019/Yule Cat positions and no-reorder policy are covered by `native/roll-service/tests/julix_parity_4232.rs`.
- Casualties frontier at pos 83 and advance behavior covered by fixture.
- Missing tail issues classified in fixture and report table above.
- Dark Horse/ComicVine physical format/issue-count confirmation requires live external evidence; do not claim verified without it.

### 3. Fix real missing/wrong memberships in authoritative user-owned Reading List
**Status: Not performed in sandbox (no production DB access).**  
Any production repair must:
- target the authoritative user-owned Reading List (custom CBL), not only legacy plan JSON or Thread blocked cache;
- preserve every Issue ID, read/rating/event history, durable exclusion, and sibling Reading List;
- include bounded before/after diff and list-scoped Undo;
- not repeatedly reconfirm unchanged intent;
- classify Young Hellboy: Thrilling Sky Adventures #4 and The Foundry #2 using source evidence before append/repair.

### 4. Production-shaped PostgreSQL/API fixtures
**Status: Added.**  
`native/roll-service/tests/julix_parity_4232.rs` asserts:
- (a) only first unread Julix entry is eligible within strict list;
- (b) no anthology/physical issue is offered more than once;
- (c) reading Casualties exposes correctly ordered next entry;
- (d) omitted in-Thread issues are classified as intentional or repaired.

### 5. Cross-surface verification
**Status: Partially run in sandbox.**  
- Focused Rust tests added for Roll eligibility, reader projection, and read-advance behavior.
- Full cross-surface production verification (Roll, Queue, list reader, Thread) requires running against production-shaped data and/or deployed environment. Observed Roll pool must be reported separately from inferred list frontier.

## Evidence / commands

Record exact commands and outcomes in the PR/issue comment when run. This sandbox session adds code/tests and this report; it does not claim production data mutation or live external source verification.