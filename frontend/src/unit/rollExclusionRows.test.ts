import { describe, expect, it } from 'vitest'
import {
  mergeBlockingDependencies,
  toBlockedPoolRow,
} from '../pages/RollPage/rollExclusionRows'
import type { BlockingDependency } from '../types'
import type { ThreadExclusionReason } from '../types/rollBootstrap'

function dependency(overrides: Partial<BlockingDependency> = {}): BlockingDependency {
  return {
    thread_id: 9,
    thread_title: 'Saga',
    issue_number: '1',
    label: 'Read Saga #1 first',
    ...overrides,
  }
}

describe('Roll exclusion row mapping', () => {
  it('maps a blocked row with a Thread id onto the pool row shape', () => {
    const row = toBlockedPoolRow({
      thread_id: 42,
      title: 'Monstress',
      format: 'Comic',
      reason: 'blocked',
      blocking_reasons: ['Read Saga #1 first'],
      last_activity_at: '2026-10-01T00:00:00Z',
    })

    expect(row).toEqual({
      id: 42,
      title: 'Monstress',
      format: 'Comic',
      blocking_reasons: ['Read Saga #1 first'],
      last_activity_at: '2026-10-01T00:00:00Z',
    })
  })

  it('uses the non-actionable sentinel for a blocked row without a Thread id', () => {
    const row = toBlockedPoolRow({ title: 'Orphaned Series', format: 'Comic', reason: 'blocked' })

    expect(row.id).toBe(0)
    expect(row.blocking_reasons).toEqual([])
    expect(row.last_activity_at).toBeNull()
  })

  it('merges dependency details only for rows with a resolvable Thread id', () => {
    const existing = { 1: [dependency({ thread_id: 5, thread_title: 'Existing' })] }
    const merged = mergeBlockingDependencies(existing, [
      { thread_id: 9, title: 'Monstress', format: 'Comic', reason: 'blocked', blocking_dependencies: [dependency()] },
      { title: 'Orphaned Series', format: 'Comic', reason: 'blocked', blocking_dependencies: [dependency({ thread_id: 7 })] },
      { thread_id: 10, title: 'No Details', format: 'Comic', reason: 'blocked' },
    ])

    expect(merged[1]).toEqual(existing[1])
    expect(merged[9]).toEqual([dependency()])
    expect(merged[7]).toBeUndefined()
    expect(merged[10]).toBeUndefined()
    expect(Object.keys(merged)).toEqual(['1', '9'])
  })
})
