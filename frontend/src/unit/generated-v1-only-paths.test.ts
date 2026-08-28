import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const schemaPath = resolve(__dirname, '../generated/openapi.json')
const schema = JSON.parse(readFileSync(schemaPath, 'utf-8')) as {
  paths: Record<string, unknown>
}

// Bare `/api` domain routes are legacy compatibility aliases served only until
// the v1 cutover completes. The generated client surface must reference none
// of them; `/api/ping` is the single documented exemption.
const EXEMPT_BARE_PATHS = new Set(['/api/ping'])

function isBareDomainPath(path: string): boolean {
  return path.startsWith('/api/') && !EXEMPT_BARE_PATHS.has(path) && !path.startsWith('/api/v1/')
}

describe('generated OpenAPI client surface', () => {
  it('contains zero bare domain-path references', () => {
    const paths = Object.keys(schema.paths)
    const violations = paths.filter(isBareDomainPath)

    expect(violations).toEqual([])
  })

  it('retains canonical v1 coverage and the ping exemption', () => {
    const paths = Object.keys(schema.paths)

    expect(paths.some((path) => path.startsWith('/api/v1/'))).toBe(true)
    expect(paths).toContain('/api/ping')
  })
})
