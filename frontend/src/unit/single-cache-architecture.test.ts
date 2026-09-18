import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')
const THIS_FILE = import.meta.filename

// The React Query migration (#1719 / #1758 / #1759) made TanStack Query
// (queryClient + queryKeys + cacheEffects) the only server-state cache and the
// roll bootstrap the authoritative session source. The legacy Map-based
// CacheContext and the unused SessionContext mirror were removed (#2573) and
// must not be reintroduced in production source. Historical docs outside
// `frontend/src/` may still describe the older architecture.
const FORBIDDEN_IDENTIFIERS = [
  { pattern: 'CacheContext', label: 'legacy Map-based cache context' },
  { pattern: 'CacheProvider', label: 'legacy Map-based cache provider' },
  { pattern: 'useCache', label: 'legacy Map-based cache hook' },
  { pattern: 'SessionContext', label: 'unused session context mirror' },
  { pattern: 'SessionProvider', label: 'unused session provider mirror' },
]

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...collectSourceFiles(full))
    } else if (/\.(js|jsx|ts|tsx)$/.test(entry) && full !== THIS_FILE) {
      files.push(full)
    }
  }
  return files
}

it('legacy pre-Query cache/session contexts are not reintroduced under frontend/src', () => {
  const files = collectSourceFiles(SOURCE_ROOT)
  const violations: string[] = []

  for (const file of files) {
    const content = readFileSync(file, 'utf-8')
    for (const { pattern, label } of FORBIDDEN_IDENTIFIERS) {
      if (content.includes(pattern)) {
        violations.push(`${file}: found "${pattern}" (${label})`)
      }
    }
  }

  const hint =
    'TanStack Query is the only server-state layer. Route cache and session writes ' +
    'through frontend/src/query/cacheEffects.ts / queryKeys instead of reintroducing ' +
    'a second Map cache or session context.'
  expect(violations, `${hint}\n${violations.join('\n')}`).toHaveLength(0)
})