# Prompt: Fix issue-level dependency blocking to use position-based range

> Superseded by GitHub issue #528. This prompt documents the older anticipatory-blocking
> behavior that caused false thread deadlocks in interleaved reading orders. Current desired
> behavior is next-unread-only blocking: a dependency blocks only when its target issue is the
> target thread's immediate next unread issue.

## Context

You are working on `comic-pile`, a FastAPI + React comic reading queue app.
The repo lives at `/mnt/extra/josh/code/comic-pile`.

## The bug (GitHub issue #413)

Issue-level dependencies are supposed to block a thread until a prerequisite issue is read.
Currently the blocking check only fires when the dependency's target issue is the **exact**
current `next_unread_issue_id`. If the user's next unread is #9 and the dependency is on #10,
the thread is not blocked — the user can read #9 freely, and the block only kicks in one issue
too late.

Real incident: a `SW Vol. 2 #11 → Planetary #10` dependency existed. User's Planetary
`next_unread` was #9. Planetary showed as unblocked. A manual hotfix dependency on #9 had to
be added by hand.

## Acceptance criteria (from the issue)

- A dependency on issue #10 blocks the thread when `next_unread` is #8, #9, or #10  
- The block lifts once the source issue is read, regardless of where next_unread is  
- Existing exact-match behaviour is preserved (dep on #10 still blocks at #10)  
- Blocking explanations still report correctly under the new condition  
- No regression in the existing test suite (except the one test that documents the old buggy behaviour — see below)  
- 96%+ coverage maintained

## The fix

### Semantics

Change from **exact-match** to **anticipatory blocking**:

> Block the target thread if the dependency's target issue has not yet been reached
> (i.e., `dep_target.position >= target_thread.next_unread.position`).

Concrete examples with a dep whose target is issue #10 (position 10):

| next_unread | next_unread position | Expected result |
|-------------|----------------------|-----------------|
| #8          | 8                    | **BLOCKED** (haven't reached #10 yet) |
| #9          | 9                    | **BLOCKED** |
| #10         | 10                   | **BLOCKED** (exactly at dep target) |
| #11         | 11                   | not blocked (already past dep target) |

### File: `comic_pile/dependencies.py`

**`get_blocked_thread_ids` (lines 28–46)**

Current join (exact match):
```python
source_issue = Issue.__table__.alias("source_issue")
target_issue = Issue.__table__.alias("target_issue")
target_thread = Thread.__table__.alias("target_thread")

issue_result = await db.execute(
    select(target_thread.c.id)
    .join(
        target_issue,
        target_issue.c.id == target_thread.c.next_unread_issue_id,
    )
    .join(Dependency, Dependency.target_issue_id == target_issue.c.id)
    .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
    .join(source, source_issue.c.thread_id == source.c.id)
    .where(target_thread.c.user_id == user_id)
    .where(source.c.user_id == user_id)
    .where(source_issue.c.status != "read")
    .where(target_thread.c.next_unread_issue_id.isnot(None))
)
```

Replace with a two-alias approach: one alias for the thread's actual next-unread issue
(`target_next_unread`), another for the dependency's target issue (`dep_target_issue`).
The join condition should be:
- `target_next_unread.id == target_thread.next_unread_issue_id` (get current position)
- `dep_target_issue.thread_id == target_thread.id AND dep_target_issue.position >= target_next_unread.position`
  (dep target is at or beyond where the user currently is)

Add `.distinct()` because multiple dependencies in the same thread could match.

**`get_blocking_explanations` (lines 66–95)**

Apply the same structural change. The select should return the blocking source thread title
and source issue number as before, but use the same range-based join so the explanations
appear whenever the block is active.

### File: `tests/test_dependencies.py`

**Update `test_future_issue_dependency_does_not_block_current_reads` (line 349)**

This test was written to document the old (buggy) behaviour. It creates a dep on
`target_issue_2` (position 2) while `target_thread.next_unread_issue_id = target_issue_1`
(position 1), then asserts the thread is **not** blocked. Under the new semantics
(dep_target.position 2 >= next_unread.position 1 → True), the thread **should** be blocked.

Changes required:
1. Rename the test to reflect the new intended behaviour, e.g.,
   `test_dep_on_future_issue_blocks_thread_before_reaching_it`
2. Change the first assertion from `not in blocked` to `in blocked`
3. Keep the second block (after marking issue 1 read, next_unread becomes issue 2) — it
   should still assert `in blocked_after` (dep_target pos 2 >= next_unread pos 2 → True)
4. Add a third step: mark `source_issue_1` as read, refresh, and assert the thread is
   **not** blocked (source satisfied → dep lifts)

**Add `test_dep_blocks_anticipatorily_before_dep_target` (new test)**

The regression test for the real-world incident. Sketch:
- Two threads (source, target), each with 3 issues
- Dep: source_issue_3 → target_issue_3
- source thread next_unread = source_issue_1 (source NOT satisfied)
- target thread next_unread = target_issue_1 (position 1; dep target is position 3)
- Assert target thread IS blocked (dep target pos 3 >= next_unread pos 1)
- Mark source_issue_3 as read (satisfy source)
- Assert target thread is NOT blocked

**Add `test_dep_does_not_block_when_next_unread_past_dep_target` (new test)**

Verifies the block does not apply when next_unread has already moved past the dep target:
- Two threads, dep on target_issue_2 (position 2)
- target thread next_unread = target_issue_3 (position 3; past the dep target)
- Assert target thread is NOT blocked

## Important note on the issue spec

The GitHub issue body contains a proposed SQL sketch that reads
`AND position <= target_next_unread.position`, which would implement *retroactive*
blocking (blocking when past the dep target). The **acceptance criteria** in the same issue
contradict this and describe *anticipatory* blocking (blocking *before* reaching the dep
target). Trust the acceptance criteria — they match the real production incident where
"Planetary #9 was freely readable" when the dep was on Planetary #10.

## Definition of done

- `make lint` passes (ruff + pyright, no `Any` types)
- `make pytest` passes with ≥96% coverage
- PR targets `main`, title follows conventional commits: `fix: block thread when next-unread is before dependency target (issue #413)`
- PR body cites issue #413 and includes a short description of the semantic change
