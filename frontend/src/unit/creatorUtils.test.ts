import { describe, expect, it } from 'vitest'
import { getCreatorDisplayText } from '../utils/creatorUtils'
import type { ManualCreatorCredit } from '../types'

describe('getCreatorDisplayText', () => {
  it('returns empty string for null/undefined/empty input', () => {
    expect(getCreatorDisplayText(null)).toBe('')
    expect(getCreatorDisplayText(undefined)).toBe('')
    expect(getCreatorDisplayText([])).toBe('')
  })

  it('returns name only when roles are empty', () => {
    const creators: ManualCreatorCredit[] = [{ name: 'Alan Moore', roles: [] }]
    expect(getCreatorDisplayText(creators)).toBe('Alan Moore')
  })

  it('formats name with roles', () => {
    const creators: ManualCreatorCredit[] = [
      { name: 'Alan Moore', roles: ['Writer'] },
      { name: 'Dave Gibbons', roles: ['Artist', 'Inker'] },
    ]
    expect(getCreatorDisplayText(creators)).toBe('Alan Moore (Writer) • Dave Gibbons (Artist, Inker)')
  })

  it('handles single creator with multiple roles', () => {
    const creators: ManualCreatorCredit[] = [{ name: 'Neil Gaiman', roles: ['Writer', 'Editor'] }]
    expect(getCreatorDisplayText(creators)).toBe('Neil Gaiman (Writer, Editor)')
  })

  it('handles mixed empty and non-empty roles', () => {
    const creators: ManualCreatorCredit[] = [
      { name: 'Creator A', roles: [] },
      { name: 'Creator B', roles: ['Penciller'] },
      { name: 'Creator C', roles: [] },
    ]
    expect(getCreatorDisplayText(creators)).toBe('Creator A • Creator B (Penciller) • Creator C')
  })

  it('joins roles with comma separator without trailing comma', () => {
    const creators: ManualCreatorCredit[] = [{ name: 'Multi', roles: ['A', 'B', 'C'] }]
    expect(getCreatorDisplayText(creators)).toBe('Multi (A, B, C)')
  })
})
