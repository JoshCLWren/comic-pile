import type { components } from '../../generated/openapi'

type ComicVineMappingHealth = components['schemas']['ComicVineMappingHealth']

/**
 * Minimal shape the manual Roll picker can label. Queue list rows
 * (`ThreadListItem`) and bootstrap summary threads (`RollBootstrapThread`)
 * both satisfy it; every disambiguating field is optional.
 */
export interface ManualPickerThread {
  id: number
  title: string
  format: string
  tags?: Array<{ name: string }>
  /** Next unread issue number for queue-backed rows. */
  next_unread_issue_number?: string | null
  /** Next/current issue number carried by some bootstrap summaries. */
  issue_number?: string | null
  issues_remaining?: number | null
  comicvine_mapping?: ComicVineMappingHealth | null
}

/** One rendered picker choice. */
export interface ManualPickerOption {
  /** Thread id, used as the option value so the submit target is exact. */
  id: number
  /** Full accessible label; disambiguated when base labels collide. */
  label: string
}

/** The picker's two rendered option groups. */
export interface ManualPickerGroups {
  activeOptions: ManualPickerOption[]
  snoozedOptions: ManualPickerOption[]
}

type PickerGroup = 'active' | 'snoozed'

interface PickerRow {
  group: PickerGroup
  thread: ManualPickerThread
  baseLabel: string
  label: string
}

/**
 * Issue #3704: the Roll "Pick manually" select must never show two
 * indistinguishable options. Same-named series (real duplicate Queue rows,
 * re-added series, blank QA titles) carry no year/volume field on the list
 * schema, so disambiguation relies on next-issue progress, issue counts,
 * mapping health, and finally the thread id.
 */

/**
 * Build the quiet base label: `Title (Format)` plus visible tag names.
 *
 * Args:
 *     thread: The thread row to label.
 *
 * Returns:
 *     The compact label used when it is already unique.
 */
function buildBaseLabel(thread: ManualPickerThread): string {
  const tagNames = (thread.tags ?? []).map((tag) => tag.name).join(', ')
  const base = `${thread.title} (${thread.format})`
  return tagNames ? `${base} · ${tagNames}` : base
}

/**
 * Summarize compact ComicVine mapping health as picker text (issue #2773
 * parity): quiet for fully mapped and non-issue-tracked rows, explicit for
 * rows that still need mapping work or review.
 *
 * Args:
 *     mapping: The mapping-health projection for the row, when present.
 *
 * Returns:
 *     A short label, or an empty string when mapping health needs no mention.
 */
function mappingDetailSegment(mapping?: ComicVineMappingHealth | null): string {
  if (!mapping) return ''
  const metadataMissing = mapping.metadata_missing_count ?? 0
  if (
    (mapping.status === 'fully_mapped' && metadataMissing === 0) ||
    mapping.status === 'not_applicable'
  ) {
    return ''
  }
  if (mapping.status === 'needs_review') {
    return mapping.needs_review_count > 0
      ? `${mapping.needs_review_count} issues need review`
      : 'Review needed'
  }
  if (metadataMissing > 0) {
    return `${metadataMissing} ${metadataMissing === 1 ? 'issue is' : 'issues are'} missing details`
  }
  if (mapping.status === 'partial') {
    return `${mapping.confirmed_issue_count} of ${mapping.tracked_issue_count} mapped`
  }
  return mapping.needs_mapping_count > 0
    ? `${mapping.needs_mapping_count} issues need mapping`
    : 'Mapping needed'
}

/**
 * Build the reader-facing progress segments that distinguish same-named
 * series: next-issue position, remaining count, and mapping health. Uses the
 * same phrasing the Queue card shows for the identical data.
 *
 * Args:
 *     thread: The thread row to describe.
 *
 * Returns:
 *     Detail segments in display order; empty when nothing is known.
 */
function pickerDetailSegments(thread: ManualPickerThread): string[] {
  const segments: string[] = []
  const nextIssueNumber = thread.next_unread_issue_number ?? thread.issue_number
  if (nextIssueNumber) segments.push(`Up next: #${nextIssueNumber}`)
  // `!= null` is the domain check for the optional count: absent (null/undefined)
  // rows show no remaining count, while a real 0 still does.
  if (thread.issues_remaining != null) {
    segments.push(
      `${thread.issues_remaining} issue${thread.issues_remaining === 1 ? '' : 's'} remaining`,
    )
  }
  const mappingDetail = mappingDetailSegment(thread.comicvine_mapping)
  if (mappingDetail) segments.push(mappingDetail)
  return segments
}

/**
 * Normalize a series title for same-name detection by stripping parenthetical
 * year/volume/run metadata.
 */
function normalizeSeriesTitle(title: string): string {
  return title.replace(/\\s*\\([^)]*\\)/g, '').trim()
}

/**
 * Collect the keys that occur on more than one row.
 */
function duplicateKeys(rows: PickerRow[], keyOf: (row: PickerRow) => string): Set<string> {
  const seen = new Set<string>()
  const duplicates = new Set<string>()
  for (const row of rows) {
    const key = keyOf(row)
    if (seen.has(key)) {
      duplicates.add(key)
    } else {
      seen.add(key)
    }
  }
  return duplicates
}

function intoRows(group: PickerGroup, threads: ManualPickerThread[], seenIds: Set<number>): PickerRow[] {
  const rows: PickerRow[] = []
  for (const thread of threads) {
    // One eligible thread renders exactly once, even when a data source
    // repeats the same id; distinct same-named threads are never collapsed.
    if (seenIds.has(thread.id)) continue
    seenIds.add(thread.id)
    rows.push({ group, thread, baseLabel: buildBaseLabel(thread), label: '' })
  }
  return rows
}

/** Append the thread id to still-ambiguous labels so every option stays unique. */
function resolveResidualCollisions(
  rows: PickerRow[],
  duplicateNormalizedTitles: Set<string>,
): void {
  const duplicateLabels = duplicateKeys(rows, (row) => row.label)
  for (const row of rows) {
    if (duplicateLabels.has(row.label)) {
      row.label = `${row.label} · Series #${row.thread.id}`
      continue
    }
    // Same base series name with no other disambiguating text: tie the row to
    // its actual Thread identity instead of leaving it bare (issue #3559).
    // A title that already carries its own parenthetical run/volume metadata
    // is self-identifying, so it keeps the concise label.
    const normalizedTitle = normalizeSeriesTitle(row.thread.title)
    const titleCarriesIdentity =
      normalizedTitle !== '' && normalizedTitle !== row.thread.title.trim()
    if (
      duplicateNormalizedTitles.has(normalizedTitle) &&
      !titleCarriesIdentity &&
      !row.label.includes('·')
    ) {
      row.label = `${row.label} · Series #${row.thread.id}`
    }
  }
}

/**
 * Build the labeled, uniquely disambiguated option groups for the manual
 * Roll picker.
 *
 * Unique rows keep their quiet base label. Rows that collide with another row
 * on `Title (Format) · tags` gain progress detail (next issue, remaining
 * count, mapping health). If the detail still leaves identical labels (no
 * progress data or identical counts), the thread id is appended so a reader
 * can always tell the options apart.
 *
 * Args:
 *     params.activeThreads: Queue list rows shown in the "Active series" group.
 *     params.snoozedThreads: Bootstrap summary rows shown in the "Snoozed series" group.
 *
 * Returns:
 *     Both option groups with one option per eligible unique thread id.
 */
export function buildManualPickerOptions(params: {
  activeThreads: ManualPickerThread[]
  snoozedThreads: ManualPickerThread[]
}): ManualPickerGroups {
  const seenIds = new Set<number>()
  const rows = [
    ...intoRows('active', params.activeThreads, seenIds),
    ...intoRows('snoozed', params.snoozedThreads, seenIds),
  ]

  const duplicateBaseLabels = duplicateKeys(rows, (row) => row.baseLabel)
  const duplicateNormalizedTitles = duplicateKeys(rows, (row) =>
    normalizeSeriesTitle(row.thread.title),
  )
  for (const row of rows) {
    row.label = row.baseLabel
    const ambiguous =
      duplicateBaseLabels.has(row.baseLabel) ||
      duplicateNormalizedTitles.has(normalizeSeriesTitle(row.thread.title))
    if (ambiguous) {
      const details = pickerDetailSegments(row.thread)
      if (details.length > 0) row.label = `${row.label} · ${details.join(' · ')}`
    }
  }
  resolveResidualCollisions(rows, duplicateNormalizedTitles)

  return {
    activeOptions: rows.flatMap((row) =>
      row.group === 'active' ? [{ id: row.thread.id, label: row.label }] : [],
    ),
    snoozedOptions: rows.flatMap((row) =>
      row.group === 'snoozed' ? [{ id: row.thread.id, label: row.label }] : [],
    ),
  }
}
