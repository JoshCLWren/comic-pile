import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function loadQueuePageSource(): string {
  const candidates = [
    resolve(process.cwd(), 'src/pages/QueuePage/QueuePage.tsx'),
    resolve(process.cwd(), 'frontend/src/pages/QueuePage/QueuePage.tsx'),
  ]
  for (const path of candidates) {
    try {
      return readFileSync(path, 'utf8')
    } catch {
      // try next candidate
    }
  }
  // Fallback when running from repo root with different cwd
  return readFileSync(resolve('frontend/src/pages/QueuePage/QueuePage.tsx'), 'utf8')
}

describe('Queue FAB regression (#2220)', () => {
  it('uses semantic primary-action tokens, not raw amber utilities', () => {
    const source = loadQueuePageSource()
    // Extract only the FAB button block, not everything after it.
    // The retry button below still uses amber for its own scope.
    const fabStart = source.indexOf('md:hidden fixed')
    const fabEnd = source.indexOf('</button>', fabStart)
    const fabBlock = source.slice(fabStart, fabEnd)
    expect(fabBlock, 'FAB block missing').toContain('bg-[var(--theme-primary-action)]')
    expect(fabBlock).toContain('hover:bg-[var(--theme-primary-action-hover)]')
    expect(fabBlock).toContain('var(--theme-primary-action)')
    expect(fabBlock).toContain('var(--theme-focus-ring)')
    // Raw amber must not remain in FAB chrome
    expect(fabBlock).not.toContain('bg-amber-600')
    expect(fabBlock).not.toContain('bg-amber-500')
    expect(fabBlock).not.toContain('rgba(212,137,14')
  })

  it('positions FAB with safe-area-aware chrome and provides bottom clearance for the last row', () => {
    const source = loadQueuePageSource()
    // Outer container must carry extra bottom padding so last row is tappable with FAB present
    expect(source).toContain('pb-[calc(10rem+env(safe-area-inset-bottom))]')
    // FAB must be safe-area aware (bottom calc with env)
    expect(source).toContain('bottom-[calc(6rem+env(safe-area-inset-bottom))]')
  })
})
