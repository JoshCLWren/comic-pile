/**
 * Client-side recovery view model for a blocked browser-owned Roll selection.
 *
 * #4350 removes the aggregate bootstrap that used to carry `roll_recovery`.
 * The inputs here are the same owner-scoped resources Roll already consumes:
 * one bounded issue-edge GET for the selected issue, one bounded card batch for
 * the named prerequisite issues, the eligible pool, and the canonical reading
 * graph diagnostics already cached by the Roll page. Nothing is synthesized
 * when the scoped inputs do not report a blocker.
 */
import type {
  GetIssueDependenciesResponse,
  IssueCardsResponse,
  ReadingGraphResponse,
} from '../generated/nativeV2Client'
import type { RollPendingSelection } from './rollPendingSelection'
import type {
  RollRecoveryBlocker,
  RollRecoveryChainNode,
  RollRecoveryDiagnostic,
  RollRecoveryInfo,
  RollRecoveryPrerequisite,
} from '../types/rollBootstrap'

type IssueCard = IssueCardsResponse['items'][number]

export interface RollRecoveryInputs {
  /** Exact browser-owned selection being rolled. */
  pending: RollPendingSelection
  /** Eligible issue ids already fetched for the current die. */
  eligibleIssueIds: readonly number[]
  /** Owner-scoped dependency edges for `pending.issue_id`, when loaded. */
  dependencies: GetIssueDependenciesResponse | null
  /** Bounded cards for the exact prerequisite issue ids named by the edges. */
  prerequisiteCards: readonly IssueCard[]
  /** Canonical owner-scoped reading-graph diagnostics, when cached. */
  graph: ReadingGraphResponse | null
  /** Display title of the selected series, when the visible pool has it. */
  originalTitle?: string | null
}

const MAX_PREREQUISITES = 20

/**
 * Build a bounded recovery envelope, or null when nothing actually blocks the
 * selected issue. A dependency edge whose source card is already read is
 * satisfied and never reported as a blocker.
 */
export function buildRollRecovery({
  pending,
  eligibleIssueIds,
  dependencies,
  prerequisiteCards,
  graph,
  originalTitle,
}: RollRecoveryInputs): RollRecoveryInfo | null {
  if (dependencies == null || dependencies.issue_id !== pending.issue_id) return null

  const eligible = new Set(eligibleIssueIds)
  const cards = new Map(prerequisiteCards.map((card) => [card.issue_id, card]))
  const directBlockers: RollRecoveryBlocker[] = []
  const readablePrerequisites: RollRecoveryPrerequisite[] = []
  const seen = new Set<number>()

  for (const edge of dependencies.incoming) {
    const sourceId = edge.source_issue_id
    const card = cards.get(sourceId)
    // A read prerequisite is satisfied; it must not keep the roll blocked.
    if (card?.status === 'read') continue
    const label = `${edge.source_thread_title} #${edge.source_issue_number}`
    directBlockers.push({
      rule_id: edge.dependency_id,
      source_type: 'issue',
      source_id: sourceId,
      source_label: label,
      satisfaction_type: 'item_read',
      satisfied: false,
      causing_issue_ids: [sourceId],
      causing_member_issue_ids: [],
      note: null,
    })
    if (!seen.has(sourceId) && seen.size < MAX_PREREQUISITES) {
      seen.add(sourceId)
      readablePrerequisites.push({
        node_type: 'issue',
        node_id: sourceId,
        label,
        is_readable: eligible.has(sourceId),
      })
    }
  }

  const diagnostics: RollRecoveryDiagnostic[] = []
  for (const cycle of graph?.cycles ?? []) {
    const touchesPending = cycle.edges.some((edge) =>
      edge.source.issue_id === pending.issue_id || edge.target.issue_id === pending.issue_id)
    if (!touchesPending) continue
    diagnostics.push({
      code: 'cycle_detected',
      node_type: 'issue',
      node_id: pending.issue_id,
    })
  }

  if (directBlockers.length === 0 && diagnostics.length === 0) return null

  const title = originalTitle ?? `Issue ${pending.issue_number ?? pending.issue_id}`
  const chains: RollRecoveryChainNode[][] = readablePrerequisites.map((prerequisite) => [
    {
      node_type: 'issue',
      node_id: prerequisite.node_id,
      label: prerequisite.label,
      is_readable: prerequisite.is_readable === true,
    },
    {
      node_type: 'issue',
      node_id: pending.issue_id,
      label: title,
      is_readable: false,
    },
  ])

  return {
    original_thread_id: pending.thread_id,
    original_thread_title: title,
    direct_blockers: directBlockers,
    readable_prerequisites: readablePrerequisites,
    chains,
    diagnostics,
  }
}
