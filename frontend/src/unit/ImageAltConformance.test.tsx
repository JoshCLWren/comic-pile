import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative, sep } from 'path'
import { describe, expect, it } from 'vitest'

/**
 * Image alt-text conformance for #3069.
 *
 * Every rendered image must carry an explicit accessibility decision, and the
 * decision has two halves that both have to be visible in the source:
 *
 * - an explicit `alt` prop. Meaningful images describe themselves in text;
 *   decorative images pass an empty string so assistive technology skips them.
 * - an `ALT:` classification marker on the lines above the element saying
 *   whether the image is `meaningful` or `decorative` and why.
 *
 * `ImageWithLoading` additionally makes `alt` a required prop, so omitting it
 * already fails `pnpm run typecheck`. This suite is the guard that keeps the
 * written classification from drifting back to an undecided image.
 */

const SOURCE_ROOT = join(import.meta.dirname, '..')

/** Render sites owned by the reusable component rather than by a page. */
const COMPONENT_OWNED = new Set(['components/ImageWithLoading.tsx'])

const ELEMENT_OPENERS = /<(img|ImageWithLoading)(\s|\/|>|$)/

/** How many lines above an element may carry its `ALT:` marker. */
const MARKER_LOOKBACK_LINES = 6

/** Guard against a vacuous scan finding nothing to check. */
const MINIMUM_IMAGE_SITES = 5

function toSourcePath(full: string): string {
  return relative(SOURCE_ROOT, full).split(sep).join('/')
}

function isScannedFile(full: string, entry: string): boolean {
  if (full === import.meta.filename) return false
  if (!/\.(jsx|tsx)$/.test(entry)) return false
  if (entry.includes('.test.') || entry.includes('.spec.')) return false
  return true
}

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      const rel = toSourcePath(full)
      if (rel === 'unit' || rel === 'test' || rel.startsWith('unit/') || rel.startsWith('test/')) {
        continue
      }
      files.push(...collectSourceFiles(full))
    } else if (isScannedFile(full, entry)) {
      files.push(full)
    }
  }
  return files
}

function readLines(file: string): string[] {
  return readFileSync(file, 'utf-8').split('\n')
}

/**
 * Read the source text of a JSX element that starts on `startLine`.
 *
 * The element text runs until the line closing its opening tag, which for every
 * image in this codebase is the line carrying `/>`.
 */
function readElementText(lines: string[], startLine: number): string {
  const collected: string[] = []
  for (let index = startLine; index < lines.length; index += 1) {
    collected.push(lines[index])
    if (lines[index].includes('/>')) break
    if (index - startLine > 40) break
  }
  return collected.join('\n')
}

function hasAltMarker(lines: string[], startLine: number): boolean {
  const window = lines.slice(Math.max(0, startLine - MARKER_LOOKBACK_LINES), startLine).join('\n')
  return /ALT:/.test(window) && /(meaningful|decorative)/i.test(window)
}

interface ImageSite {
  file: string
  line: number
  element: string
}

function collectImageSites(): ImageSite[] {
  const sites: ImageSite[] = []
  for (const file of collectSourceFiles(SOURCE_ROOT)) {
    const lines = readLines(file)
    lines.forEach((line, index) => {
      const opened = ELEMENT_OPENERS.exec(line)
      if (!opened) return
      sites.push({
        file: toSourcePath(file),
        line: index + 1,
        element: opened[1] ?? 'img',
      })
    })
  }
  return sites
}

describe('Image alt-text conformance', () => {
  const sites = collectImageSites()

  it('finds the render-time image sites it is meant to guard', () => {
    expect(sites.length).toBeGreaterThanOrEqual(MINIMUM_IMAGE_SITES)
  })

  it('every image element carries an explicit alt decision', () => {
    const violations: string[] = []
    for (const site of sites) {
      if (COMPONENT_OWNED.has(site.file)) continue
      const lines = readLines(join(SOURCE_ROOT, site.file))
      if (!/\balt\s*=/.test(readElementText(lines, site.line - 1))) {
        violations.push(`${site.file}:${site.line} <${site.element}> has no explicit alt decision`)
      }
    }
    expect(violations, violations.join('\n')).toHaveLength(0)
  })

  it('every image element is classified as meaningful or decorative', () => {
    const violations: string[] = []
    for (const site of sites) {
      if (COMPONENT_OWNED.has(site.file)) continue
      const lines = readLines(join(SOURCE_ROOT, site.file))
      if (!hasAltMarker(lines, site.line - 1)) {
        violations.push(
          `${site.file}:${site.line} <${site.element}> has no 'ALT: meaningful|decorative' marker`,
        )
      }
    }
    expect(violations, violations.join('\n')).toHaveLength(0)
  })

  it('the reusable component keeps alt required and documented', () => {
    const content = readFileSync(join(SOURCE_ROOT, 'components/ImageWithLoading.tsx'), 'utf-8')
    expect(content).toMatch(/alt: string/)
    expect(content).not.toMatch(/alt\?: string/)
    expect(content).not.toMatch(/alt = ''/)
  })
})