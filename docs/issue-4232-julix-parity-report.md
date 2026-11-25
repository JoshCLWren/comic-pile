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
**Status: Partially satisfied in-repo; live verification required.**  
This document records the issue's verified 2026-10-27 findings and the required report shape. A complete 466-row story-to-physical-issue parity report requires access to the latest Julix Story tab and production/custom-CBL data. The report must include: source version, every source row, story, mapped physical issue, single list position, dedupe reason for anthology rows, and diff classification.

**Required live steps:**
- Export/fetch latest Julix Story tab (record sheet version/timestamp).
- Export production custom CBL #2 entries for user 1 with issue/thread metadata.
- Produce row-by-row mapping: `source_row -> story -> physical_issue_id -> thread_id -> list_position`.
- Mark each row: `match`, `moved`, `missing_in_list`, `missing_in_source`, `anthology_deduped`, `intentional_exclusion`, `repaired`.

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