import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

// Vitest runs from frontend/, so production sources are rooted under src/.
const SRC_ROOT = join(process.cwd(), 'src')
const BASELINE_PATH = join(SRC_ROOT, 'pagination/bespokePagers.baseline.json')

interface PaginationBaseline {
  manualTokenLoops: Record<string, string>
  handRolledPagers: Record<string, string>
  nextCursorFiles: Record<string, string>
  migratedSurfaces: Record<string, string>
  documentedExceptions: Record<string, string>
}

function readBaseline(): PaginationBaseline {
  return JSON.parse(readFileSync(BASELINE_PATH, 'utf8')) as PaginationBaseline
}

function productionSources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      // Generated contracts and test files are not product pagination surfaces.
      if (['generated', 'unit', 'test'].includes(entry.name)) return []
      return productionSources(fullPath)
    }
    return /\.(ts|tsx)$/.test(entry.name) ? [fullPath] : []
  })
}

// Mechanics that belong only to the shared pagination layer. A surface that
// owns any of them has reintroduced a bespoke page-token state machine (#2570).
const BESPOKE_TOKEN_MECHANICS = [
  /\bseenPageTokens\b/,
  /\bseenTokens\b/,
  /\bsetNextPageToken\b/,
  /\bwhile\s*\(\s*(?:token|pageToken|nextPageToken)\b/,
  /\b(?:nextPageToken|pageToken|token)\s*=\s*(?:data|page|result)\.next_page_token/,
]

const CANONICAL_COLLECTOR_CONSUMERS = [
  'components/IssueCorrectionDialog.tsx',
  'hooks/useContinuityPlannerData.ts',
  'hooks/useCrossovers.ts',
  'hooks/useDependencies.ts',
  'hooks/useThreadIssueCreators.ts',
  'hooks/useThreadIssues.ts',
  'pages/HistoryPage.tsx',
  'pages/QueuePage/IssueToggleList.tsx',
  'pages/QueuePage/useQueueCompletedSearch.ts',
  'pages/RollPage/useRollModals.ts',
]

describe('pagination migration conformance (#2570)', () => {
  it('keeps direct token-draining mechanics out of every production surface', () => {
    const offenders = productionSources(SRC_ROOT)
      .filter((path) => !relative(SRC_ROOT, path).startsWith('pagination'))
      .filter((path) => {
        const source = readFileSync(path, 'utf8')
        return BESPOKE_TOKEN_MECHANICS.some((pattern) => pattern.test(source))
      })
      .map((path) => relative(SRC_ROOT, path))

    expect(offenders).toEqual([])
  })

  it('routes every former bespoke surface through the shared collector', () => {
    for (const surface of CANONICAL_COLLECTOR_CONSUMERS) {
      const source = readFileSync(join(SRC_ROOT, surface), 'utf8')
      expect(source, surface).toMatch(/collectAllPages/)
    }
  })

  it('records every remaining non-opaque cursor contract as an explicit exception', () => {
    const baseline = readBaseline()
    expect(baseline.manualTokenLoops).toEqual({})
    expect(baseline.handRolledPagers).toEqual({})
    expect(baseline.nextCursorFiles).toEqual({})
    expect(Object.keys(baseline.documentedExceptions).length).toBeGreaterThan(0)

    for (const exception of Object.keys(baseline.documentedExceptions)) {
      expect(() => readFileSync(join(SRC_ROOT, exception), 'utf8'), exception).not.toThrow()
    }
  })

  it('keeps the documented exception files free of bespoke token state machines', () => {
    const baseline = readBaseline()
    for (const exception of Object.keys(baseline.documentedExceptions)) {
      const source = readFileSync(join(SRC_ROOT, exception), 'utf8')
      expect(BESPOKE_TOKEN_MECHANICS.some((pattern) => pattern.test(source)), exception).toBe(false)
    }
  })
})
