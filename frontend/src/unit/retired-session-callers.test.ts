import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

// Only shipped source is scanned. Unit tests and E2E specs intentionally name
// retired paths to assert their absence; generated artifacts are validated by
// generated-v1-only-paths.test.ts.
const LIVE_SOURCE_DIRS = [
  'services',
  'hooks',
  'pages',
  'components',
  'query',
  'contexts',
  'routes',
  'types',
]
const LIVE_SOURCE_FILES = ['App.tsx']

const RETIRED_CALLS: ReadonlyArray<{ label: string; pattern: RegExp }> = [
  { label: 'retired session list/single reads', pattern: /\/v1\/sessions|\/api\/v1\/sessions|\/api\/sessions/ },
  { label: 'retired current-session read', pattern: /sessions\/current/ },
  { label: 'retired restore-session-start action', pattern: /restore-session-start/ },
  { label: 'retired v1/unversioned undo reads', pattern: /\/v1\/undo|\/api\/undo/ },
]

function liveSourceFiles(): string[] {
  const files: string[] = []
  for (const dir of LIVE_SOURCE_DIRS) {
    const absolute = resolve(srcRoot, dir)
    if (!existsSync(absolute)) continue
    for (const entry of readdirSync(absolute)) {
      const path = resolve(absolute, entry)
      if (statSync(path).isFile() && /\.(ts|tsx)$/.test(entry)) files.push(path)
    }
  }
  for (const file of LIVE_SOURCE_FILES) {
    const path = resolve(srcRoot, file)
    if (existsSync(path)) files.push(path)
  }
  return files
}

describe('retired session/undo callers (#4839)', () => {
  it('has no shipped caller of a retired v1 session or undo path', () => {
    const violations = liveSourceFiles().flatMap((path) => {
      const source = readFileSync(path, 'utf-8')
      return RETIRED_CALLS.filter(({ pattern }) => pattern.test(source)).map(
        ({ label }) => `${path.replace(`${srcRoot}/`, '')}: ${label}`,
      )
    })

    expect(violations).toEqual([])
  })

  it('no longer ships the unused session pager hook', () => {
    const hookSource = readFileSync(resolve(srcRoot, 'hooks/useSession.ts'), 'utf-8')
    const barrelSource = readFileSync(resolve(srcRoot, 'hooks/index.ts'), 'utf-8')
    const serviceSource = readFileSync(resolve(srcRoot, 'services/api-sessions.ts'), 'utf-8')

    expect(hookSource).not.toMatch(/\buseSessions\b/)
    expect(barrelSource).not.toMatch(/\buseSessions\b/)
    expect(serviceSource).not.toMatch(/\blist:\s*async/)
    expect(serviceSource).not.toMatch(/\bget:\s*\(/)
  })

  it('keeps the supported session and undo reads on resource-shaped v2 paths', () => {
    const serviceSource = readFileSync(resolve(srcRoot, 'services/api-sessions.ts'), 'utf-8')
    const undoSource = readFileSync(resolve(srcRoot, 'services/api-undo.ts'), 'utf-8')

    expect(serviceSource).toContain('/v2/reading-sessions/${id}/details')
    expect(serviceSource).toContain('/v2/reading-sessions/${id}/snapshots')
    expect(undoSource).toContain('/v2/undo/${sessionId}/snapshots')
    expect(undoSource).toContain('/v2/undo/${sessionId}/snapshots/${snapshotId}/restore')
  })
})
