import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')
const THIS_FILE = import.meta.filename

// Every production query key must be built through `queryKeys.*` in
// `frontend/src/query/queryKeys.ts`. The sessions index historically invented
// an inline `['sessions', params]` key (issue #2584) that escaped the `session`
// namespace, so cacheEffects / resume invalidation targeting
// `queryKeys.session.*` could not reliably refresh the list. The key is now the
// `queryKeys.session.list(...)` builder; any inline `['sessions'` key is a
// regression back to the split cache namespace.
const FORBIDDEN_PATTERNS = ["queryKey: ['sessions'", "queryKey: ['session','pages'"]

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

it('production query keys for the session index are built through queryKeys.session', () => {
  const files = collectSourceFiles(SOURCE_ROOT).filter((file) => !file.includes('/unit/'))
  const violations: string[] = []

  for (const file of files) {
    const content = readFileSync(file, 'utf-8')
    for (const pattern of FORBIDDEN_PATTERNS) {
      if (content.includes(pattern)) {
        violations.push(`${file}: found "${pattern}"`)
      }
    }
  }

  const hint =
    'Session index keys must be built through queryKeys.session.list(...) so ' +
    'invalidating queryKeys.session.pages() / all refreshes the Session index.'
  expect(violations, `${hint}\n${violations.join('\n')}`).toHaveLength(0)
})