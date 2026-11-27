# v2 URL-shape contract and CI guard

Issue: #5720 (parent #4456, epic #4335). Design sources:
[AIP-122](https://google.aip.dev/122) (collection identifiers),
[AIP-131 to AIP-135](https://google.aip.dev/130) (standard methods),
[AIP-136](https://google.aip.dev/136) (custom methods) and
[AIP-185](https://google.aip.dev/185) (major version).

`scripts/check_v2_aip_shapes.mjs` fails a pull request that introduces a new
`/api/v2` operation which does not follow that contract. It does **not** rename,
retire or otherwise change any live route. Existing debt is recorded, per
operation, in [v2-aip-shapes-baseline.json](v2-aip-shapes-baseline.json) with the
issue that owns its removal.

## Rules enforced

| Reason code | Rule |
| --- | --- |
| `non-lowercamelcase-segment` | A collection or resource segment must be lowerCamelCase: `readingLists`, not `reading-lists` or `reading_lists`. Path parameters (`{list_id}`) are exempt. |
| `trailing-slash` | Canonical paths never end in `/`. |
| `action-shaped-subpath` | A bare verb (`/restore`, `/preview`, `/resolve`) is not a resource method. Use a `:verbNoun` custom method or a real sub-resource. |
| `custom-method-not-final` / `custom-method-malformed` | A custom method is one final `{resource}:verbNoun` segment. |
| `custom-method-not-lowercamelcase` | The verb is lowerCamelCase: `:planAdoption`, not `:PlanAdoption`. |
| `custom-method-verb` | Custom methods use GET (read-only) or POST only. |
| `put-mutation` | Partial resource updates are PATCH with `update_mask` (AIP-134); PUT is not a resource method in this contract. |
| `unsupported-verb` | Only GET, POST, PATCH and DELETE (plus the flagged PUT) appear in the inventory. |

Versioned `METHOD path` is the primary key, so nested collection paths
(`/api/v2/threads/{threadId}/issues`) and justified custom methods
(`/api/v2/threads/{threadId}:planAdoption`) are recognized as conforming rather
than treated as free-form strings.

## Sources checked

The guard merges two sources and de-duplicates by `METHOD path`:

1. `docs/api/route-fragments/*.json` — the only contributor-editable route
   source. `vercel-rewrites.json` is the generated rewrite artifact and is
   skipped, as are generated `vercel.json` rewrites and the generated
   [v2-route-inventory.json](v2-route-inventory.json) contract.
2. [v2-route-inventory.json](v2-route-inventory.json) — the generated live
   inventory. A small number of historical ingress routes (for example the auth
   operations) are declared directly in `vercel.json` and therefore exist only
   here; they are still live v2 operations, so they are covered.

## Measured state at introduction

Checked against the fragment and inventory sources in the introducing change:

- 152 distinct live `/api/v2` method/path pairs (131 declared by route
  fragments, 21 historical ingress-only operations).
- 96 of them do not satisfy the contract yet and are baselined:
  - 87 contain a hyphenated or otherwise non-lowerCamelCase segment;
  - 15 use an action-shaped subpath instead of a `:camelCaseVerb` custom method;
  - 6 use a trailing slash;
  - 6 mutate a resource with PUT.
  (A single operation can have more than one reason.)

This inventory is **not** evidence that the live v2 surface is AIP-compliant.
The nonconforming patterns are known and owned:

- **Hyphenated resource families**: `continuity-plans`, `reading-lists`,
  `reading-orders`, `reading-sessions`, `reading-plan-sync`, `queue-entries`,
  `queue-exclusions`, `identity-inbox`, `issue-read-markers`,
  `issue-read-marker-removals`, `issue-duplicate-reconciliation`,
  `series-mapping-commits`, `demo-roll`, `reading-graph`,
  `reading-boundaries`, plus hyphenated sub-collections such as
  `adoption-commits`, `overlap-decisions`, `release-sources`,
  `assignment-batches`, `issue-candidates`, `reader-context` and
  `suggestion-dismissals`.
- **Trailing slash**: `GET|POST /api/v2/continuity-plans/`,
  `POST /api/v2/dependencies/`, `GET /api/v2/reading-orders/`,
  `POST /api/v2/continuity-plans/release-sources/` and
  `GET /api/v2/continuity-plans/{plan_id}/release-sources/`.
- **Action-shaped subpaths**: `/api/v2/issue-duplicate-reconciliation/{apply,
  detect,preview,undo}`, `/api/v2/queue-exclusions/restore`,
  `/api/v2/queue-exclusion-groups/{group_id}/restore`,
  `/api/v2/comicvine/resolve`, `/api/v2/comicvine/search/series`,
  `/api/v2/creators/compare`, `/api/v2/reading-lists/{list_id}/export`,
  `/api/v2/continuity-plans/{plan_id}/reading-orders/project`,
  `/api/v2/undo/{session_id}/snapshots[/{snapshot_id}/restore]`,
  `/api/v2/roll/reset` and `/api/v2/auth/refresh`.
- **PUT mutations**: `/api/v2/continuity-plans/{plan_id}`,
  `/api/v2/issues/{issue_id}/position`, `/api/v2/reading-lists/{list_id}`,
  `/api/v2/reading-lists/{list_id}/overlap-decisions`,
  `/api/v2/reading-mode` and `/api/v2/threads/{thread_id}/issue-order`.

Baseline entries name the owning issue from the route fragment where one is
declared; the rest fall back to the #4456 API audit. Routing families are
retired by their cutover slices (#4335, #4459, #4595, #4653, #4684, #4835,
#4836, #4838, #4839, #4844, #4850, #4851, #4855, #5435), not by this guard.

## Working with the guard

A conforming route needs nothing beyond its fragment entry:

```bash
node scripts/check_v2_aip_shapes.mjs
node --test scripts/check_v2_aip_shapes.test.mjs
```

- **Adding an operation**: conform, or add a baseline entry naming the issue that
  will retire it. A deliberate exception is a reviewed decision, never a silent
  exemption.
- **Renaming or retiring an operation**: delete its baseline entry. Entries that
  are no longer noncompliant are reported as stale notes, not failures, so debt
  removal is never blocked.
- **Regenerating the ledger**: `node scripts/check_v2_aip_shapes.mjs
  --print-baseline` prints the baseline that would accept the current state. It
  writes nothing; committing the result is an explicit, reviewable act.
- Anonymous baseline exemptions (no `owning_issue`), duplicate keys and
  malformed entries fail the guard, so the ledger cannot grow into a blanket
  suppression.

The check runs in the required CI `script-checks` job, which is part of the CI
Summary gate, so a violating route cannot land on the protected branch.
