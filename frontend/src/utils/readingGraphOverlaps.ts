/**
 * Presentation helpers for the prospective reading graph (#4020).
 *
 * Everything here is a pure projection of the server's read-only preview. The
 * module never decides eligibility, never relaxes a hold, and never groups
 * series by name: an overlap always names two exact Comic Vine volume
 * identities, so two same-titled runs stay separate decisions (#1615).
 */

import type {
  ReadingGraphChoiceEffect,
  ReadingGraphOverlap,
  ReadingGraphOverlapChoice,
  ReadingGraphOverlapChoiceId,
  ReadingGraphPreview,
  ReadingGraphPreviewRequest,
  ReadingGraphSeriesNode,
  ReadingGraphSeriesReference,
} from '../services/api-reading-graph'

/** Reader's answers keyed by the server's stable overlap identity. */
export type ReadingGraphChoices = Record<string, ReadingGraphOverlapChoiceId>

/**
 * Reader-facing label for one exact volume.
 *
 * Two volumes can share a series name, so the year disambiguates them instead
 * of collapsing them into one indistinguishable option.
 *
 * @param series - Exact volume identity from the server.
 * @returns `Name (year)` when a year is known, otherwise `Name`.
 */
export function readingGraphSeriesLabel(series: ReadingGraphSeriesReference): string {
  return series.year === null ? series.series_name : `${series.series_name} (${series.year})`
}

/**
 * Reader-facing label for one comic named by the graph.
 *
 * @param preview - The graph that owns the issue directory.
 * @param issueId - Canonical issue ID named by the server.
 * @returns `Series #Number`, or a stable fallback when the issue is absent.
 */
export function readingGraphIssueLabel(preview: ReadingGraphPreview, issueId: number): string {
  const issue = preview.issues.find((candidate) => candidate.issue_id === issueId)
  if (!issue) return `Issue ${issueId}`
  return `${issue.series_name} #${issue.issue_number}`
}

/**
 * Label several comics for a compact effect list.
 *
 * @param preview - The graph that owns the issue directory.
 * @param issueIds - Canonical issue IDs in server order.
 * @returns The comic labels in the same order.
 */
export function readingGraphIssueLabels(
  preview: ReadingGraphPreview,
  issueIds: number[],
): string[] {
  return issueIds.map((issueId) => readingGraphIssueLabel(preview, issueId))
}

/**
 * Whether the preview contains a genuine series conflict to resolve.
 *
 * A source with no real overlap must never open a questionnaire (#4020).
 *
 * @param preview - Server preview, or `null` while it loads.
 * @returns True when at least one overlap question exists.
 */
export function hasGenuineOverlap(preview: ReadingGraphPreview | null): boolean {
  return Boolean(preview && preview.overlaps.length > 0)
}

/**
 * The answer that currently applies to one overlap.
 *
 * A local answer wins over a previously saved one so the reader's newest
 * choice is reflected before the server round-trip completes.
 *
 * @param overlap - One conflict question.
 * @param choices - Answers made during this preview session.
 * @returns The effective answer, or `null` while the reader has not decided.
 */
export function effectiveOverlapChoice(
  overlap: ReadingGraphOverlap,
  choices: ReadingGraphChoices,
): ReadingGraphOverlapChoiceId | null {
  return choices[overlap.overlap_id] ?? overlap.selected_choice ?? null
}

/**
 * Every overlap that still needs an answer.
 *
 * @param preview - Server preview, or `null` while it loads.
 * @param choices - Answers made during this preview session.
 * @returns Conflicts in server order, each without an effective answer.
 */
export function unresolvedOverlaps(
  preview: ReadingGraphPreview | null,
  choices: ReadingGraphChoices,
): ReadingGraphOverlap[] {
  if (!preview) return []
  return preview.overlaps.filter(
    (overlap) => effectiveOverlapChoice(overlap, choices) === null,
  )
}

/**
 * Build the answers payload for a graph preview or a commit.
 *
 * @param preview - Server preview, or `null` while it loads.
 * @param choices - Answers made during this preview session.
 * @returns One entry per answered conflict, in server order.
 */
export function overlapChoicePayload(
  preview: ReadingGraphPreview | null,
  choices: ReadingGraphChoices,
): ReadingGraphOverlapChoice[] {
  if (!preview) return []
  return preview.overlaps.flatMap((overlap) => {
    const choice = effectiveOverlapChoice(overlap, choices)
    return choice === null ? [] : [{ overlap_id: overlap.overlap_id, choice }]
  })
}

/**
 * Build the read-only graph preview request for the current selection.
 *
 * @param includedPositions - Included CBL source positions, in source order.
 * @param preview - Server preview that names the conflicts.
 * @param choices - Answers already made.
 * @returns The request body for the graph preview endpoint.
 */
export function buildReadingGraphRequest(
  includedPositions: number[],
  preview: ReadingGraphPreview | null,
  choices: ReadingGraphChoices,
): ReadingGraphPreviewRequest {
  return {
    included_positions: [...includedPositions].sort((left, right) => left - right),
    overlap_choices: overlapChoicePayload(preview, choices),
  }
}

/**
 * Explain one prospective effect in reader language.
 *
 * The labels come straight from the server's issue directory, so the dialog and
 * the committed graph describe the same comics.
 *
 * @param preview - The graph that owns the issue directory.
 * @param effect - Server-provided effect of one answer.
 * @returns Comic labels that can roll, comic labels that wait, and whether the
 *   answer changes anything at all.
 */
export function describeOverlapEffect(
  preview: ReadingGraphPreview,
  effect: ReadingGraphChoiceEffect,
): { rollable: string[]; waiting: string[]; changesAnything: boolean } {
  return {
    rollable: readingGraphIssueLabels(preview, effect.rollable_issue_ids),
    waiting: readingGraphIssueLabels(preview, effect.waiting_issue_ids),
    changesAnything:
      effect.rollable_issue_ids.length > 0 || effect.waiting_issue_ids.length > 0,
  }
}

/**
 * Reader-facing status for one series node.
 *
 * @param node - Series node from the server preview.
 * @returns A short status such as `Can continue` or `Waits`.
 */
export function readingGraphSeriesStatus(node: ReadingGraphSeriesNode): string {
  switch (node.state) {
    case 'continues':
      return 'Can continue'
    case 'waits':
      return 'Waits'
    case 'mixed':
      return 'Partly waits'
  }
}

/**
 * One-line graph totals for the inline summary.
 *
 * @param preview - Server preview.
 * @returns Counts of series, rollable comics, and waiting comics.
 */
export function readingGraphSummaryLine(preview: ReadingGraphPreview): string {
  const seriesCount = preview.series.length
  return `${seriesCount} series · ${preview.rollable_issue_ids.length} rollable · ${preview.waiting_issue_ids.length} waiting`
}

/**
 * The chosen answer's label for one overlap.
 *
 * @param overlap - One conflict question.
 * @param choices - Answers made during this preview session.
 * @returns The chosen reader-facing label, or `null` when undecided.
 */
export function overlapDecisionLabel(
  overlap: ReadingGraphOverlap,
  choices: ReadingGraphChoices,
): string | null {
  const choice = effectiveOverlapChoice(overlap, choices)
  if (choice === null) return null
  const effect = overlap.choices.find((candidate) => candidate.choice === choice)
  return effect?.label ?? null
}

/**
 * The series labels a waiting series holds in the current graph.
 *
 * @param preview - The graph that owns the issue directory.
 * @param node - Series node whose holds should be named.
 * @returns Comic labels the series currently waits for.
 */
export function readingGraphWaitLabels(
  preview: ReadingGraphPreview,
  node: ReadingGraphSeriesNode,
): string[] {
  return readingGraphIssueLabels(preview, node.waits_for_issue_ids)
}

/**
 * Append a local answer to an overlap without re-deriving any graph state.
 *
 * The merge only records the reader's selection; the next server preview owns
 * the resulting blockers and rollable comics.
 *
 * @param preview - Server preview to annotate.
 * @param choices - Answers made during this preview session.
 * @returns The preview with local answers applied to its overlap objects.
 */
export function withLocalChoices(
  preview: ReadingGraphPreview,
  choices: ReadingGraphChoices,
): ReadingGraphPreview {
  if (Object.keys(choices).length === 0) return preview
  return {
    ...preview,
    overlaps: preview.overlaps.map((overlap) =>
      overlap.overlap_id in choices
        ? { ...overlap, selected_choice: choices[overlap.overlap_id] }
        : overlap,
    ),
  }
}
