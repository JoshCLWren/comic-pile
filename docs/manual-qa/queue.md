# Queue

**Route:** `/queue`. The queue contains the reader's durable ordered threads. Being present in Queue is not the same as being eligible in the current Roll pool.

## MQA-QUEUE-001: Ordering and positions persist

**Setup:** Several QA threads with distinct positions.

**Test:** Drag/reorder one and move another to front, then reload Queue and each thread page.

**Expected:** Displayed positions agree everywhere (Queue list, Thread page and pending Roll label), persist, and do not duplicate or lose rows. Regression history: #5263, fixed by #5429.

## MQA-QUEUE-002: Move to front affects the bounded pool

**Setup:** An eligible QA thread beyond the chosen die boundary.

**Test:** Move it to front and inspect Roll.

**Expected:** The thread enters the eligible die pool by new queue position; the selected die size remains unchanged.

## MQA-QUEUE-003: Snooze and re-admit

**Test:** Snooze a QA series, inspect its queue/roll state, then unsnooze or satisfy the relevant backoff rule.

**Expected:** Excluded series do not roll while excluded, without being deleted or silently re-prioritized; they return when eligible. Temporary snoozes are browser-scoped reroll exclusions that expire at local midnight or on Reset Dice ([#4405](https://github.com/JoshCLWren/comic-pile/issues/4405); UPDATE 2026-11-18). Durable exclusion is Remove from Queue, which is non-destructive and restorable from the excluded section.

**Unsnooze (UPDATE 2026-11-18, [#4589](https://github.com/JoshCLWren/comic-pile/issues/4589)):** Queue Unsnooze calls the server: it removes that snooze and, when it was the latest snooze with no later action, restores the series as the pending roll and reverts the die; otherwise it only removes the snooze. See MQA-ROLL-014.

## MQA-QUEUE-004: Blocked differs from out-of-pool

**Setup:** One QA series with an unread prerequisite and a different eligible series outside the die boundary.

**Test:** Inspect labels/explanations and attempt Roll.

**Expected:** True blockers name a real prerequisite; out-of-pool is not mislabeled blocked; neither ineligible series is selected.

## MQA-QUEUE-005: Mapping health agrees with owned issues

**Setup:** Fully, partly and unmapped QA threads.

**Test:** Compare indicators with their tracked issues; safely map one and revisit Queue.

**Expected:** Counts reflect real issue mapping state, not title similarity, and refresh after mapping. Fully confirmed series stay unobtrusive.

## MQA-QUEUE-006: Counts, canonical issue numbers, and sort order are truthful

**Setup:** A QA series containing issue #40 among eight owned issues, plus a Queue with filters and alternate sorts.

**Test:** Inspect Queue/Roll count labels and issue numbering; switch position, title and recently-added sorts; exercise Reposition from a filtered view.

**Expected:** Canonical issue number and ordinal progress are clearly different (never Issue 40 of 8). Count/copy distinguish zero, one, and many, including Map Series. Reposition uses the series' actual unfiltered Queue position. In a non-position sort, the interface explains that a position change affects position order, or makes the action unavailable; it must not suggest the current alternate sort will visibly rearrange. Reopening position sort shows the persisted correct rank.

## MQA-QUEUE-007: Search and clear use the latest query

**Setup:** Large QA Queue with known title matches and a controllably slow search response.

**Test:** Type quickly, clear with the labeled clear control, press Escape while focused in search, then immediately search another title; resolve the older response after the newer one. Check a narrow viewport and keyboard-only use.

**Expected:** Filtering/clear respond within the normal short debounce (under one second in normal local/test conditions), with visible accessible feedback during genuine remote delay. Older responses never overwrite the latest query, result counts, or empty state. Clear and Escape restore the unfiltered series set without mutating Queue order; focus remains sensible. If a filtered N of M count is shown, both numbers match the actual scope.

## MQA-QUEUE-008: Add/Edit Series drafts are safe and validated

**Setup:** QA series with both read and unread issues and an editable issue range.

**Test:** Make an unsaved change, Cancel, then edit again and attempt to close; stage issue removal; enter Already read as -1, 1.5, an over-maximum value, zero, and the maximum. Attempt to remove a ComicVine mapping.

**Expected:** Cancel discards the draft. Closing a dirty draft asks whether to discard; closing an unchanged draft does not. Staged issue removals clearly occur only on Save, while committed destructive work keeps explicit confirmation. Already read accepts integers from zero through the real maximum inclusive, with inline errors and disabled submit for invalid values, and server-side rejection if bypassed. Mapping removal uses an accessible app confirmation dialog, not a native window.confirm. Cancel/error never mutates persisted issues.

## MQA-QUEUE-009: Sibling mapping suggestions respect canonical identities

**Setup:** QA library with partially mapped issues, duplicate #2 and #20-22 identifiers, and similarly named but distinct ComicVine volumes.

**Test:** Correct one mapping and inspect suggested related issues before accepting any.

**Expected:** Only applicable unmapped or mismatched issues from the same canonical Thread/series are suggested. Stable identities deduplicate suggestions; already-correct issues are excluded or clearly non-actionable. Same-name, wrong-volume, or unrelated Thread issues are not suggested or auto-remapped. No mutation occurs without explicit approval.

## MQA-QUEUE-010: Confirmed edits promptly reconcile visible state

**Test:** Rename a QA series, mark it completed, inspect Queue and other open surfaces without hard refresh, then repeat while simulating failed mutations and stale query responses.

**Expected:** Confirmed title and active/completed state refresh promptly across affected views, including Queue position. Targeted cache invalidation prevents stale data from reappearing; failed operations never falsely show committed changes or lose persisted state. No unrelated Thread is affected.

**Tracking:** Approved Queue/dialog work [#3558](https://github.com/JoshCLWren/comic-pile/issues/3558); related QA regression [#3771](https://github.com/JoshCLWren/comic-pile/issues/3771). Keep separately tracked functional Queue bugs independent of this usability contract.


## MQA-QUEUE-011: Finished series stay listed and can be extended

**Setup:** QA account with a fully read single-issue series, with its original issue rating recorded.

**Test:** Open Queue, expand Finished Series, reload and navigate away and back. Choose **Add Back to Queue** for the finished series, explicitly request one new unread issue in **Issues to Add**, and inspect the expanded series and read history. Independently test **Removed from Queue → Restore** on a removed (not finished) series.

**Expected:** Completed series remain listed before reactivation (read from the completed collection, not the active-only Queue rows). **Add Back to Queue intentionally creates the requested number of new unread issues** and reactivates the expanded series. A finished one-issue series extended by one becomes a two-issue series with its original issue still read and rated, and the new #2 unread (50% complete). Do not report the requested new #2 as a phantom issue. Verify exactly the requested addition is made, without duplicate issues or damaged existing history. In contrast, restoring a **Removed from Queue** series reactivates its existing issues and does not create new issues. Owner decision 2026-11-20; prior misclassified report [#5611](https://github.com/JoshCLWren/comic-pile/issues/5611). Source: #5171, fixed by #5297.

## MQA-QUEUE-012: Queue rows show the series cover when a confirmed cover exists

**Test:** Open Queue with one series whose next unread issue has a confirmed ComicVine mapping carrying a cover, one series whose only confirmed covers sit on later issues, and one series with no confirmed cover. Expand the page at phone and desktop widths.

**Expected:** The series with a confirmed cover shows the provider cover image at the start of its row, using the provider URL unchanged and reserving its frame before load (no layout shift). The later-issue series shows the first confirmed cover by issue position. The series without a confirmed cover shows the shared "No cover" placeholder, not a broken image or an empty gap. Covers never come from unconfirmed candidates.

**Tracking:** Part of the V2 covers work [#5433](https://github.com/JoshCLWren/comic-pile/issues/5433). Other views (Thread detail, History, Sessions, plans, CBL browser, Identity inbox, Creators, Crossovers) are not covered by this scenario yet.

## MQA-QUEUE-013: Bulk remove and restore container series from Queue

**Setup:** An authoritative Reading List containing multiple active series in the Queue. Include a case where at least one member also belongs to another active list/crossover when possible.

**Test:** From the container page, choose "Remove all series from Queue" (or equivalent bulk action), review the affected series list, keep any series that should remain in another active context when offered, and confirm. Inspect Queue active rows, the Removed from Queue section, and Roll eligibility. Then restore the whole removal group from Queue and/or restore all from the container action.

**Expected:** The action removes the selected container series from the active Queue in one operation without deleting issues, read history, ratings, mappings, or Reading List membership. Removed series appear grouped by the removal source in Queue with group and individual restore available. Restoring returns eligible series to the active Queue and updates Roll eligibility accordingly. The confirmation waits for overlap checks to complete and does not proceed if those checks fail; series intentionally kept in Queue remain active.

## MQA-QUEUE-014: Delete series removes events and related rows atomically

**Setup:** QA account with a queued series that has roll events (for example, after a manual roll pick and a remove/restore cycle) and appears in a reading order.

**Test:** From the Queue row menu choose "Delete series" and confirm "Delete Series" in the "Permanently delete …?" dialog. Reload Queue and reopen the reading order.

**Expected:** The series disappears from Queue with no foreign-key error banner. Its issues, reading history, ratings, events and reading-order entries are removed atomically in one transaction, a delete audit event is recorded, and unrelated series are untouched. Source: #5461, fixed by #5468 (renumbered from MQA-QUEUE-012 after main added the covers scenario with that ID).
