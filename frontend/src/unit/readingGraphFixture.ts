/**
 * Deterministic reading-graph fixtures for the #1615 overlap scenario.
 *
 * Fourth World `F1 -> F2`, JLI `J1 -> M1 -> J2 -> M2 -> J3`, reader-approved
 * requirement `F2` before `M1`, and only `J1` already read. These identifiers
 * are synthetic, exactly as the product design specifies.
 */

import type {
  ReadingGraphIssueReference,
  ReadingGraphOverlap,
  ReadingGraphOverlapChoiceId,
  ReadingGraphPreview,
  ReadingGraphSeriesNode,
} from '../services/api-reading-graph'

export const ISSUE_IDS = {
  F1: 101,
  F2: 102,
  J1: 103,
  M1: 104,
  J2: 105,
  M2: 106,
  J3: 107,
} as const

export const VOLUME_IDS = {
  fourthWorld: '4050-1971-fourth-world',
  jli: '4050-1987-jli',
  misterMiracle: '4050-1989-mister-miracle',
  misterMiracleModern: '4050-2019-mister-miracle',
} as const

const ISSUES: ReadingGraphIssueReference[] = [
  { issue_id: ISSUE_IDS.F1, series_name: 'Fourth World', issue_number: '1', comicvine_volume_id: VOLUME_IDS.fourthWorld },
  { issue_id: ISSUE_IDS.F2, series_name: 'Fourth World', issue_number: '2', comicvine_volume_id: VOLUME_IDS.fourthWorld },
  { issue_id: ISSUE_IDS.J1, series_name: 'Justice League International', issue_number: '1', comicvine_volume_id: VOLUME_IDS.jli },
  { issue_id: ISSUE_IDS.M1, series_name: 'Mister Miracle', issue_number: '1', comicvine_volume_id: VOLUME_IDS.misterMiracle },
  { issue_id: ISSUE_IDS.J2, series_name: 'Justice League International', issue_number: '2', comicvine_volume_id: VOLUME_IDS.jli },
  { issue_id: ISSUE_IDS.M2, series_name: 'Mister Miracle', issue_number: '2', comicvine_volume_id: VOLUME_IDS.misterMiracle },
  { issue_id: ISSUE_IDS.J3, series_name: 'Justice League International', issue_number: '3', comicvine_volume_id: VOLUME_IDS.jli },
]

const BASELINE_SERIES: ReadingGraphSeriesNode[] = [
  {
    comicvine_volume_id: VOLUME_IDS.fourthWorld,
    series_name: 'Fourth World',
    year: 1971,
    state: 'continues',
    unread_count: 1,
    rollable_count: 1,
    waiting_count: 0,
    waits_for_issue_ids: [],
  },
  {
    comicvine_volume_id: VOLUME_IDS.misterMiracle,
    series_name: 'Mister Miracle',
    year: 1989,
    state: 'waits',
    unread_count: 2,
    rollable_count: 0,
    waiting_count: 2,
    waits_for_issue_ids: [ISSUE_IDS.F2],
  },
  {
    comicvine_volume_id: VOLUME_IDS.jli,
    series_name: 'Justice League International',
    year: 1987,
    state: 'waits',
    unread_count: 2,
    rollable_count: 0,
    waiting_count: 2,
    waits_for_issue_ids: [ISSUE_IDS.M1, ISSUE_IDS.M2],
  },
]

const CONTINUING_SERIES: ReadingGraphSeriesNode[] = [
  BASELINE_SERIES[0],
  {
    ...BASELINE_SERIES[1],
    waits_for_issue_ids: [ISSUE_IDS.F2, ISSUE_IDS.J2],
  },
  {
    ...BASELINE_SERIES[2],
    state: 'mixed',
    rollable_count: 1,
    waiting_count: 1,
    waits_for_issue_ids: [ISSUE_IDS.J2],
  },
]

/** The single Mister Miracle/JLI conflict used by the acceptance scenario. */
export const MISTER_MIRACLE_OVERLAP: ReadingGraphOverlap = {
  overlap_id: 'overlap-mister-miracle-jli',
  continuing_series: {
    comicvine_volume_id: VOLUME_IDS.jli,
    series_name: 'Justice League International',
    year: 1987,
  },
  waiting_series: {
    comicvine_volume_id: VOLUME_IDS.misterMiracle,
    series_name: 'Mister Miracle',
    year: 1989,
  },
  question:
    'Should Justice League International (1987) continue while Mister Miracle (1989) waits?',
  blocked_issue_ids: [ISSUE_IDS.J2],
  choices: [
    {
      choice: 'continue_series',
      label: 'Mister Miracle waits; JLI continues',
      detail:
        'Mister Miracle keeps its own order and still waits for Fourth World, while JLI keeps rolling.',
      rollable_issue_ids: [ISSUE_IDS.J2],
      waiting_issue_ids: [ISSUE_IDS.M1, ISSUE_IDS.M2, ISSUE_IDS.J3],
      series: CONTINUING_SERIES,
    },
    {
      choice: 'protect_order',
      label: 'Keep the full chosen order',
      detail:
        'JLI waits for every earlier Mister Miracle comic before it continues.',
      rollable_issue_ids: [],
      waiting_issue_ids: [ISSUE_IDS.J2, ISSUE_IDS.J3],
      series: BASELINE_SERIES,
    },
  ],
  selected_choice: null,
}

/** A same-named second Mister Miracle volume, which must stay separate. */
export const SECOND_MISTER_MIRACLE_OVERLAP: ReadingGraphOverlap = {
  ...MISTER_MIRACLE_OVERLAP,
  overlap_id: 'overlap-mister-miracle-2019-jli',
  waiting_series: {
    comicvine_volume_id: VOLUME_IDS.misterMiracleModern,
    series_name: 'Mister Miracle',
    year: 2019,
  },
  question:
    'Should Justice League International (1987) continue while Mister Miracle (2019) waits?',
}

/**
 * Build the prospective graph preview, before or after an answer.
 *
 * @param overrides - Partial preview fields, including a chosen answer.
 * @returns A complete server-shaped preview.
 */
export function readingGraphPreview(
  overrides: Partial<ReadingGraphPreview> = {},
): ReadingGraphPreview {
  const overlaps = overrides.overlaps ?? [MISTER_MIRACLE_OVERLAP]
  return {
    source_list_id: 7,
    content_hash: 'graph-hash-1',
    revision_sha: 'abcdef1234567890',
    series: BASELINE_SERIES,
    overlaps,
    issues: ISSUES,
    rollable_issue_ids: [ISSUE_IDS.F2],
    waiting_issue_ids: [ISSUE_IDS.M1, ISSUE_IDS.J2, ISSUE_IDS.M2, ISSUE_IDS.J3],
    cycle_errors: [],
    ...overrides,
  }
}

/**
 * The graph after the reader approves the series exception.
 *
 * @returns A complete preview whose JLI series can continue.
 */
export function afterContinuingChoice(): ReadingGraphPreview {
  return readingGraphPreview({
    series: CONTINUING_SERIES,
    overlaps: [
      {
        ...MISTER_MIRACLE_OVERLAP,
        selected_choice: 'continue_series',
      },
    ],
    rollable_issue_ids: [ISSUE_IDS.F2, ISSUE_IDS.J2],
    waiting_issue_ids: [ISSUE_IDS.M1, ISSUE_IDS.M2, ISSUE_IDS.J3],
  })
}

/**
 * Mark one overlap as already answered by the server.
 *
 * @param choice - Saved answer to restore.
 * @returns A preview that reports the saved decision.
 */
export function withSavedChoice(choice: ReadingGraphOverlapChoiceId): ReadingGraphPreview {
  return readingGraphPreview({
    overlaps: [{ ...MISTER_MIRACLE_OVERLAP, selected_choice: choice }],
  })
}

/**
 * A preview with no genuine overlap, where the questionnaire must not appear.
 *
 * @returns A single-series graph with no conflicts.
 */
export function withoutOverlap(): ReadingGraphPreview {
  return readingGraphPreview({
    overlaps: [],
    series: [BASELINE_SERIES[0]],
    rollable_issue_ids: [ISSUE_IDS.F2],
    waiting_issue_ids: [],
  })
}
