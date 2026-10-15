# Reading sessions

**Entry:** `/sessions/:id` from History or other session navigation.

## MQA-SESSION-001: Session details match recorded events

**Test:** Roll, rate, and snooze in one QA session, then open details.

**Expected:** Correct events appear in order in the proper session without mixing another session's activity.

## MQA-SESSION-002: Session boundary keeps durable progress

**Test:** Return during an active session and after the configured inactivity boundary when feasible.

**Expected:** Session identity/boundaries behave as configured while persistent read and rating history survives.

## MQA-SESSION-003: Pending selection resumes honestly

**Test:** Leave a QA selection unresolved, return to the app and resolve it.

**Expected:** The pending choice isn't replaced or silently rated; subsequent session history is accurate.
