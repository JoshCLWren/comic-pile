import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcDir = resolve(__dirname, '..')

const SCAN_EXCLUDED_DIRS = new Set(['unit', 'test', 'devtools'])
const SCAN_EXCLUDED_FILES = new Set(['setup.ts'])

function collectProductionSources(dir: string): string[] {
  const entries = readdirSync(dir)
  const files: string[] = []
  for (const entry of entries) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (SCAN_EXCLUDED_DIRS.has(entry)) {
        continue
      }
      files.push(...collectProductionSources(full))
    } else if (/\.(ts|tsx)$/.test(entry) && !SCAN_EXCLUDED_FILES.has(entry)) {
      files.push(full)
    }
  }
  return files
}

function relative(path: string): string {
  return path.slice(srcDir.length + 1)
}

const sources = collectProductionSources(srcDir)

function filesMatching(pattern: RegExp): string[] {
  return sources
    .filter((file) => pattern.test(readFileSync(file, 'utf-8')))
    .map(relative)
    .sort()
}

/**
 * Scroll ownership guardrail (#2582). Route/resume restoration has exactly
 * one owner — the route restoration layer through
 * `scroll/scrollCoordinator.ts`. These assertions make a second
 * navigation-scroll owner fail loudly instead of shipping as another local
 * timer/observer fix.
 */
describe('scroll ownership guardrail (issue #2582)', () => {
  it('restricts window.scrollTo to the scroll coordinator', () => {
    expect(filesMatching(/window\.scrollTo|window\.scroll\(/)).toEqual([
      'scroll/scrollCoordinator.ts',
    ])
  })

  it('restricts scrollIntoView to gated feature semantic scrolling', () => {
    expect(filesMatching(/scrollIntoView\(/)).toEqual([
      'pages/HelpPage.tsx',
      'pages/RollPage/useRollViewport.ts',
    ])
  })

  it('routes every scrollIntoView call site through the semantic-scroll gate', () => {
    for (const file of ['pages/HelpPage.tsx', 'pages/RollPage/useRollViewport.ts']) {
      const source = readFileSync(resolve(srcDir, file), 'utf-8')
      expect(source).toMatch(/requestSemanticScroll/)
    }
  })

  it('restricts virtualizer scrollToIndex to the Queue virtualized list', () => {
    expect(filesMatching(/scrollToIndex\(/)).toEqual([
      'pages/QueuePage/VirtualizedThreadList.tsx',
    ])
  })

  it('keeps fixed-timeout correctness out of the restoration hook', () => {
    const source = readFileSync(resolve(srcDir, 'hooks/useScrollRestoration.ts'), 'utf-8')
    expect(source).not.toMatch(/setTimeout/)
    expect(source).not.toMatch(/setInterval/)
    expect(source).not.toMatch(/window\.scrollTo/)
    expect(source).toMatch(/scrollCoordinator/)
    expect(source).toMatch(/waitForLayoutSettled/)
  })

  it('keeps ResumeRecovery data-only: no viewport writes, no unscoped invalidation', () => {
    const source = readFileSync(resolve(srcDir, 'components/ResumeRecovery.tsx'), 'utf-8')
    expect(source).not.toMatch(/window\.scrollTo/)
    expect(source).not.toMatch(/scrollIntoView/)
    expect(source).not.toMatch(/scrollToIndex/)
    expect(source).not.toMatch(/invalidateQueries\(\s*\)/)
    expect(source).toMatch(/invalidateAfterResumeRecovery/)
  })

  it('documents Modal scroll-lock as the intentional element-level exception', () => {
    // Modal saves/restores the app-root scrollTop while a dialog locks
    // scrolling. That is dialog scroll-lock on an element, not window
    // navigation restoration, so it stays outside the coordinator — but it
    // must never grow into a window.scrollTo restore path.
    const source = readFileSync(resolve(srcDir, 'components/Modal.tsx'), 'utf-8')
    expect(source).not.toMatch(/window\.scrollTo/)
    expect(source).not.toMatch(/scrollIntoView\(/)
  })
})
