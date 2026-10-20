import { describe, expect, it } from 'vitest'
import { evaluateReadingProgress } from '../utils/readingProgress'

describe('evaluateReadingProgress', () => {
  it('reports the read share of a tracked series', () => {
    expect(evaluateReadingProgress({ total_issues: 10, issues_remaining: 2 })).toEqual({
      status: 'known',
      percentage: 80,
      readCount: 8,
      totalIssues: 10,
    })
    expect(evaluateReadingProgress({ total_issues: 4, issues_remaining: 0 })).toMatchObject({
      status: 'known',
      percentage: 100,
      readCount: 4,
    })
    expect(evaluateReadingProgress({ total_issues: 4, issues_remaining: 4 })).toMatchObject({
      status: 'known',
      percentage: 0,
      readCount: 0,
    })
  })

  it('reports no progress for legacy counter threads', () => {
    expect(evaluateReadingProgress({ total_issues: null, issues_remaining: 3 }).status).toBe('untracked')
    expect(evaluateReadingProgress({ issues_remaining: 3 }).status).toBe('untracked')
    expect(evaluateReadingProgress(null).status).toBe('untracked')
    expect(evaluateReadingProgress(undefined).status).toBe('untracked')
  })

  it('rejects a remaining count below zero', () => {
    expect(evaluateReadingProgress({ total_issues: 10, issues_remaining: -4 }).status).toBe('inconsistent')
  })

  it('rejects a remaining count above the total', () => {
    // The reported #3595 thread: one total issue with 36 still to read.
    expect(evaluateReadingProgress({ total_issues: 1, issues_remaining: 36 }).status).toBe('inconsistent')
  })

  it('reports an empty series without claiming a percentage', () => {
    expect(evaluateReadingProgress({ total_issues: 0, issues_remaining: 0 }).status).toBe('empty')
    expect(evaluateReadingProgress({ total_issues: 0, issues_remaining: 3 }).status).toBe('inconsistent')
    expect(evaluateReadingProgress({ total_issues: 0, issues_remaining: -1 }).status).toBe('inconsistent')
  })

  it('rejects counters that are not finite numbers', () => {
    expect(evaluateReadingProgress({ total_issues: Number.NaN, issues_remaining: 1 }).status).toBe('inconsistent')
    expect(
      evaluateReadingProgress({ total_issues: 10, issues_remaining: Number.POSITIVE_INFINITY }).status,
    ).toBe('inconsistent')
  })

  it('never derives a percentage outside 0% and 100%', () => {
    const counters = [
      { total_issues: 10, issues_remaining: 0 },
      { total_issues: 10, issues_remaining: 10 },
      { total_issues: 10, issues_remaining: 11 },
      { total_issues: 10, issues_remaining: -1 },
    ]
    for (const counter of counters) {
      const progress = evaluateReadingProgress(counter)
      if (progress.status !== 'known') continue
      expect(progress.percentage).toBeGreaterThanOrEqual(0)
      expect(progress.percentage).toBeLessThanOrEqual(100)
    }
  })
})
