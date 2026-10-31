import { describe, expect, it } from 'vitest'
import {
  isRollMapSeriesCandidate,
  type ComicVineMappingHealth,
} from '../hooks/useRollSeriesMapping'

/**
 * Build a fully shaped mapping-health projection so the gate tests never need
 * a partial-object type assertion. Only `status` drives the gate, but every
 * schema field is present to match what the API actually returns.
 */
function health(status: ComicVineMappingHealth['status']): ComicVineMappingHealth {
  return {
    status,
    tracked_issue_count: 2,
    confirmed_issue_count: 0,
    needs_mapping_count: 2,
    needs_review_count: 0,
    metadata_missing_count: 0,
  }
}

describe('useRollSeriesMapping gate', () => {
  it('allows unresolved, needs_review, and partial health', () => {
    expect(isRollMapSeriesCandidate(health('unresolved'))).toBe(true)
    expect(isRollMapSeriesCandidate(health('needs_review'))).toBe(true)
    expect(isRollMapSeriesCandidate(health('partial'))).toBe(true)
  })

  it('excludes fully_mapped and not_applicable', () => {
    expect(isRollMapSeriesCandidate(health('fully_mapped'))).toBe(false)
    expect(isRollMapSeriesCandidate(health('not_applicable'))).toBe(false)
  })

  it('fails closed on missing health', () => {
    expect(isRollMapSeriesCandidate(null)).toBe(false)
    expect(isRollMapSeriesCandidate(undefined)).toBe(false)
  })
})
