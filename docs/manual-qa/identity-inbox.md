# Identity inbox

**Route:** `/identity-inbox`. Review and correct canonical identities using evidence.

## MQA-IDENTITY-001: Resolve a genuinely matched issue

**Setup:** An unresolved QA issue with identifiable ComicVine candidate.

**Test:** Find it in the inbox, inspect candidates, confirm correct identity, and reload thread.

**Expected:** Only the chosen issue gets the approved mapping; inbox and thread indicators update.

## MQA-IDENTITY-002: Unsafe candidates can be deferred

**Test:** Inspect ambiguous/conflicting candidates, then dismiss without approval.

**Expected:** No mapping is forced or silently inferred from title similarity; existing reading and identity state stay intact.

## MQA-IDENTITY-003: Mapping state agrees across surfaces

**Test:** Resolve one issue and compare inbox, thread detail and Queue.

**Expected:** Each surface reflects persisted scope and remaining work; one mapped issue does not imply a fully mapped series.
