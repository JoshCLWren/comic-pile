import { describe, expect, it } from 'vitest'

import type { ReadingListPredecessorChange } from '../services/api-custom-cbl'
import {
  computeEntryRequirements,
  decodeCustomCBLError,
  describeCyclePath,
  describePredecessorChange,
} from '../utils/readingListAuthoring'

function axiosError(status: number, detail: unknown) {
  return { isAxiosError: true, response: { status, data: { detail } } }
}

describe('decodeCustomCBLError', () => {
  it('decodes the predecessor confirmation detail', () => {
    const detail = decodeCustomCBLError(
      axiosError(409, {
        code: 'reading_list_predecessor_confirmation_required',
        predecessor_changes: [
          {
            issue_id: 30001,
            issue_name: 'All-Star Comics #1',
            before_issue_ids: [],
            before_issue_names: [],
            after_issue_ids: [26360],
            after_issue_names: ['Starman #55'],
          },
        ],
      }),
    )

    expect(detail.code).toBe('reading_list_predecessor_confirmation_required')
    expect(detail.predecessorChanges).toEqual([
      {
        issue_id: 30001,
        issue_name: 'All-Star Comics #1',
        before_issue_ids: [],
        before_issue_names: [],
        after_issue_ids: [26360],
        after_issue_names: ['Starman #55'],
      },
    ])
    expect(detail.cyclePath).toEqual([])
  })

  it('decodes the structured cycle path', () => {
    const detail = decodeCustomCBLError(
      axiosError(422, {
        code: 'reading_list_cycle',
        message: 'Cycle detected',
        path: [
          {
            source_issue_id: 26360,
            source_issue_name: 'Starman #55',
            target_issue_id: 30001,
            target_issue_name: 'All-Star Comics #1',
            origin: 'list',
            prerequisite_origin: null,
            provenance: [],
          },
        ],
      }),
    )

    expect(detail.code).toBe('reading_list_cycle')
    expect(detail.message).toBe('Cycle detected')
    expect(detail.cyclePath).toEqual([
      {
        source_issue_id: 26360,
        source_issue_name: 'Starman #55',
        target_issue_id: 30001,
        target_issue_name: 'All-Star Comics #1',
        origin: 'list',
        prerequisite_origin: null,
        provenance: [],
      },
    ])
  })

  it('decodes legacy cycle edges without names and filters malformed endpoints', () => {
    const detail = decodeCustomCBLError(axiosError(422, {
      code: 'reading_list_cycle',
      path: [
        null,
        { source_issue_id: '1', target_issue_id: 2 },
        { source_issue_id: 1, target_issue_id: '2' },
        {
          source_issue_id: 1,
          target_issue_id: 2,
          source_issue_name: 42,
          target_issue_name: null,
          prerequisite_origin: 'reader',
          provenance: ['Reader prerequisite', 42],
        },
        {
          source_issue_id: 2,
          target_issue_id: 1,
          prerequisite_origin: 'converted',
        },
      ],
    }))
    expect(detail.cyclePath).toEqual([
      {
        source_issue_id: 1, target_issue_id: 2, origin: null,
        prerequisite_origin: 'reader', provenance: ['Reader prerequisite'],
      },
      {
        source_issue_id: 2, target_issue_id: 1, origin: null,
        prerequisite_origin: 'converted', provenance: [],
      },
    ])
    expect(describeCyclePath(detail.cyclePath, (id) => `Canonical #${id}`)).toContain(
      'Canonical #1 → Canonical #2 → Canonical #1',
    )
  })

  it('ignores malformed predecessor records and retains valid typed array members', () => {
    const detail = decodeCustomCBLError(axiosError(409, {
      predecessor_changes: [
        null,
        { issue_id: '1', issue_name: 'Invalid' },
        { issue_id: 1, issue_name: 42 },
        {
          issue_id: 2,
          issue_name: 'JSA #1',
          before_issue_ids: [1, 'invalid'],
          before_issue_names: ['Starman #55', null],
        },
      ],
    }))
    expect(detail.predecessorChanges).toEqual([{
      issue_id: 2, issue_name: 'JSA #1',
      before_issue_ids: [1], before_issue_names: ['Starman #55'],
      after_issue_ids: [], after_issue_names: [],
    }])
  })

  it.each([null, 42, [], undefined])('ignores unstructured detail %s', (detail) => {
    expect(decodeCustomCBLError(axiosError(422, detail))).toEqual({
      code: null, message: null, predecessorChanges: [], cyclePath: [],
    })
  })

  it('keeps a string detail as the message and ignores non-axios failures', () => {
    expect(decodeCustomCBLError(axiosError(404, 'Reading List not found')).message).toBe(
      'Reading List not found',
    )
    expect(decodeCustomCBLError(new Error('Nope')).code).toBeNull()
  })
})

describe('describePredecessorChange', () => {
  const base: ReadingListPredecessorChange = {
    issue_id: 30001,
    issue_name: 'All-Star Comics #1',
    before_issue_ids: [],
    before_issue_names: [],
    after_issue_ids: [],
    after_issue_names: [],
  }

  it('states a new wait', () => {
    expect(
      describePredecessorChange({
        ...base,
        after_issue_names: ['Starman #55'],
      }),
    ).toBe('All-Star Comics #1 now waits on Starman #55.')
  })

  it('states a removed wait', () => {
    expect(
      describePredecessorChange({
        ...base,
        before_issue_names: ['Starman #55'],
      }),
    ).toBe('All-Star Comics #1 no longer waits on anything (was waiting on Starman #55).')
  })

  it('states a retargeted wait', () => {
    expect(
      describePredecessorChange({
        ...base,
        before_issue_names: ['Starman #55'],
        after_issue_names: ['JSA #1', 'JSA #2'],
      }),
    ).toBe('All-Star Comics #1 was waiting on Starman #55, now waits on JSA #1 and JSA #2.')
  })
})

describe('describeCyclePath', () => {
  it('names the chain returned by the server', () => {
    const message = describeCyclePath(
      [
        { source_issue_id: 1, target_issue_id: 2, origin: null, prerequisite_origin: null, provenance: [] },
        { source_issue_id: 2, target_issue_id: 1, origin: null, prerequisite_origin: null, provenance: [] },
      ],
      (issueId) => (issueId === 1 ? 'Starman #55' : 'All-Star Comics #1'),
    )
    expect(message).toBe(
      'This order would create a reading cycle: Starman #55 → All-Star Comics #1 → Starman #55. Change the sequence and try again.',
    )
  })

  it('prefers server-provided names for issues outside the edited list', () => {
    const message = describeCyclePath(
      [
        {
          source_issue_id: 26360,
          source_issue_name: 'Starman #55',
          target_issue_id: 99001,
          target_issue_name: 'JSA #1',
          origin: 'list Other',
          prerequisite_origin: null,
          provenance: [],
        },
        {
          source_issue_id: 99001,
          source_issue_name: 'JSA #1',
          target_issue_id: 26360,
          target_issue_name: 'Starman #55',
          origin: 'list Other',
          prerequisite_origin: null,
          provenance: [],
        },
      ],
      () => 'Issue #99001',
    )
    expect(message).toBe(
      'This order would create a reading cycle: Starman #55 → JSA #1 → Starman #55. Change the sequence and try again.',
    )
    expect(message).not.toContain('Issue #99001')
  })

  it('falls back to generic guidance without a path', () => {
    expect(describeCyclePath([], () => 'x')).toContain('create a reading cycle')
  })
})

describe('computeEntryRequirements', () => {
  it('gates every later entry in strict mode', () => {
    const requirements = computeEntryRequirements('strict', [
      { issue_id: 1, gate: 'none', skipped: false },
      { issue_id: 2, gate: 'none', skipped: false },
      { issue_id: 3, gate: 'none', skipped: false },
    ])
    expect(requirements.get(1)).toEqual([])
    expect(requirements.get(2)).toEqual([1])
    expect(requirements.get(3)).toEqual([1, 2])
  })

  it('keeps loose entries independent unless gated', () => {
    const requirements = computeEntryRequirements('loose', [
      { issue_id: 1, gate: 'none', skipped: false },
      { issue_id: 2, gate: 'none', skipped: false },
      { issue_id: 3, gate: 'after_previous', skipped: false },
    ])
    expect(requirements.get(1)).toEqual([])
    expect(requirements.get(2)).toEqual([])
    expect(requirements.get(3)).toEqual([2])
  })

  it('gates later entries behind a hold milestone but not earlier ones', () => {
    const requirements = computeEntryRequirements('loose', [
      { issue_id: 1, gate: 'none', skipped: false },
      { issue_id: 2, gate: 'hold', skipped: false },
      { issue_id: 3, gate: 'none', skipped: false },
    ])
    expect(requirements.get(1)).toEqual([])
    expect(requirements.get(2)).toEqual([1])
    expect(requirements.get(3)).toEqual([1, 2])
  })

  it('never lets skipped entries contribute or receive requirements', () => {
    const requirements = computeEntryRequirements('strict', [
      { issue_id: 1, gate: 'none', skipped: true },
      { issue_id: 2, gate: 'none', skipped: false },
      { issue_id: 3, gate: 'after_previous', skipped: false },
    ])
    expect(requirements.has(1)).toBe(false)
    expect(requirements.get(2)).toEqual([])
    expect(requirements.get(3)).toEqual([2])
  })
})
