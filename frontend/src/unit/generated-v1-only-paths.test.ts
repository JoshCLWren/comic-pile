import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const schemaPath = resolve(__dirname, '../generated/openapi.json')
// SAFETY: the committed API schema file has exactly this shape
const schema = JSON.parse(readFileSync(schemaPath, 'utf-8')) as {
  paths: Record<string, Record<string, string>>
}

// Bare `/api` domain routes are legacy compatibility aliases served only until
// their versioned replacements are adopted. The generated client surface must reference none
// of them except the same-path native startup metrics contract (#4854). The retired
// `/api/v1/metrics` alias (#4348) is no longer published.
const EXEMPT_BARE_PATHS = new Set(['/api/metrics'])

function isBareDomainPath(path: string): boolean {
  return path.startsWith('/api/') && !EXEMPT_BARE_PATHS.has(path) && !path.startsWith('/api/v1/') && !path.startsWith('/api/v2/')
}

describe('generated OpenAPI client surface', () => {
  it('contains zero bare domain-path references', () => {
    const paths = Object.keys(schema.paths)
    const violations = paths.filter(isBareDomainPath)

    expect(violations).toEqual([])
  })

  it('retains canonical v1 coverage and publishes migrated v2 operations', () => {
    const paths = Object.keys(schema.paths)

    expect(paths.some((path) => path.startsWith('/api/v1/'))).toBe(true)
    expect(paths).not.toContain('/api/ping')
    expect(paths).toContain('/api/metrics')
    expect(paths).not.toContain('/api/v1/metrics')
    for (const path of [
      '/api/v2/releases',
      '/api/v2/roll/override',
      '/api/v2/roll/dismiss-pending',
      '/api/v2/roll/switch-prerequisite',
      '/api/v2/reading-sessions/{session_id}/details',
      '/api/v2/reading-sessions/{session_id}/snapshots',
    ]) {
      expect(paths).toContain(path)
    }
  })
})
