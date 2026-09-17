# Reading Graph persistence design

**Date:** 2026-09-17  
**Scope:** Documentation-only deliverable for issue #2537.  
**Authority:** [READING_GRAPH_ADR.md](READING_GRAPH_ADR.md), accepted 2026-09-16.

This design does not authorize a migration, production access, runtime cutover, API/UI change,
or deletion. Architecture hold #2363 remains in force. The ADR supersedes older recovery
recommendations about runtime authority; their recorded data observations remain useful evidence.

## Recommendation

Keep Thread/Issue progression and the existing issue-to-issue Dependency identity. Replace plan
JSON membership with ordinary Issue foreign keys; replace rule-note ownership with a many-to-many
plan/dependency join. Preserve source snapshots and source occurrences separately from reader
presentation. No polymorphic executable references, graph extension, generalized owner resource,
or peer ordering service is needed.

A plan is a collection, not a second eligibility engine. Its order, lanes, source positions,
optional flags, and import revisions never independently block Roll. A hard requirement is a
canonical Dependency; multiple incoming Dependencies require all source Issues to be read.

## 1. Current schema and state inventory

### Evidence boundary

This audit inspected checkout `b58b4855` and recorded operator evidence, not a live database.
The ADR records that current production plans use issue nodes and current rules have issue
endpoints. That statement is not an exhaustive, current row-level census. No production connection
or write was made for this document. The following observations are dated, not claims about
unchanged September 17 production counts:

| Recorded state | Evidence and interpretation |
| --- | --- |
| September 7: zero plans, three Reading Orders/140 items, 1,686 legacy-backed rules for user 1 | [Step 7 inventory](https://github.com/JoshCLWren/comic-pile/issues/2366#issuecomment-5575624189). Historical baseline, superseded by later imports. |
| Real-reader B.P.R.D. plan 6 had 22 nodes, pending explicit adoption | [Production status](https://github.com/JoshCLWren/comic-pile/issues/2366#issuecomment-5610629569). Do not substitute disposable acceptance-account plan 15 for this reader's plan. |
| September 12: informational plans 16 Doctor Strange (17 Issues), 17 Starman (66), 18 JSA (57); legacy 140 items retained, four standalone prerequisites preserved | [Production apply and independent verification](https://github.com/JoshCLWren/comic-pile/issues/2366#issuecomment-5643218385). No plan-owned hard constraints created by that migration. |
| Ultimate Universe plan 19: strict sequential, 130 source-backed nodes; 131 plan-owned rules: 117 `item_read`, 14 `converged`; twelve standalone adjacent rules reused without reownership | [Step 24 production cutover](https://github.com/JoshCLWren/comic-pile/issues/2366#issuecomment-5646791964). Concrete persisted convergence and reuse evidence. Group 15 retained 130 memberships with no sequence values. Rule count is not expanded edge count. |
| September 13: eleven manifests created plans 21–31 and retired 119 reader-order Dependencies | [Recovery checkpoint](recovery/READER_WORKFLOW_RECOVERY_PROGRESS.md), lines 6–41, and [operator checkpoint](https://github.com/JoshCLWren/comic-pile/issues/2482#issuecomment-5657738115). |
| DC K.O./Ultimate Universe candidates overlap existing plans or rules | Same recovery checkpoint, lines 144–152. This establishes overlap needing reconciliation, not exact shared-Issue tuples. |

The reviewed evidence does **not** supply a complete current plan/Issue intersection census,
all convergence payloads, or every rule ownership note. In particular, it does not prove an exact
pair of production plans sharing a named Issue ID. The ADR requires shared Issues irrespective
of that gap. Before a future data migration, obtain an authorized snapshot with per-plan Issue
sets, their intersections, occurrence counts, gates, and rule links; do not infer missing rows
from plan names or historical counts. This is a migration precondition, not a request to access
production in this documentation task.

The [legacy-order rehearsal evidence](recovery/step23b-legacy-reading-order-migration-rehearsal-evidence.json)
is an isolated clone, not production proof. Likewise,
`tests/test_continuity_plan_writer_rule_reuse.py:143` demonstrates a **synthetic** two-plan ownership
conflict, not successful shared production ownership. These distinctions prevent a design based
on fabricated production completeness.

### Persisted resources

References below are checkout paths and line numbers; all proposed names in section 2 are new
design names, not assertions that those tables already exist.

| Current resource | Shape, constraints, and persistence meaning |
| --- | --- |
| `ContinuityPlan` | `id` PK; `user_id` FK with cascade; `name`; `ordering_mode`; `nodes_json`; `lanes_json`; `created_at`, `updated_at`. User index; no name uniqueness. Membership, lane links, gate references, and source links inside JSON have no database FKs. See `app/models/continuity_plan.py:18`. |
| Plan lanes/nodes | Lane IDs/orders and node IDs/lane-local positions are application-unique. Node `ref_id` is not unique: two occurrences may reference the same Issue. Strict mode requires one lane and contiguous zero-based positions, excluding thread nodes. Informational mode still allows checkpoint/convergence blockers. See `app/schemas/continuity_plan.py:23–185`. |
| `Dependency` | `id` PK, non-null Issue FKs `source_issue_id`/`target_issue_id` with cascade, unique endpoint pair, `created_at`, nullable `note`. No owner column; ownership follows endpoints through Thread. No database self-edge prohibition in this model. See `app/models/dependency.py:22–39`. |
| `ContinuityRule` | User FK; generalized type/ID endpoints without endpoint FKs; unique `(user_id, source_type, source_id, target_type, target_id)`; satisfaction type; checkpoint Issue FK with restrict; convergence JSON; note; timestamps. Nullable unique `legacy_dependency_id` FK cascades on Dependency deletion. `ContinuityRuleSelectedMember` has rule/Issue FKs and unique pair. See `app/models/continuity_rule.py:21–101`. |
| Compiled rule provenance | Exact note `continuity-plan:<id>` identifies rules deleted/recompiled on save or plan deletion. Any matching prefix prevents standalone reuse, even a malformed marker. Equivalent standalone `item_read` rules are reused unchanged with **no persisted plan link**; another plan's marker causes a conflict. See `app/services/continuity_plan_writer.py:164–225,334–398` and `app/repositories/continuity_repository.py:53–66`. |
| `CBLSource` / `CBLSourceList` | Repository unique; source revision/sync timestamps. List unique by `(source_id, source_path)`, with name, declared count, content hash, revision, active flag, timestamps. These are a mutable source index, not immutable import snapshots. See `app/models/cbl_reference.py:13–60`. |
| `CBLSourceEntry` | List FK with cascade; unique `(list_id, position)`; series/issue labels, volume/publication years, optional external series/issue identity FKs, creation time. No canonical Issue FK/read state. Source entries can repeat an Issue at different positions. See `app/models/cbl_reference.py:63–93`. |
| `CustomCBLList` / `CustomCBLEntry` | Reader-owned name/description/timestamps; entry Issue FK and position, unique `(list_id, position)` and `(list_id, issue_id)`. Editable template, not plan state. See `app/models/custom_cbl.py:13–66`. |
| `ReadingOrder` / `ReadingOrderItem` | Order ID/name/description/user FK; items have order/thread FKs, position, nullable textual `issue_number`. No Issue FK, position uniqueness, source provenance, or timestamps. See `app/models/reading_order.py:11–41`. |
| `DependencyGroup` / membership | Group ID/user/name/created time, unique user/name. Membership has group FK and exactly one nullable thread or Issue FK, unique group/thread and group/Issue; nullable `sequence_order`, with no DB uniqueness/positive check. No dependency-edge relationship or source revision. See `app/models/dependency_group.py:21–94`. |

Issue read state belongs to the canonical Issue everywhere. Thread-local `Issue.position` and
`Thread.next_unread_issue_id` remain unchanged. Neither group membership nor ReadingOrder items
are evidence that every neighboring pair is a hard dependency.

### Source and compatibility writer facts

- `app/cbl_ingest.py:60–143` records one-based XML positions and raw content hashes.
  `app/cbl_sync.py:138–237` replaces entries when content changes; unchanged lists retain their
  previous revision even when repository revision advances. Entry IDs are not durable occurrence IDs.
- `app/services/cbl_targeted_plan_adoption.py:67–160` checks reviewed revision/hash when supplied,
  but stored placements retain only path/position. Existing Issues are reused and new nodes appended.
  Reconstructing import revision from the latest source row would invent history.
- Source strings have three observed conventions: bare path in CBL adoption, `repository:path`
  in derived templates, and `custom-cbl:<id>` in custom application. Preserve the raw value and
  resolve namespaces explicitly; do not split arbitrary paths on a colon and assume identity.
- `app/services/cbl_plan_adoption.py:450–545` deduplicates by Issue and records at most one
  placement per path in that path. A repeated source occurrence may already have been lost.
  A future migration cannot recreate it as known reader intent.
- `app/services/custom_cbl.py:128–153,185–357` uses zero-based positions, rewrites entries,
  preserves Issues outside the target lane, and reuses/reorders target-lane nodes. Removing a
  template entry does not delete the Issue from the plan. Deleting the template leaves plan
  provenance strings intact. Export uses current title/issue number, not a historical source snapshot.
- `app/services/reading_order_adoption.py:71–138` makes thread nodes from legacy items and
  does not copy item `issue_number` or description. Projection in
  `app/services/reading_order_projection.py:227–293,349–369` rewrites thread items and drops
  issue labels. Neither is a lossless Issue-membership migration algorithm.
- Group APIs validate ownership and positive, unique explicit order values in application code
  (`app/api/dependency_group.py:552–765`); unordered and thread members remain possible.
  Historical rebuild tooling is not a generic migration and must not be run by this audit.

## 2. Proposed minimal relational shape

Use the existing `continuity_plans` identity as ReadingPlan, preserving IDs and timestamps; a
physical rename to `reading_plans` is optional cleanup, not a prerequisite. The following six
plan-family tables are sufficient. Source placements are separate because an Issue can appear
in multiple sources or more than once in one source. Membership occurrences preserve existing
valid JSON without creating another executable node type.

| Table | Columns and integrity rules |
| --- | --- |
| `reading_plans` (logical name) | Existing `id` PK, `user_id` FK, `name`, timestamps. Nullable `description` preserves legacy order/custom descriptions when actually migrated. Small `presentation_json` for historical type/display settings only; no Issue IDs, hard-edge authority, or read state. No unique name requirement. |
| `reading_plan_lanes` | `plan_id` FK, `lane_id` string, `name`, nonnegative `display_order`; PK `(plan_id, lane_id)`, unique `(plan_id, display_order)`. Lane is presentation only. Optional `migration_evidence_json` retains the server-authored historical contract without interpreting its IDs as live references. |
| `reading_plan_issues` | `plan_id`, `occurrence_id` (preserve node `id`), non-null `issue_id` FK, `lane_id`, nonnegative `display_position`; PK `(plan_id, occurrence_id)`; composite FK `(plan_id, lane_id)` to lanes; unique `(plan_id, lane_id, display_position)`; index `(plan_id, issue_id)` and reverse Issue lookup. `label`, `reader_role`, nullable `reader_optional`, `is_checkpoint` are presentation fields; `source_metadata_json` holds advisory classification/story-arc annotations. |
| `reading_plan_dependencies` | `plan_id` FK, `dependency_id` FK; composite PK. Optional human explanation, not an ownership marker. Reverse dependency index. Zero, one, or many plans reference the same edge. Endpoint membership in the referencing plan is **not** required: a separate plan's frontier may depend on an external Issue. |
| `reading_plan_sources` | `id` PK; `plan_id` FK; `raw_source_path`, nullable resolved `repository`, `source_path`, `revision_sha`, `content_hash`; nullable `cbl_source_list_id` FK and `custom_cbl_list_id` FK; nullable historical `adopted_at`; non-null `recorded_at`; `metadata_json` for retained name/description and missing-provenance explanation. At most one of the two source FKs is populated; neither is required for unresolved/deleted historical sources. Unique `(plan_id, id)` supports composite child FKs. Snapshot identity is immutable: unique `(plan_id, raw_source_path, repository, source_path, revision_sha, content_hash)` with NULLS NOT DISTINCT for idempotent import of unknown legacy identity. |
| `reading_plan_source_placements` | `id` PK, `plan_id`, `occurrence_id`, `plan_source_id`, nullable `source_position`; composite FKs to `(plan_id, occurrence_id)` and `(plan_id, id)` above. Unique `(plan_id, occurrence_id, plan_source_id, source_position)` with NULLS NOT DISTINCT. Null position means known source association but no recorded placement. Multiple positions from one source may explain one Issue occurrence. Preserve original position, including legacy values, rather than conflating it with display rank. |

`reading_plan_issues` is the explicit ReadingPlan–Issue join. It deliberately does **not** have
unique `(plan_id, issue_id)`: the schema currently permits repeated Issue occurrences with
separate lane/label context. Unique membership is its `SELECT DISTINCT plan_id, issue_id`
projection; progress counts distinct Issues, not duplicate occurrences. There is no need for
both a distinct-membership table and a separate generalized node table.

For example, `(P, 'jsa-5', I)` and `(Q, 'event-12', I)` reference the same Issue I. A second
occurrence `(P, 'recap-5', I)` adds display context, not another read state. Reading I advances
both P and Q once. Neither plan is merged into the other.

Keep `dependencies` and its unique `(source_issue_id, target_issue_id)` identity. Recommend a
non-self check for future writes/backfill, after existing invalid rows are inventoried; global
cycle rejection requires transactional service validation, not just a CHECK. Resolve or reuse
the edge under its uniqueness constraint, then insert `(P, edge)` and `(Q, edge)` links. A race
to insert the same pair must yield one edge and two links, not a note conflict.

### Referential integrity and lifecycle

- All identity links above use ordinary FKs. Do not use `(owner_type, owner_id)` or generalized
  node IDs. Optional source cache FKs use SET NULL; immutable snapshot text survives refresh/deletion.
  This is not a polymorphic FK: CBL and custom list references name concrete tables.
- Plan deletion cascades only to plan-local lanes, occurrences, source snapshots/placements,
  and dependency links. It never cascades to Issues or Dependencies. Lane/occurrence replacement
  is a deliberate transaction, not an implicit source-refresh operation.
- Issue deletion can cascade through occurrence and endpoint FKs, and placements through their
  occurrence FK. Dependency deletion cascades to its plan links. A global edge removal must
  expose every affected plan and require explicit authorization; ordinary plan editing only
  unlinks that plan. **No automatic last-link garbage collection.** Standalone Dependencies
  legitimately have zero plan links. This conservative lifecycle needs no single-owner flag
  and cannot erase independent or shared intent based on absence of links.
- An explicit future “remove hard requirement” operation is distinct from removing membership.
  It may delete an edge after checking all plan references and independent intent in one
  transaction. Do not preserve today's implicit note-based delete/recompile behavior.
- FKs prove existence, not tenant ownership. Services must verify both endpoint Issues through
  `Issue.thread_id → Thread.user_id`, the plan owner, and any custom source owner in the same
  write transaction. Do not imply current models have composite tenant FKs. Plan and relevant
  edge mutations must serialize ownership/reference checks to avoid a check/delete race.
- Snapshot fields are not overwritten by source-index sync. Refresh creates a new reviewed
  source snapshot/placement set and applies only accepted membership/display changes, preserving
  reader edits. Known repository/revision/path identifies source content; `content_hash` records
  exact bytes when known. A deleted or unavailable revision is reported, not silently replaced
  with HEAD. A custom template has no Git SHA: retain a content hash if available, otherwise
  explicit unknown provenance. Do not invent an adoption timestamp from migration time.

The plan/source and plan/dependency joins preserve the evidence that exists today. They do not
invent per-edge CBL causation: a source's presence in a plan does not prove it authored every
edge. Current rule markers carry no revision-level edge attribution. If later explicitly authored
per-edge source evidence is required, an ordinary composite-FK dependency-link/source join can
be added then; no generalized provenance table is justified now.

## 3. Complete field and semantic disposition

Categories: **N** normalized first-class data; **P** presentation metadata; **S** source/provenance;
**D** derivable, not separately authoritative; **L** legacy/transitional, removable after cutover.

| Current persisted field or semantic | Category and destination |
| --- | --- |
| Plan `id`, `user_id`, `name`, `created_at`, `updated_at` | N: preserve on logical ReadingPlan; do not change IDs merely to rename the product. |
| `ordering_mode` | P/L: retain original value as historical display metadata. Strict order is no longer an automatic compiler setting. Classify existing hard intent separately before removing the compiler. |
| `nodes_json` array | L: replace with Issue occurrence rows; keep a migration snapshot until reconciliation succeeds. It must no longer be canonical membership. |
| Node `id`, issue `ref_id` | N: `occurrence_id` and Issue FK. Resolve gates by old node ID before dropping the JSON. |
| Node `node_type` | L for executable type; only Issue survives. Thread/crossover references need explicit resolution described below, not a polymorphic target column. |
| Node `lane_id`, `position`, `label` | P stored in normalized occurrence/lane columns; lane-local display position is not `Issue.position` or CBL position. |
| `source_role`, `source_confidence`, `source_explanation` | S: preserve advisory values in occurrence source metadata, never execution authority or reader override. |
| `source_paths` | S: snapshot association plus nullable-position placement. D: distinct plan source-path listing can then be computed. Preserve raw ambiguous/unresolved strings. |
| `source_cbl_placements[].source_path`, `.position` | S/N: source snapshot plus placement rows; preserve path/position pairing, repeated occurrences, and original position base. Existing data lacks repository/revision, so leave those unknown unless independently proven. |
| `source_story_arc_ids`, `source_target_story_arc_id` | S: retain string annotations in source metadata; not proven canonical Issue or external-identity FKs. |
| `reader_role`, `reader_optional` | P: retain per occurrence, including explicit false versus null. They do not change global read state or silently remove hard edges. |
| `is_checkpoint` | P plus explicit N edge where a hard requirement exists. Compiler meaning is checkpoint Issue → next node in its lane, not all prior nodes → checkpoint. Final-lane checkpoint produces no edge. |
| `convergence_gate[].node_type`, `.node_id` | N: resolve actual referenced Issue IDs to incoming Dependencies and plan links. L: JSON gate IDs/type tags disappear. D: incoming blocker view derives from linked edges; a convergence display badge may remain presentation-only. |
| `lanes_json` lane `id`, `name`, `order` | P: normalized lane rows. L: the containing JSON document can disappear. |
| Lane `migration_contract.kind`, `classification_family_keys`, `selected_dependency_ids`, `issue_ids`, `edges`, `issue_fingerprint`, `edge_fingerprint` | S/L: preserve the complete server-owned historical evidence object or archive it with cutover evidence. Selected IDs may name deleted rows; do not pretend they are live FKs or copy them into current runtime constraints. Retire from active storage once replay consumers are gone. |
| Rule `id`, timestamps | S/L: retain old-to-new mapping in migration evidence; the canonical Dependency may already have its own ID/timestamps. Do not overwrite existing edge creation history. |
| Rule `user_id`, endpoint types/IDs, satisfaction type | N reduction into owned Issue Dependencies; L generalized wrapper removed only after semantic reconciliation. |
| Rule `checkpoint_issue_id`, `convergence_targets`, selected-member rows | N reduction described below; L original wrappers after cutover. No surviving JSON executable references. |
| Rule `note` and `legacy_dependency_id` | S/N: exact plan markers become many-plan links; legacy FK is a reuse candidate, verified by endpoint pair. Preserve useful prose in evidence/edge explanation; malformed/orphan markers require review. L: marker-based ownership and mirror linkage retire. |
| Dependency endpoint IDs, ID, timestamp, prose note | N: retain canonical edge identity and useful explanation. L: any note-as-owner interpretation. Classify bulk-generated history before making rows authoritative. |
| CBL repository/path/revision/hash/position | S: immutable per-plan source snapshot and placement; cache FKs optional. Source name, declared count, active/sync timestamps and entry labels/years/identity references remain template-index metadata, not execution data. |
| Custom CBL user/name/description, entry Issue/position, timestamps | S: editable template retained separately; on adoption preserve known template identity/description and placements. No automatic synchronization of a reader plan. |
| ReadingOrder user/name/description, item IDs/thread/position/issue label | N for accepted resolved Issue memberships; P name/description/order; S original item identity/labels and unresolved associations in migration evidence. L old resource after all references and consumers migrate. |
| DependencyGroup user/name/created time, membership thread/Issue IDs, `sequence_order` | N owned Issue membership after reviewed conversion; P name/order and historical crossover designation; S legacy IDs/unresolved thread membership in evidence. L group-only execution/resource distinction. Null order stays unordered, never a fabricated hard chain. |
| Progress/readiness/source-path summaries, lane/step counts | D: Issue read state + distinct memberships; canonical Dependencies for eligibility; presentation occurrences for step count. No second persisted plan progress or readiness state. |

New-plan serialization currently strips client migration contracts; updates preserve server
contracts by lane ID (`app/services/continuity_plan_writer.py:41–65`). Preserve that trust boundary
during transition. The old fingerprints describe historical classified intent, not necessarily
the latest reader-edited plan.

## 4. Concrete rule and JSON conversion

Build an explicit mapping `(old_plan_id, old_node_id) → (occurrence_id, issue_id)` before resolving
any gate. Validate actual node references, not supplied gate type tags. Preserve all occurrences;
deduplicate only execution pairs. Missing references, duplicate resolved prerequisites, conflicting
aliases, foreign-owned Issues, and document/rule discrepancies are preflight exceptions, not an
invitation to guess or silently discard fields.

| Existing constraint | Canonical reduction |
| --- | --- |
| `item_read`, issue A → issue B | A → B, reusing the existing Dependency pair if present. Link every plan that requires it, including plans that reused an unmarked standalone rule. |
| Plan checkpoint B in lane A/B/C | B → C if it represents retained hard intent; the checkpoint badge remains on B. No edge from a terminal checkpoint. |
| Standalone checkpoint with Issue target D | `checkpoint_issue_id` → D; the stored source ID need not be the satisfaction Issue. |
| D has gate references B and C; stored rule D → D, `converged`, targets B/C | B → D and C → D. Never D → D. Union/deduplicate pairs across rules/plans after checking contradictions; both incoming prerequisites are required. |
| Strict-sequential adjacent rule | Audit intended hard constraint, not just its presence. Retain actual exceptional prerequisites; do not regenerate all display/CBL adjacency or natural Thread neighbors. |
| Explicit reader-order migration lane | Its topologically sorted display order is not a hard chain. Preserve the classified partial-order pairs evidenced by gates/contracts and actual rules, not all displayed neighbors. |
| Crossover endpoints, `all_members_read`, `selected_members_read` | Resolve only with reviewed concrete prerequisite Issue sets and target Issue frontiers. Selected-member Issue FKs are evidence; evolving crossover membership is not a durable executable node. No blind full Cartesian expansion. |
| Thread/crossover plan membership or a legacy item with issue label | Resolve against owned Thread Issues and explicit recorded scope. Keep unambiguous Issue references; ambiguous issue labels, whole-thread scope, and unmatched legacy references require a reviewed mapping before that record cuts over. Never substitute current next-unread for historical membership. |

For plan P containing B/C/D and plan Q containing D/E, a shared B → D edge can have links to
both P and Q even when Q does not contain B. P may also link C → D. Reading B alone does not
unblock D until C is read. Removing P's membership or source snapshot cannot erase Q's B → D
edge or reset D's read state. Natural D → next issue in D's Thread needs no materialized edge.

The current compiler ignores optional/skipped flags when compiling adjacency/checkpoints/gates
(`app/services/continuity_plan_writer.py:228–291`). Filtering those nodes or reconnecting their
neighbors during backfill would change constraints. Conversely, blindly carrying all historical
CBL adjacency into the new runtime violates the ADR. Compare intended edge sets, retain explicit
reader requirements, and record approved removals of redundant natural/source order separately.
Do not use `ordering_mode` alone to decide that intent.

Reuse reconstruction must compare plan semantics and persisted rule endpoints, not just notes.
Exact valid markers link known plans; standalone reused rules need additional plan links; unknown
prefixes/orphan owners remain exceptions. A rule-count equality check is insufficient: the
synthetic partial-order case in `tests/test_explicit_reader_order_migration.py:169–229` has three
edges represented by two converged wrappers. The Ultimate Universe recorded production totals
likewise cannot be copied into an expected Dependency count.

## 5. Risks and smallest safe migration sequence

This is a recommendation for separately authorized implementation, not a recovery runbook or
executable SQL. Four bounded phases suffice; no architecture rewrite or mandatory historical
bulk-data purge is needed.

1. **Inventory and rehearse on an authorized snapshot.** Record raw plan documents, lane contracts,
   legacy associations, source strings, rule/Dependency IDs and expanded intended edge pairs.
   Include all plans, shared-Issue intersections, repeated occurrences, convergence, standalone
   reuse, and unknown provenance. Produce deterministic old-to-new mappings and a finite exception
   list; reconcile ambiguous rows before their cutover. Preserve global read state and Thread
   frontier baselines. Historical production reports above guide cases, not current expected counts.
2. **Add relational plan storage and backfill without runtime change.** Preserve plan identities,
   fill lanes/occurrences/source snapshots, and compare distinct membership plus presentation and
   provenance round trips. Use one transactional writer or a brief write pause for reconciliation,
   not indefinite dual writes. Existing Dependencies may be linked without re-creation. Do not
   insert converted rules into live Dependencies while the compatibility bridge is still active.
3. **Perform the coordinated, separately approved edge/runtime cutover.** Account for the bridge
   in `alembic/versions/c84400000002_sync_legacy_dependency_writes.py:69–121`: Dependency writes
   currently upsert rules and can replace satisfaction/provenance; deletion cascades linked rules.
   Replace/retire that bridge and legacy compilers/writers as one controlled deployment boundary,
   materialize only classified canonical hard pairs, attach all plan links, and switch the audited
   runtime reader to Thread frontier + Dependencies. Keep historical bulk CBL-generated rows inert
   through the explicitly audited legacy exclusion boundary; never turn on an unfiltered scan of
   every existing Dependency. Runtime-audit implementation must prove that boundary before switch;
   this design does not introduce a new competing eligibility mechanism. Compare eligibility
   against the approved intended constraints, not accidental redundant source blockers.
4. **Remove obsolete storage after verified cutover.** Keep the pre-cutover snapshot and mapping
   evidence until the rollback window closes. Before accepting new-only writes, rollback can
   restore the unchanged legacy reader/writer and snapshot together. After new shared-edge/source
   semantics are accepted, an old reader cannot represent them safely: use a verified reverse
   conversion or forward fix, never merely flip back to single-owner rules. Drop retired columns,
   rule machinery, and compatibility resources only after no consumer still reads/writes them.

The most material risks are source revisions that were never persisted; dangling JSON references;
repeated-Issue aliases collapsing gates; differing position namespaces; stale ownership markers;
concurrent shared-edge edits; trigger-driven provenance overwrite; and accidentally reactivating
bulk CBL adjacency. Missing historical facts stay explicitly unknown. No migration may treat
unknown as proof of safety or discard the affected plan.

### Focused verification contract for that future migration

These are required test cases for implementation, not tests claimed to have run in this docs PR:

- Round-trip every field in section 3, including null/false distinctions, lane evidence, multiple
  source paths/positions, repeated Issue occurrences, and unresolved provenance.
- P/Q share I and edge B → D: one global read state, one executable pair, two links; independent
  plan deletion/unlink cannot delete the edge. Standalone zero-link edges survive. Concurrent
  equivalent inserts converge without ownership conflicts.
- D waits on B and C: two incoming pairs, no self-edge; checkpoints block the next lane node;
  informational mode may still contain explicit gates; display order creates no extra pairs.
- Source refresh/deletion preserves plan memberships, reader order/overrides, and old snapshot
  revision. Same path in different repositories and repeated source occurrences stay distinct.
- Reject dangling FKs, cross-plan lane/source references, foreign-user endpoints, self-edges and
  cycles. Resolve unsupported legacy references explicitly rather than suppressing failures.
- Backfill with the old bridge cannot overwrite rules; cutover keeps historical bulk rows inert,
  leaves read state/frontiers unchanged, and matches approved expanded edge sets/eligibility.

Existing regression evidence to reuse when implementation is authorized includes
`tests/test_continuity_plan_api.py:452–649` (checkpoints/convergence),
`tests/test_continuity_plan_writer_rule_reuse.py:79–209` (standalone reuse/current conflict), and
`tests/test_explicit_reader_order_migration.py:169–229` (partial order). The ownership-conflict
expectation must eventually be replaced by shared-edge success coverage, not deleted to hide a
failure. This documentation-only change alters no tests or behavior.

## 6. Delete/retain boundary after successful cutover

**Delete after replacement consumers and rollback evidence are verified:** `nodes_json` and
`lanes_json`; executable interpretation of ordering mode/checkpoint/convergence JSON; compiled
`ContinuityRule` and selected-member tables; note-owner parsing/conflicts/delete-recompile paths;
legacy dependency-to-rule triggers/FKs; rule readiness readers; ReadingOrder/ReadingOrderItem
and DependencyGroup/Membership only once their useful memberships/presentation/provenance and
remaining UI/import consumers have migrated. Remove `sequence_order` as execution authority,
not as an excuse to lose reader presentation. Archive lane migration proof when replay tooling
is retired. Historical bulk CBL Dependency deletion is separately proven cleanup, not a cutover
prerequisite.

**Retain:** Thread order/frontier, global Issue read state, canonical Dependencies, independent
Reading Plans with relational membership and many-plan edge links, presentation-only lanes and
annotations, immutable import provenance, external identity evidence, and the configured CBL
Git template library. Mutable source tables may remain an index/cache, never the universe of
available templates or runtime authority. Custom CBL persistence remains template compatibility
until its import/export replacement is ready; this audit does not delete it or design that UI.

## Documentation validation

The focused local check is `python -B scripts/check_markdown_docs.py`, plus whitespace/diff scope
review. The Documentation workflow's full commands are
`uv run python scripts/check_markdown_docs.py` and
`uv run python -m pytest -q --no-cov tests/test_markdown_docs.py tests/test_generate_markdown_inventory.py`
(`.github/workflows/docs.yml:43–45`). No Python/frontend source, schema, migration, runtime rule,
or production data changes belong in this PR.
