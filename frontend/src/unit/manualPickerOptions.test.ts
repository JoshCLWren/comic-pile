import { describe, expect, it } from 'vitest'
import type { components } from '../generated/openapi'
import {
  buildManualPickerOptions,
  type ManualPickerThread,
} from '../pages/RollPage/manualPickerOptions'

type ComicVineMappingHealth = components['schemas']['ComicVineMappingHealth']

/** A fully-quiet mapping row; tests override only the fields they exercise. */
function mapping(overrides: Partial<ComicVineMappingHealth>): ComicVineMappingHealth {
  return {
    confirmed_issue_count: 0,
    metadata_missing_count: 0,
    needs_mapping_count: 0,
    needs_review_count: 0,
    status: 'fully_mapped',
    tracked_issue_count: 0,
    ...overrides,
  }
}

function thread(overrides: Partial<ManualPickerThread> & { id: number }): ManualPickerThread {
  return { title: 'Saga', format: 'Single Issues', ...overrides }
}

const labelsOf = (options: Array<{ id: number; label: string }>) =>
  options.map((option) => option.label)

describe('buildManualPickerOptions (#3704)', () => {
  it('keeps the quiet label when the base label is already unique', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 1, title: 'Daredevil', next_unread_issue_number: '12', issues_remaining: 3 }),
      ],
      snoozedThreads: [],
    })

    expect(result.activeOptions).toEqual([
      { id: 1, label: 'Daredevil (Single Issues)' },
    ])
    expect(result.snoozedOptions).toEqual([])
  })

  it('disambiguates same-named threads with different progress instead of their ids', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 1, next_unread_issue_number: '12', issues_remaining: 3 }),
        thread({ id: 2, next_unread_issue_number: '40', issues_remaining: 1 }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · Up next: #12 · 3 issues remaining',
      'Saga (Single Issues) · Up next: #40 · 1 issue remaining',
    ])
  })

  it('shows a zero remaining count on colliding rows rather than hiding it', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 1, next_unread_issue_number: '12', issues_remaining: 0 }),
        thread({ id: 2, next_unread_issue_number: '12', issues_remaining: 5 }),
      ],
      snoozedThreads: [],
    })

    expect(result.activeOptions[0]?.label).toBe(
      'Saga (Single Issues) · Up next: #12 · 0 issues remaining',
    )
  })

  it('falls back to the thread id when colliding rows have no detail data at all', () => {
    const result = buildManualPickerOptions({
      activeThreads: [thread({ id: 3 }), thread({ id: 4 })],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · Series #3',
      'Saga (Single Issues) · Series #4',
    ])
  })

  it('falls back to the thread id when colliding rows carry identical details', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 7, next_unread_issue_number: '5', issues_remaining: 2 }),
        thread({ id: 8, next_unread_issue_number: '5', issues_remaining: 2 }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · Up next: #5 · 2 issues remaining · Series #7',
      'Saga (Single Issues) · Up next: #5 · 2 issues remaining · Series #8',
    ])
  })

  it('uses mapping-health detail to tell same-named rows apart', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({
          id: 11,
          comicvine_mapping: mapping({ status: 'needs_review', needs_review_count: 4 }),
        }),
        thread({
          id: 12,
          comicvine_mapping: mapping({
            status: 'partial',
            confirmed_issue_count: 2,
            tracked_issue_count: 10,
          }),
        }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · 4 issues need review',
      'Saga (Single Issues) · 2 of 10 mapped',
    ])
  })

  it('keeps fully mapped and non-applicable mapping health out of unique labels', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({
          id: 13,
          title: 'Quiet One',
          comicvine_mapping: mapping({ status: 'fully_mapped' }),
        }),
        thread({
          id: 14,
          title: 'Quiet Two',
          comicvine_mapping: mapping({ status: 'not_applicable' }),
        }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Quiet One (Single Issues)',
      'Quiet Two (Single Issues)',
    ])
  })

  it('appends the thread id when healthy mapping leaves colliding rows identical', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 17, comicvine_mapping: mapping({ status: 'fully_mapped' }) }),
        thread({ id: 18, comicvine_mapping: mapping({ status: 'not_applicable' }) }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · Series #17',
      'Saga (Single Issues) · Series #18',
    ])
  })

  it('adds metadata-missing detail for otherwise fully mapped colliding rows', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({
          id: 15,
          comicvine_mapping: mapping({ metadata_missing_count: 1 }),
        }),
        thread({
          id: 16,
          comicvine_mapping: mapping({ metadata_missing_count: 3 }),
        }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · 1 issue is missing details',
      'Saga (Single Issues) · 3 issues are missing details',
    ])
  })

  it('falls back to the bootstrap issue_number when no queue progress exists', () => {
    const result = buildManualPickerOptions({
      activeThreads: [thread({ id: 21, issue_number: '7' })],
      snoozedThreads: [thread({ id: 22, issue_number: '9' })],
    })

    expect(labelsOf(result.activeOptions)).toEqual(['Saga (Single Issues) · Up next: #7'])
    expect(labelsOf(result.snoozedOptions)).toEqual(['Saga (Single Issues) · Up next: #9'])
  })

  it('treats same-named rows with different tags as already distinct', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 31, tags: [{ name: 'Comixology' }] }),
        thread({ id: 32, tags: [{ name: 'Library' }, { name: 'Trade' }] }),
      ],
      snoozedThreads: [],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · Comixology',
      'Saga (Single Issues) · Library, Trade',
    ])
  })

  it('disambiguates a name collision that spans both option groups', () => {
    const result = buildManualPickerOptions({
      activeThreads: [thread({ id: 41, next_unread_issue_number: '12' })],
      snoozedThreads: [thread({ id: 42, next_unread_issue_number: '40' })],
    })

    expect(labelsOf(result.activeOptions)).toEqual([
      'Saga (Single Issues) · Up next: #12',
    ])
    expect(labelsOf(result.snoozedOptions)).toEqual([
      'Saga (Single Issues) · Up next: #40',
    ])
  })

  it('renders an id repeated inside one group exactly once', () => {
    const result = buildManualPickerOptions({
      activeThreads: [
        thread({ id: 51, next_unread_issue_number: '12' }),
        thread({ id: 51, next_unread_issue_number: '99' }),
      ],
      snoozedThreads: [],
    })

    // The duplicate is dropped before label counting, so the single remaining
    // row is unique again and keeps its quiet label.
    expect(result.activeOptions).toEqual([
      { id: 51, label: 'Saga (Single Issues)' },
    ])
    expect(result.snoozedOptions).toEqual([])
  })

  it('renders a thread id present in both groups once, in the active group', () => {
    const result = buildManualPickerOptions({
      activeThreads: [thread({ id: 61, title: 'Held Active' })],
      snoozedThreads: [thread({ id: 61, title: 'Held Active' })],
    })

    expect(result.activeOptions).toEqual([{ id: 61, label: 'Held Active (Single Issues)' }])
    expect(result.snoozedOptions).toEqual([])
  })

  it('returns an empty object shape when no threads are eligible', () => {
    const result = buildManualPickerOptions({ activeThreads: [], snoozedThreads: [] })

    expect(result).toEqual({ activeOptions: [], snoozedOptions: [] })
  })

  it('adds thread ID fallback for single options that have no disambiguating information', () => {
    const result = buildManualPickerOptions({
      activeThreads: [thread({ id: 101, title: 'Mister Miracle' })],
      snoozedThreads: [thread({ id: 102, title: 'Mister Miracle' })],
    })

    expect(labelsOf(result.activeOptions)).toEqual(['Mister Miracle (Single Issues) · Series #101'])
    expect(labelsOf(result.snoozedOptions)).toEqual(['Mister Miracle (Single Issues) · Series #102'])
  })

  it('does not add thread ID fallback for single options that have disambiguating information', () => {
    const result = buildManualPickerOptions({
      activeThreads: [thread({ id: 101, title: 'Mister Miracle', next_unread_issue_number: '5' })],
      snoozedThreads: [thread({ id: 102, title: 'Mister Miracle', next_unread_issue_number: '10' })],
    })

    expect(labelsOf(result.activeOptions)).toEqual(['Mister Miracle (Single Issues) · Up next: #5'])
    expect(labelsOf(result.snoozedOptions)).toEqual(['Mister Miracle (Single Issues) · Up next: #10'])
  })
})
