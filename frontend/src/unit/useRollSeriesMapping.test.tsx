import { describe, expect, it } from 'vitest'
import { isRollMapSeriesCandidate } from '../hooks/useRollSeriesMapping'

describe('useRollSeriesMapping gate', () => {
  it('allows unresolved, needs_review, and partial health', () => {
    expect(isRollMapSeriesCandidate({ status: 'unresolved' } as never)).toBe(true)
    expect(isRollMapSeriesCandidate({ status: 'needs_review' } as never)).toBe(true)
    expect(isRollMapSeriesCandidate({ status: 'partial' } as never)).toBe(true)
  })

  it('excludes fully_mapped and not_applicable', () => {
    expect(isRollMapSeriesCandidate({ status: 'fully_mapped' } as never)).toBe(false)
    expect(isRollMapSeriesCandidate({ status: 'not_applicable' } as never)).toBe(false)
  })

  it('fails closed on missing health', () => {
    expect(isRollMapSeriesCandidate(null)).toBe(false)
    expect(isRollMapSeriesCandidate(undefined)).toBe(false)
  })
})