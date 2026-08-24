import { describe, expect, it } from 'vitest'
import {
  normalizeArcName,
  extractComicIdentity,
  getMemberState,
  getStateLabel,
  getStateColorClass,
} from '../utils/comicIdentity'
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

describe('normalizeArcName', () => {
  it('strips (Storyline) suffix', () => {
    expect(normalizeArcName('Knightfall (Storyline)')).toBe('Knightfall')
  })

  it('strips (Collection) suffix case-insensitively', () => {
    expect(normalizeArcName('Civil War (collection)')).toBe('Civil War')
  })

  it('strips (Trade Paperback) suffix', () => {
    expect(normalizeArcName('Infinity Gauntlet (Trade Paperback)')).toBe('Infinity Gauntlet')
  })

  it('strips (Hardcover) suffix', () => {
    expect(normalizeArcName('Secret Wars (Hardcover)')).toBe('Secret Wars')
  })

  it('strips (Omnibus) suffix', () => {
    expect(normalizeArcName('Crisis on Infinite Earths (Omnibus)')).toBe('Crisis on Infinite Earths')
  })

  it('collapses multiple spaces', () => {
    expect(normalizeArcName('The   Big   Arc')).toBe('The Big Arc')
  })

  it('trims leading and trailing whitespace', () => {
    expect(normalizeArcName('  Knightfall  ')).toBe('Knightfall')
  })

  it('returns plain names unchanged', () => {
    expect(normalizeArcName('Avengers Disassembled')).toBe('Avengers Disassembled')
  })

  it('handles empty string', () => {
    expect(normalizeArcName('')).toBe('')
  })
})

describe('extractComicIdentity', () => {
  it('builds primary from series name and issue number', () => {
    const issue: ComicVineRelatedIssue = {
      comicvine_issue_id: '1',
      series_name: 'Batman',
      issue_number: '125',
      name: 'The Dark Knight',
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [],
    }
    const identity = extractComicIdentity(issue)
    expect(identity.primary).toBe('Batman #125')
    expect(identity.secondary).toBe('The Dark Knight')
  })

  it('falls back to name when series and number are missing', () => {
    const issue: ComicVineRelatedIssue = {
      comicvine_issue_id: '2',
      series_name: null,
      issue_number: null,
      name: 'Special Edition',
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [],
    }
    const identity = extractComicIdentity(issue)
    expect(identity.primary).toBe('Special Edition')
    expect(identity.secondary).toBeNull()
  })

  it('uses comicvine issue ID as final fallback', () => {
    const issue: ComicVineRelatedIssue = {
      comicvine_issue_id: '999',
      series_name: null,
      issue_number: null,
      name: null,
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [],
    }
    const identity = extractComicIdentity(issue)
    expect(identity.primary).toBe('ComicVine issue 999')
    expect(identity.secondary).toBeNull()
  })

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

describe('getMemberState', () => {
  it('returns missing when no matches', () => {
    const issue: ComicVineRelatedIssue = {
      comicvine_issue_id: '1',
      series_name: null,
      issue_number: null,
      name: null,
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [],
    }
    expect(getMemberState(issue)).toBe('missing')
  })

  it('returns unread when match has unread status', () => {
    const issue: ComicVineRelatedIssue = {
      comicvine_issue_id: '2',
      series_name: null,
      issue_number: null,
      name: null,
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [{ issue_id: 1, thread_id: 1, thread_title: 'T', issue_number: '1', status: 'unread' }],
    }
    expect(getMemberState(issue)).toBe('unread')
  })

  it('returns read when all matches are read', () => {
    const issue: ComicVineRelatedIssue = {
      comicvine_issue_id: '3',
      series_name: null,
      issue_number: null,
      name: null,
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [{ issue_id: 1, thread_id: 1, thread_title: 'T', issue_number: '1', status: 'read' }],
    }
    expect(getMemberState(issue)).toBe('read')
  })
})

describe('getStateLabel', () => {
  it('returns correct labels', () => {
    expect(getStateLabel('read')).toBe('Read')
    expect(getStateLabel('unread')).toBe('Unread')
    expect(getStateLabel('missing')).toBe('Not in ComicPile')
  })
})

describe('getStateColorClass', () => {
  it('returns correct color classes', () => {
    expect(getStateColorClass('read')).toBe('text-emerald-400')
    expect(getStateColorClass('unread')).toBe('text-amber-400')
    expect(getStateColorClass('missing')).toBe('text-rose-400')
  })
})
