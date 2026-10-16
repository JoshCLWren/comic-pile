# Queue "Map series" repair

**Entry:** `/queue` → Map series, select a ComicVine volume → preview owned issue matches → approve. Volume selection alone never writes mappings.

## MQA-MAP-001: Bootstrap a fully unmapped series

**Setup:** QA thread with several numbered issues and zero confirmed ComicVine mappings; a correct provider volume has unique exact issue-number matches.

**Test:** Open Map series, select that volume, inspect proposed matches, approve all safe rows, then reload Queue and thread.

**Expected:** The origin issue can establish the first safe mapping and other safely matching owned issues can be approved in the same operation. No need for a separate first-issue repair. Counts and identities persist. Ambiguous, conflicting and special-number matches remain unconfirmed for review.

## MQA-MAP-002: Finish a partially mapped series

**Setup:** QA thread with some issues confirmed to a selected volume, and other owned issues unmapped.

**Test:** Open Map series, select the matching volume, review safe checked rows/count, approve and reload.

**Expected:** Only safe owned issues are mapped; existing correct mappings remain intact; the queue health indicator refreshes and remaining unsafe rows are reported.

## MQA-MAP-003: Reject genuinely unsafe mappings

**Setup:** QA issues with mismatched, duplicate, fractional, conflicting, or special identifiers.

**Test:** Select a nonmatching or ambiguous provider volume and inspect preview.

**Expected:** Unsafe matches cannot be approved automatically; refusal explains why without mutation. This is distinct from the invalid zero-mapping dead end in MQA-MAP-001.

## MQA-MAP-004: Dialog state is isolated

**Test:** Open preview for QA thread A and cancel; open thread B, choose another volume, then return to A.

**Expected:** Search query, selected volume, checked rows, and preview refer to the correct active thread. Cancel has no effect on identities, progress, or queue order.

## MQA-MAP-005: Stale or failed approval is safe

**Test:** Attempt an expired/stale preview or controlled provider failure if reproducible without harming real data; retry.

**Expected:** A stale approval cannot commit without a fresh preview. Error messages explain the outcome; retries are idempotent and never falsely report success.

**Reference:** [#3741](https://github.com/JoshCLWren/comic-pile/issues/3741) records the fully unmapped-series defect. The owner confirmed that the intended solution is functional safe bulk mapping, not hiding the Map series action.
