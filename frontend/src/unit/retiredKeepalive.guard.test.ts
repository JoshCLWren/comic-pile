import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')

// The old heartbeat had no mounted caller and no native endpoint (#5721).
// AuthProvider and ResumeRecovery own authentication and tab-resume recovery.
function findRetiredKeepaliveReferences(directory: string): string[] {
  const violations: string[] = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      if (['unit', 'test', 'generated'].includes(entry.name)) continue
      violations.push(...findRetiredKeepaliveReferences(path))
    } else if (/\.[jt]sx?$/.test(entry.name)) {
      const source = readFileSync(path, 'utf8')
      if (/\buseKeepalive\b|\/v1\/keepalive\b/.test(source)) {
        violations.push(relative(SOURCE_ROOT, path))
      }
    }
  }
  return violations
}

it('does not ship the retired v1 keepalive hook or endpoint caller', () => {
  expect(findRetiredKeepaliveReferences(SOURCE_ROOT)).toEqual([])
})
