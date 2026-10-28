import type { CustomCBL, CustomCBLListItem } from '../services/api-custom-cbl'

/**
 * When legacy plan-source provenance lacks a custom-cbl pointer, permit an edit
 * link only after validating a unique, owned list with matching issue identity.
 * This never changes source provenance, list membership, or reading eligibility.
 */
export function verifiedOwnedReadingListForPlan(
  planName: string,
  planIssueIds: readonly number[],
  ownedLists: readonly CustomCBLListItem[],
  listDetail: CustomCBL | null,
): number | null {
  const normalized = planName.trim().toLocaleLowerCase()
  const matching = ownedLists.filter((list) => list.name.trim().toLocaleLowerCase() === normalized)
  if (matching.length !== 1 || !listDetail || matching[0].id !== listDetail.id) return null
  const fromPlan = new Set(planIssueIds)
  const fromList = new Set(listDetail.entries.map((entry) => entry.issue_id))
  if (fromPlan.size === 0 || fromList.size === 0) return null
  const shared = [...fromPlan].filter((issueId) => fromList.has(issueId)).length
  // Allow at most a small parity gap for historical conversion defects; never
  // match unrelated lists merely because their names happen to be equal.
  const required = Math.max(fromPlan.size, fromList.size) < 20 ? 1 : 0.98
  return shared / Math.max(fromPlan.size, fromList.size) >= required ? listDetail.id : null
}
