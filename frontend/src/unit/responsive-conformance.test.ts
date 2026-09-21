import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')

/**
 * Files that may legitimately reference viewport geometry or name the
 * responsive API. Application code must route responsive behavior through
 * `frontend/src/utils/responsive.ts`; telemetry may report raw viewport
 * dimensions without branching on them.
 */
const ALLOWLIST = new Set(['utils/responsive.ts', 'hooks/useDiagnostics.ts'])

const FORBIDDEN_PATTERNS = ['window.innerWidth', 'innerWidth']

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...collectSourceFiles(full))
    } else if (/\.(js|jsx|ts|tsx)$/.test(entry)) {
      files.push(full)
    }
  }
  return files
}

function relativeToSource(file: string): string {
  return file.slice(SOURCE_ROOT.length + 1).replaceAll('\\', '/')
}

it('application source never reads window.innerWidth for responsive behavior', () => {
  const files = collectSourceFiles(SOURCE_ROOT).filter(
    (file) =>
      !relativeToSource(file).startsWith('unit/') &&
      !relativeToSource(file).startsWith('test/') &&
      !ALLOWLIST.has(relativeToSource(file)),
  )
  const violations: string[] = []

  for (const file of files) {
    const content = readFileSync(file, 'utf-8')
    for (const pattern of FORBIDDEN_PATTERNS) {
      if (content.includes(pattern)) {
        violations.push(`${relativeToSource(file)}: found "${pattern}"`)
      }
    }
    for (const line of content.split('\n')) {
      if (line.includes('matchMedia(') && line.includes('px')) {
        violations.push(`${relativeToSource(file)}: inline breakpoint matchMedia query`)
        break
      }
    }
  }

  expect(violations, violations.join('\n')).toHaveLength(0)
})
