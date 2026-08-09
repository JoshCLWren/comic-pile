import { describe, expect, it } from 'vitest'

import { isPublicChangelogLink } from './WhatsNewPage'

describe('isPublicChangelogLink', () => {
  it('hides GitHub destinations from the public changelog', () => {
    expect(isPublicChangelogLink('https://github.com/JoshCLWren/comic-pile/pull/948')).toBe(false)
    expect(isPublicChangelogLink('https://www.github.com/JoshCLWren/comic-pile')).toBe(false)
    expect(isPublicChangelogLink('https://gist.github.com/JoshCLWren/example')).toBe(false)
  })

  it('keeps non-GitHub links available', () => {
    expect(isPublicChangelogLink('https://comic-pile.vercel.app/help')).toBe(true)
  })

  it('fails closed for malformed destinations', () => {
    expect(isPublicChangelogLink('not-a-url')).toBe(false)
  })
})
