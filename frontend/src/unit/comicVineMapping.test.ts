import { describe, expect, it } from 'vitest'
import {
  getMappingHealthDescription,
  getMappingHealthLabel,
  needsMappingAttention,
} from '../utils/comicVineMapping'
import type { ComicVineMappingHealth } from '../types/comic-vine'

const base: ComicVineMappingHealth = {
  status: 'partial',
  tracked_issue_count: 4,
  confirmed_issue_count: 2,
  needs_mapping_count: 2,
  needs_review_count: 0,
}

describe('comicVineMapping helpers', () => {
  it('getMappingHealthLabel states the count for every status', () => {
    expect(getMappingHealthLabel({ ...base, status: 'not_applicable' })).toBe('Not applicable')
    expect(getMappingHealthLabel({ ...base, status: 'fully_mapped' })).toBe('Fully mapped')
    expect(getMappingHealthLabel({ ...base, status: 'partial' })).toBe('2 of 4 mapped')
    expect(getMappingHealthLabel({ ...base, status: 'unresolved' })).toBe('2 need mapping')
    expect(getMappingHealthLabel({ ...base, status: 'needs_review', needs_review_count: 3 })).toBe('3 need review')
  })

  it('getMappingHealthDescription separates review work from missing mapping', () => {
    expect(getMappingHealthDescription({ ...base, status: 'not_applicable' })).toBe(
      'This series does not track ComicVine issue identity.',
    )
    expect(getMappingHealthDescription({ ...base, status: 'fully_mapped' })).toBe(
      'All 4 issues are confirmed against ComicVine.',
    )
    expect(getMappingHealthDescription({ ...base, status: 'partial' })).toBe(
      '2 of 4 issues are confirmed; 2 still need mapping.',
    )
    expect(getMappingHealthDescription({ ...base, status: 'unresolved' })).toBe(
      '2 of 4 issues have no confirmed ComicVine identity.',
    )
    expect(getMappingHealthDescription({ ...base, status: 'needs_review', needs_review_count: 3 })).toBe(
      '3 issues are ambiguous or conflicting and need review before they can be mapped.',
    )
  })

  it('needsMappingAttention flags only repairable states', () => {
    expect(needsMappingAttention(null)).toBe(false)
    expect(needsMappingAttention(undefined)).toBe(false)
    expect(needsMappingAttention({ ...base, status: 'partial' })).toBe(true)
    expect(needsMappingAttention({ ...base, status: 'unresolved' })).toBe(true)
    expect(needsMappingAttention({ ...base, status: 'needs_review' })).toBe(true)
    expect(needsMappingAttention({ ...base, status: 'fully_mapped' })).toBe(false)
    expect(needsMappingAttention({ ...base, status: 'not_applicable' })).toBe(false)
  })
})