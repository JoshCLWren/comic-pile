import { describe, expect, it } from 'vitest'

import type { Release } from '../services/api-releases'
import { isDisplayableRelease } from '../pages/WhatsNewPage'

function release(overrides: Partial<Release> = {}): Release {
  return {
    id: 1,
    released_at: '2026-08-26T19:00:00Z',
    category: "What's New",
    title: 'Real reader-facing release title',
    summary: 'A real reader-facing release summary for What\'s New.',
    body: null,
    sort_order: 0,
    created_at: '2026-08-26T19:00:00Z',
    updated_at: '2026-08-26T19:00:00Z',
    ...overrides,
  }
}

describe('isDisplayableRelease', () => {
  it('shows a normal reader-facing release', () => {
    expect(isDisplayableRelease(release())).toBe(true)
  })

  it('hides a release whose title equals its summary', () => {
    const broken = release({
      title: 'persists normalized CBL reading-list sources, ordered entries',
      summary: 'persists normalized CBL reading-list sources, ordered entries',
    })
    expect(isDisplayableRelease(broken)).toBe(false)
  })

  it('hides a release with a dev-internal all-caps category', () => {
    const broken = release({
      title: 'Some reader-facing title',
      summary: 'A real reader-facing summary here.',
      category: 'CBL REFERENCE IMPORTS',
    })
    expect(isDisplayableRelease(broken)).toBe(false)
  })

  it('hides a release with a lowercase PR-fragment title', () => {
    const broken = release({
      title: 'makes issue and pull-request',
      summary: 'A real reader-facing summary here.',
    })
    expect(isDisplayableRelease(broken)).toBe(false)
  })

  it('hides the backfill announcement note', () => {
    const broken = release({
      title: 'adds an auditable historical What\'s New backfill that safely imports',
      summary: 'adds an auditable historical What\'s New backfill that safely imports',
    })
    expect(isDisplayableRelease(broken)).toBe(false)
  })

  it('keeps "What\'s New" category as reader-facing', () => {
    const good = release({ category: "What's New" })
    expect(isDisplayableRelease(good)).toBe(true)
  })
})
