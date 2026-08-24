import { describe, expect, it } from 'vitest'
import { extractComicIdentity } from '../utils/comicIdentity'
import type { ComicVineRelatedIssue } from '../services/api'

function makeRelatedIssue(overrides: Partial<ComicVineRelatedIssue> = {}): ComicVineRelatedIssue {
  return {
    comicvine_issue_id: '36956',
    series_name: null,
    issue_number: null,
    name: null,
    cover_date: null,
    comicvine_url: null,
    comicpile_matches: [],
    ...overrides,
  }
}

describe('extractComicIdentity', () => {
  it('prefers series name plus issue number', () => {
    const identity = extractComicIdentity(
      makeRelatedIssue({ series_name: 'Stormwatch', issue_number: '1' }),
    )
    expect(identity.primary).toBe('Stormwatch #1')
  })

  it('falls back to the series name alone', () => {
    const identity = extractComicIdentity(makeRelatedIssue({ series_name: 'Stormwatch' }))
    expect(identity.primary).toBe('Stormwatch')
  })

  it('falls back to a bare issue number', () => {
    const identity = extractComicIdentity(makeRelatedIssue({ issue_number: '12' }))
    expect(identity.primary).toBe('#12')
  })

  it('falls back to the issue title when no series or number exists', () => {
    const identity = extractComicIdentity(makeRelatedIssue({ name: 'The Dark Side' }))
    expect(identity.primary).toBe('The Dark Side')
  })

  it('never exposes the numeric provider ID when no human identity exists', () => {
    const identity = extractComicIdentity(makeRelatedIssue())
    expect(identity.primary).toBe('Untitled ComicVine issue')
    expect(identity.secondary).toBeNull()
    expect(identity.primary).not.toMatch(/\d/)
  })

  it('keeps whitespace-only metadata out of the identity', () => {
    const identity = extractComicIdentity(
      makeRelatedIssue({ series_name: '   ', issue_number: '  ', name: '\t' }),
    )
    expect(identity.primary).toBe('Untitled ComicVine issue')
  })
})
