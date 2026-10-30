import type { CustomCBL } from '../services/api-custom-cbl'
import type { CBLAdoptionPreview } from '../services/api-cbl-sources'
import type { ReplaceEntry } from '../components/CblReplaceReviewPanel'

/**
 * Exact before/after review projection for one Reading List replacement.
 *
 * Named so the owner contract stays explicit instead of widening through an
 * anonymous return type.
 */
interface ReplacementModel {
  before: ReplaceEntry[]
  after: ReplaceEntry[]
  unresolvedCount: number
}

/**
 * Project one CBL source preview onto a Reading List replacement review.
 *
 * Only already-resolved canonical Issues can join a Reading List. Source rows
 * that still need identity resolution are reported separately instead of being
 * guessed. Saved entries that the chosen CBL does not contain stay checked so a
 * replacement never silently discards the reader's own additions.
 *
 * @param list - The exact owned Reading List being replaced.
 * @param preview - Reconciled global CBL source preview.
 * @returns Exact before/after entries plus the count of unresolvable source rows.
 */
export function buildReplacementModel(
  list: CustomCBL,
  preview: CBLAdoptionPreview,
): ReplacementModel {
  const savedByIssue = new Map(list.entries.map((entry) => [entry.issue_id, entry]))
  const before: ReplaceEntry[] = list.entries.map((entry) => ({
    comicId: entry.issue_id,
    title: `${entry.series_name} #${entry.issue_number}`,
    included: true,
    saved: true,
    gate: entry.gate,
    skipped: entry.skipped,
  }))

  const after: ReplaceEntry[] = []
  const sourceIssueIds = new Set<number>()
  let unresolvedCount = 0
  for (const entry of preview.entries) {
    const issueId = entry.resolved_issue_id
    if (issueId === null || entry.adoption_class !== 'existing' || sourceIssueIds.has(issueId)) {
      if (entry.adoption_class !== 'existing' || issueId === null) unresolvedCount += 1
      continue
    }
    const saved = savedByIssue.get(issueId)
    // Collection exclusions can return an owned Issue with
    // `adoption_decision: 'excluded'`. Only a source row the server actually
    // adopted becomes a checked default; an excluded row stays visible only
    // when the reader already saved it, and then as a saved entry rather than
    // a default.
    const sourceIncluded = entry.adopted && entry.adoption_decision !== 'excluded'
    if (!sourceIncluded && !saved) continue
    sourceIssueIds.add(issueId)
    after.push({
      comicId: issueId,
      title: `${entry.series_name} #${entry.issue_number}`,
      series_group_id: entry.series_group_id,
      series_name: entry.series_name,
      volume_year: entry.volume_year ?? entry.publication_year ?? null,
      included: sourceIncluded || saved !== undefined,
      defaultIncluded: sourceIncluded,
      saved: saved !== undefined,
      gate: saved?.gate ?? 'none',
      skipped: saved?.skipped ?? false,
    })
  }

  for (const entry of list.entries) {
    if (sourceIssueIds.has(entry.issue_id)) continue
    after.push({
      comicId: entry.issue_id,
      title: `${entry.series_name} #${entry.issue_number}`,
      included: true,
      manual: true,
      defaultIncluded: false,
      saved: true,
      gate: entry.gate,
      skipped: entry.skipped,
    })
  }

  return { before, after, unresolvedCount }
}

