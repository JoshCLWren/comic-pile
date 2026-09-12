# Step 23A — Legacy Reading Order migration preflight

Read-only production preflight for migrating the three surviving legacy
Reading Orders into informational canonical Reading Plans.

- Result: `PASS`
- Captured at: `2026-09-11T23:34:56.311307+00:00`
- Base HEAD: `f58e71309f7ecdf61183428fa4196a5e20f62d02`
- Production project: `delicate-sea-51036121`
- Production branch: `br-silent-violet-ayobfez5`
- Snapshot token: `6cfa01ccc82f33c4e0fc7a23d9b7d4e4b32a66a7aa13bbbfd50bc633e38bdf7c`

## Required reconciliation

- Production Reading Order count for user 1: **3**
- Still exactly 3: **True**
- Doctor Strange item count: **17**
- Starman item count: **66**
- JSA item count: **57**
- Total item count: **140**
- Every legacy item resolved to exactly one canonical plan node: **True**
- Unresolved or ambiguous items: **0**
- Existing Reading Plan overlaps: **0**
- Dependency overlap count: **13**
- Dependency classification breakdown: reading_plan_order **9**, standalone_prerequisite **4**, needs_review **0**
- Standalone prerequisites that must survive: **4** (`[18, 19, 20, 21]`)
- Global Step 14 needs_review rows touch these orders: **False**
- Informational migration would change current Roll eligibility: **False**
- All factual reader state can be preserved unchanged: **True**
- Persisted vs derived eligibility mismatches: **0**

## Proposed canonical targets

Each order becomes one `ordering_mode=informational` Reading Plan with a
single `main` lane and issue-level nodes in the existing reader-visible
order. No adjacency blockers, checkpoints, convergence gates, CBL
provenance, or `sequence_order` changes are proposed.

- `Doctor Strange Epic Collection Vol. 10: Infinity War`: 17 issue nodes, Reading Order id 1
- `Starman Compendiums 1-2`: 66 issue nodes, Reading Order id 2
- `JSA: Robinson / Goyer / Johns`: 57 issue nodes, Reading Order id 3

## Current eligibility baseline

- Thread 105 `Doctor Strange, Sorcerer Supreme`: next unread 2245, persisted blocked=True, derived eligible=False, blockers=#1808 Silver Surfer #67 (reading_plan_order)
- Thread 180 `Starman`: next unread 101798, persisted blocked=False, derived eligible=True, blockers=none
- Thread 393 `The Shade`: next unread None, persisted blocked=False, derived eligible=False, blockers=none
- Thread 3173 `Batman/Hellboy/Starman`: next unread None, persisted blocked=False, derived eligible=False, blockers=none
- Thread 17060 `Doctor Strange, Sorcerer Supreme Annual`: next unread None, persisted blocked=False, derived eligible=False, blockers=none
- Thread 17061 `Silver Surfer`: next unread 115324, persisted blocked=True, derived eligible=False, blockers=#2778 Marvel Graphic Novel (1982 - 1993) #1 (reading_plan_order)
- Thread 17062 `Spider-Man/Dr. Strange: The Way to Dusty Death`: next unread 2252, persisted blocked=True, derived eligible=False, blockers=#1810 Doctor Strange, Sorcerer Supreme #47 (reading_plan_order)
- Thread 17194 `JSA (Robinson / Goyer / Johns)`: next unread 101817, persisted blocked=True, derived eligible=False, blockers=#1833 Starman #55 (reading_plan_order)

## Safety

No production state was changed. Legacy Reading Orders remain in place
for rollback. Architecture hold #2363 remains in force. Step 23B has
not started.
