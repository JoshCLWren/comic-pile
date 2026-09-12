# Step 23B — Guarded legacy Reading Order apply and rollback

Guarded apply + rollback tooling for migrating the three surviving user-1
legacy Reading Orders into informational canonical Reading Plans.

- Result: `PASS`
- Production mutated: `False`
- Production apply executed: `False`
- Production rollback executed: `False`
- Reviewed Step 23A snapshot token: `6cfa01ccc82f33c4e0fc7a23d9b7d4e4b32a66a7aa13bbbfd50bc633e38bdf7c`
- Snapshot guard passed: `True`
- Architecture hold #2363 lifted: `False`

## What this step implements

Operator CLI `scripts/legacy_reading_order_step23b_migration.py` with
`dry-run`, `apply`, and `rollback`.

- `dry-run` is always read-only and re-runs the Step 23A preflight.
- `apply` and `rollback` require `--database-url`, the unique confirmation
  string `STEP23B-LEGACY-READING-ORDERS`, and the reviewed snapshot or
  receipt token. Production is never the default target.
- Apply refuses unless a fresh locked preflight produces the exact reviewed
  Step 23A token. A drifted token is not auto-accepted.

## Apply contract that was proved

- Created exactly three informational Reading Plans for user 1:
  - `Doctor Strange Epic Collection Vol. 10: Infinity War` — 17 nodes
  - `Starman Compendiums 1-2` — 66 nodes
  - `JSA: Robinson / Goyer / Johns` — 57 nodes
- Total nodes created: **140**
- Plan-owned hard constraints created by migration: **0**
- Retired `reading_plan_order` dependency ids:
  `1806, 1807, 1808, 1810, 1811, 1832, 1833, 1846, 1847`
- Preserved standalone prerequisite ids: `18, 19, 20, 21`
- Legacy Reading Orders were **retained** as rollback/compatibility rows.
  Canonical reader-owned authority after apply is the three informational
  Reading Plans, not the legacy orders.

## Protected reader state

Before/after factual hashes were identical:

- issue: `148838ca59c7835f403bf1b9d14e96a05c94fedc3608373f30be4175be8c9c57`
- events: `58e3007d6d6fb8f909d5e21c74c373249db60aa68b50be40aaebbd0b7f453abd`
- identities: `68c1b3f9dd66c83d923014581b460017811430eb3dbe13c1bb108765cb3c6abc`
- threads excluding persisted blocked flags:
  `8536ed15ea7424f50b331196abf472731243e53c18971b6e640e36df191dbfde`

## Eligibility

Next unread issue identity and standalone blockers were unchanged.

The expected constraint-model delta from retiring the nine serialization
edges is that three current next-unread issues are no longer blocked by
those retired rules:

- Thread 105 next unread 2245: lost rule 911 / dependency 1808
- Thread 17062 next unread 2252: lost rule 915 / dependency 1810
- Thread 17194 next unread 101817: lost rule 938 / dependency 1833

No candidate became blocked by informational plan position.
No standalone prerequisite was removed.
Unrelated blocker #2778 was left in place.
Persisted blocked state and derived eligibility agreed after refresh.

## Rollback

Rollback restored exact legacy dependency and ContinuityRule identities,
deleted the three migration-created plans, preserved #18–#21, and returned
eligibility to the captured pre-apply baseline. The production
Dependency → ContinuityRule mirror trigger path was covered in PostgreSQL
tests.

## Non-production rehearsal

Isolated Neon clone, not production:

- Project: `delicate-sea-51036121`
- Parent production branch: `br-silent-violet-ayobfez5`
- Rehearsal branch: `br-raspy-term-ay2o0uxl` / `step23b-rehearsal-4ee9`
- Sequence: fresh dry-run → apply → post-apply verification → rollback →
  exact restoration verification
- Final snapshot token after rollback:
  `6cfa01ccc82f33c4e0fc7a23d9b7d4e4b32a66a7aa13bbbfd50bc633e38bdf7c`
- Final snapshot equals original pre-rehearsal migration-owned state: `True`

## Local verification

- `ruff check .` passed on the full repo
- `ty check --error-on-warning` passed on the full repo
- `pytest tests/test_legacy_reading_order_production_migration.py` — 16 passed
  on isolated PostgreSQL (`comic_pile_test` on `br-odd-hall-ayvnneiz`)

## Boundaries that remain in force

- Production was not mutated.
- Ultimate Universe cutover was not started.
- Broad CBL cleanup was not started.
- Legacy Reading Orders were not deleted from production.
- Architecture hold #2363 was not lifted.
- Step 23C has not started.
