# Reading sessions

**Entry:** `/sessions/:id` from History or other session navigation.

**Owner rulings:** sessions are retired as an entity ([#4405](https://github.com/JoshCLWren/comic-pile/issues/4405), 2026-10-30/31; migration [#4839](https://github.com/JoshCLWren/comic-pile/issues/4839)); `GET /sessions/current` and Restore Session Start retired by owner directive on [#4343](https://github.com/JoshCLWren/comic-pile/issues/4343) (2026-11-18, implemented in #5442).

**Amended 2026-11-18:** Roll is sessionless per [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405) (no six-hour timer, session row lifecycle or automatic session resets). The detail page remains as an event-derived view of recorded activity; `GET /api/v1/sessions/current/` and Restore Session Start were retired by owner directive on #4343 / [#5442](https://github.com/JoshCLWren/comic-pile/pull/5442).

## MQA-SESSION-001: Session details match recorded events

**Test:** Roll, rate, and snooze in one QA session, then open details.

**Expected:** Correct events appear in order in the proper session without mixing another session's activity. The timeline includes snoozes and ratings, consistent with History (see [#5387](https://github.com/JoshCLWren/comic-pile/issues/5387)).

## MQA-SESSION-002: Session boundary keeps durable progress

**Status: Retired (2026-11-18)** -- owner decision [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405): no reading sessions as entities, no inactivity/six-hour boundary, no automatic resets. Durable read and rating history persisting across time is covered by MQA-HISTORY-001 and MQA-HISTORY-004.

**Original expectation (historical):** Session identity/boundaries behave as configured while persistent read and rating history survives.

## MQA-SESSION-003: Pending selection resumes honestly

**Test:** Leave a QA selection unresolved, return to the app and resolve it.

**Expected:** The pending choice isn't replaced or silently rated; subsequent history is accurate. Per #4405 (UPDATE 2026-11-18) the pending selection is browser-owned: it survives reload and syncs across tabs of the same signed-in reader, clears only after successfully rating/reading that same issue, a successful explicit Cancel Roll (MQA-ROLL-008), or Reset Dice, is kept on failed requests, and never leaks to another account on the same browser.

## MQA-SESSION-004: Restore Session Start is gone; Undo Latest remains

**Status: Retired (2026-11-18) for Restore Session Start** -- owner directive on [#4343](https://github.com/JoshCLWren/comic-pile/issues/4343), implemented in #5442: restoring a session-start snapshot conflicts with the event-based activity, rating-correction and Reset Dice model.

**Test:** Open a QA session detail page.

**Expected:** No Restore Start action or confirmation exists. Undo Latest and the event timeline (including historical undo/restore events) remain; rating correction goes through the issue rating edit. Reading history is preserved.
