import { describe, expect, it } from 'vitest'
import { buildCreatorKey, creatorKeyFor, creatorRoutePath, parseCreatorKey } from '../utils/creatorKey'

describe('creatorKey', () => {
  it('builds canonical creator keys from stable provider ids', () => {
    expect(buildCreatorKey(12345)).toBe('creator:12345')
  })

  it('parses canonical keys back to the external person id', () => {
    expect(parseCreatorKey('creator:12345')).toBe(12345)
  })

  it('rejects non-canonical shapes instead of guessing identity', () => {
    expect(parseCreatorKey(null)).toBeNull()
    expect(parseCreatorKey(undefined)).toBeNull()
    expect(parseCreatorKey('')).toBeNull()
    expect(parseCreatorKey('Stan Lee')).toBeNull()
    expect(parseCreatorKey('creator:')).toBeNull()
    expect(parseCreatorKey('creator:abc')).toBeNull()
    expect(parseCreatorKey('writer:12345')).toBeNull()
    expect(parseCreatorKey('creator:12:34')).toBeNull()
  })

  it('resolves keys only for rows with a stable provider id', () => {
    expect(creatorKeyFor({ creator_id: 7 })).toBe('creator:7')
    expect(creatorKeyFor({ creator_id: null })).toBeNull()
    expect(creatorKeyFor({ creator_id: undefined })).toBeNull()
    expect(creatorKeyFor({})).toBeNull()
    expect(creatorKeyFor(null)).toBeNull()
    expect(creatorKeyFor(undefined)).toBeNull()
  })

  it('builds a navigable route path for a canonical key', () => {
    expect(creatorRoutePath('creator:12345')).toBe('/creators/creator%3A12345')
  })
})
