import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { queryKeys } from '../query/queryKeys'
import { expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')
const THIS_FILE = import.meta.filename

// The paginated Session index was retired with the v1 session surface
// (#4839, #4343): History is served by `activity`, and SessionPage reads the
// resource-shaped v2 detail/snapshot endpoints. Any surviving
// `queryKeys.session.pages/list/page` builder or inline `['session', 'pages']`
// key would resurrect a cache namespace no live query populates.
const RETIRED_KEY_PATTERNS = [
  'queryKeys.session.pages',
  'queryKeys.session.list',
  'queryKeys.session.page(',
  "queryKey: ['session','pages'",
  "queryKey: ['session', 'pages'",
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

it('does not expose retired paginated session index keys', () => {
  expect(queryKeys.session).not.toHaveProperty('pages')
  expect(queryKeys.session).not.toHaveProperty('list')
  expect(queryKeys.session).not.toHaveProperty('page')
  // The supported keys remain: current-session bootstrap state plus the
  // resource-shaped detail/snapshot reads.
  expect(queryKeys.session.current()).toEqual(['session', 'current'])
  expect(queryKeys.session.detail(9)).toEqual(['session', 'detail', 9])
  expect(queryKeys.session.snapshotsAll()).toEqual(['session', 'snapshots'])
})

it('has no shipped caller of a retired paginated session index key', () => {
  const files = collectSourceFiles(SOURCE_ROOT).filter((file) => !file.includes('/unit/'))
  const violations: string[] = []

  for (const file of files) {
    const content = readFileSync(file, 'utf-8')
    for (const pattern of RETIRED_KEY_PATTERNS) {
      if (content.includes(pattern)) {
        violations.push(`${file}: found "${pattern}"`)
      }
    }
  }

  expect(violations, violations.join('\n')).toHaveLength(0)
})

it('removes the retired session list key helpers from queryKeys', () => {
  const source = readFileSync(join(SOURCE_ROOT, 'query/queryKeys.ts'), 'utf-8')

  for (const helper of [
    'normalizedSessionParams',
    'SessionListParams',
    'SessionListKeyOptions',
    'SessionPageKeyOptions',
  ]) {
    expect(source, `${helper} must stay gone`).not.toContain(helper)
  }
})
