# Queue

**Route:** `/queue`. The queue contains the reader's durable ordered threads. Being present in Queue is not the same as being eligible in the current Roll pool.

## MQA-QUEUE-001: Ordering and positions persist

**Setup:** Several QA threads with distinct positions.

**Test:** Drag/reorder one and move another to front, then reload Queue and each thread page.

**Expected:** Displayed positions agree everywhere, persist, and do not duplicate or lose rows.

## MQA-QUEUE-002: Move to front affects the bounded pool

**Setup:** An eligible QA thread beyond the chosen die boundary.

**Test:** Move it to front and inspect Roll.

**Expected:** The thread enters the eligible die pool by new queue position; the selected die size remains unchanged.

## MQA-QUEUE-003: Snooze and re-admit

**Test:** Snooze a QA series, inspect its queue/roll state, then unsnooze or satisfy the relevant backoff rule.

**Expected:** Excluded series do not roll while excluded, without being deleted or silently re-prioritized; they return when eligible.

## MQA-QUEUE-004: Blocked differs from out-of-pool

**Setup:** One QA series with an unread prerequisite and a different eligible series outside the die boundary.

**Test:** Inspect labels/explanations and attempt Roll.

**Expected:** True blockers name a real prerequisite; out-of-pool is not mislabeled blocked; neither ineligible series is selected.

## MQA-QUEUE-005: Mapping health agrees with owned issues

**Setup:** Fully, partly and unmapped QA threads.

**Test:** Compare indicators with their tracked issues; safely map one and revisit Queue.

**Expected:** Counts reflect real issue mapping state, not title similarity, and refresh after mapping. Fully confirmed series stay unobtrusive.
