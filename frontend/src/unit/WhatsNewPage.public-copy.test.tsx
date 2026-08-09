import { describe, expect, it } from 'vitest'
import { publicChangelogText } from '../pages/WhatsNewPage'

describe('publicChangelogText', () => {
  it('removes linked pull request numbers from release-note entries', () => {
    expect(publicChangelogText('[#994](https://github.com/JoshCLWren/comic-pile/pull/994) replaces internal fields with comic issue labels.')).toBe('replaces internal fields with comic issue labels.')
  })

  it('removes plain PR references while preserving the user-facing change', () => {
    expect(publicChangelogText('PR #990: Rating retries after login recovery.')).toBe('Rating retries after login recovery.')
  })

  it('leaves ordinary comic issue numbers alone', () => {
    expect(publicChangelogText('Fantastic Four #583 stays selected after login recovery.')).toBe('Fantastic Four #583 stays selected after login recovery.')
  })
})
