import { describe, expect, it } from 'vitest'

import {
  buildReadingGraphRequest,
  describeOverlapEffect,
  effectiveOverlapChoice,
  hasGenuineOverlap,
  overlapChoicePayload,
  overlapDecisionLabel,
  readingGraphIssueLabel,
  readingGraphSeriesLabel,
  readingGraphSeriesStatus,
  readingGraphSummaryLine,
  readingGraphWaitLabels,
  unresolvedOverlaps,
  withLocalChoices,
} from '../utils/readingGraphOverlaps'
import {
  ISSUE_IDS,
  MISTER_MIRACLE_OVERLAP,
  SECOND_MISTER_MIRACLE_OVERLAP,
  VOLUME_IDS,
  readingGraphPreview,
  withSavedChoice,
  withoutOverlap,
} from './readingGraphFixture'

describe('readingGraphOverlaps', () => {
  it('labels volumes by exact identity including the year', () => {
    expect(readingGraphSeriesLabel(MISTER_MIRACLE_OVERLAP.waiting_series)).toBe(
      'Mister Miracle (1989)',
    )
    expect(
      readingGraphSeriesLabel({ comicvine_volume_id: 'v', series_name: 'Saga', year: null }),
    ).toBe('Saga')
  })

  it('keeps two same-named volumes as distinct decisions', () => {
    const preview = readingGraphPreview({
      overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
    })
    expect(preview.overlaps).toHaveLength(2)
    expect(readingGraphSeriesLabel(preview.overlaps[0].waiting_series)).toBe(
      'Mister Miracle (1989)',
    )
    expect(readingGraphSeriesLabel(preview.overlaps[1].waiting_series)).toBe(
      'Mister Miracle (2019)',
    )
    expect(unresolvedOverlaps(preview, {})).toHaveLength(2)
    expect(
      unresolvedOverlaps(preview, { [MISTER_MIRACLE_OVERLAP.overlap_id]: 'continue_series' }),
    ).toEqual([SECOND_MISTER_MIRACLE_OVERLAP])
  })

  it('reports no genuine overlap for a single-series graph', () => {
    expect(hasGenuineOverlap(null)).toBe(false)
    expect(hasGenuineOverlap(withoutOverlap())).toBe(false)
    expect(hasGenuineOverlap(readingGraphPreview())).toBe(true)
  })

  it('prefers a local answer over a saved one and falls back to the saved answer', () => {
    const saved = withSavedChoice('protect_order')
    const overlap = saved.overlaps[0]
    expect(effectiveOverlapChoice(overlap, {})).toBe('protect_order')
    expect(effectiveOverlapChoice(overlap, { [overlap.overlap_id]: 'continue_series' })).toBe(
      'continue_series',
    )
    expect(unresolvedOverlaps(saved, {})).toEqual([])
    expect(unresolvedOverlaps(readingGraphPreview(), {})).toHaveLength(1)
  })

  it('explains the prospective effects of each answer with real comic labels', () => {
    const preview = readingGraphPreview()
    const continuing = preview.overlaps[0].choices.find(
      (effect) => effect.choice === 'continue_series',
    )
    const protect = preview.overlaps[0].choices.find((effect) => effect.choice === 'protect_order')
    expect(continuing).toBeDefined()
    expect(protect).toBeDefined()

    expect(describeOverlapEffect(preview, continuing!)).toEqual({
      rollable: ['Justice League International #2'],
      waiting: ['Mister Miracle #1', 'Mister Miracle #2', 'Justice League International #3'],
      changesAnything: true,
    })
    expect(describeOverlapEffect(preview, protect!).rollable).toEqual([])
    expect(describeOverlapEffect(preview, protect!).waiting).toEqual([
      'Justice League International #2',
      'Justice League International #3',
    ])
  })

  it('falls back to a stable label for an issue the preview does not list', () => {
    expect(readingGraphIssueLabel(readingGraphPreview(), 999)).toBe('Issue 999')
  })

  it('summarizes the graph and each series status', () => {
    const preview = readingGraphPreview()
    expect(readingGraphSummaryLine(preview)).toBe('3 series · 1 rollable · 4 waiting')
    expect(preview.series.map(readingGraphSeriesStatus)).toEqual([
      'Can continue',
      'Waits',
      'Waits',
    ])
  })

  it('names what a waiting series holds for', () => {
    const preview = readingGraphPreview()
    expect(readingGraphWaitLabels(preview, preview.series[1])).toEqual(['Fourth World #2'])
    expect(readingGraphWaitLabels(preview, preview.series[0])).toEqual([])
  })

  it('builds an ordered answer payload containing only answered conflicts', () => {
    const preview = readingGraphPreview({
      overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
    })
    const choices = { [SECOND_MISTER_MIRACLE_OVERLAP.overlap_id]: 'protect_order' as const }
    expect(overlapChoicePayload(preview, choices)).toEqual([
      { overlap_id: SECOND_MISTER_MIRACLE_OVERLAP.overlap_id, choice: 'protect_order' },
    ])
    expect(overlapChoicePayload(null, choices)).toEqual([])
  })

  it('builds the read-only preview request from positions and answers', () => {
    const preview = readingGraphPreview()
    expect(
      buildReadingGraphRequest([3, 1, 2], preview, {
        [preview.overlaps[0].overlap_id]: 'continue_series',
      }),
    ).toEqual({
      included_positions: [1, 2, 3],
      overlap_choices: [
        { overlap_id: preview.overlaps[0].overlap_id, choice: 'continue_series' },
      ],
    })
  })

  it('applies local answers without inventing graph state', () => {
    const preview = readingGraphPreview()
    const annotated = withLocalChoices(preview, {
      [preview.overlaps[0].overlap_id]: 'continue_series',
    })
    expect(annotated.overlaps[0].selected_choice).toBe('continue_series')
    // The blockers and rollable comics still come from the server preview.
    expect(annotated.rollable_issue_ids).toEqual(preview.rollable_issue_ids)
    expect(annotated.waiting_issue_ids).toEqual(preview.waiting_issue_ids)
    expect(withLocalChoices(preview, {})).toBe(preview)
  })

  it('describes the chosen decision in reader language', () => {
    expect(
      overlapDecisionLabel(MISTER_MIRACLE_OVERLAP, {
        [MISTER_MIRACLE_OVERLAP.overlap_id]: 'continue_series',
      }),
    ).toBe('Mister Miracle waits; JLI continues')
    expect(overlapDecisionLabel(MISTER_MIRACLE_OVERLAP, {})).toBeNull()
  })

  it('keeps the exact volume identities from the server payload', () => {
    const preview = readingGraphPreview()
    expect(preview.overlaps[0].continuing_series.comicvine_volume_id).toBe(VOLUME_IDS.jli)
    expect(preview.overlaps[0].waiting_series.comicvine_volume_id).toBe(
      VOLUME_IDS.misterMiracle,
    )
    expect(preview.overlaps[0].blocked_issue_ids).toEqual([ISSUE_IDS.J2])
  })
})
