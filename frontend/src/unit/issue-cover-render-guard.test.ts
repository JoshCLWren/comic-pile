import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { describe, expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')

/**
 * #5433 closure guard: comic/series cover presentation must flow through
 * shared components, never bespoke raw <img> markup.
 *
 * Shared owners:
 * - `components/ImageWithLoading.tsx` is the only raw <img> implementation.
 * - `components/ComicIssueCard.tsx` owns ComicIssueCover / ComicIssueCard.
 * - `components/CompactIssueCardTrigger.tsx` owns compact covered rows.
 * - `components/ComicIssueReadingCard.tsx` composes the shared card.
 *
 * Any new raw <img> in app source is a regression unless it is moved into a
 * shared image component and this allowlist is updated with justification.
 */
const RAW_IMG_ALLOWLIST = new Set(['components/ImageWithLoading.tsx'])

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...collectSourceFiles(full))
    } else if (/\.(tsx|ts)$/.test(entry)) {
      files.push(full)
    }
  }
  return files
}

function relativeToSource(file: string): string {
  return file.slice(SOURCE_ROOT.length + 1)
}

describe('issue cover render guard (#5433)', () => {
  it('does not introduce raw <img> outside shared image components', () => {
    const files = collectSourceFiles(SOURCE_ROOT).filter((file) => {
      const rel = relativeToSource(file)
      return !rel.startsWith('unit/') && !rel.startsWith('test/') && !RAW_IMG_ALLOWLIST.has(rel)
    })
    const violations: string[] = []

    for (const file of files) {
      const rel = relativeToSource(file)
      const content = readFileSync(file, 'utf-8')
      if (/<img\b/.test(content)) {
        violations.push(`${rel}: raw <img> is not allowed; use ComicIssueCover/ImageWithLoading`)
      }
    }

    expect(violations, violations.join('\n')).toHaveLength(0)
  })

  it('keeps cover image URLs flowing through shared image components', () => {
    const files = collectSourceFiles(SOURCE_ROOT).filter((file) => {
      const rel = relativeToSource(file)
      return !rel.startsWith('unit/') && !rel.startsWith('test/')
    })
    const violations: string[] = []
    // Catch bespoke image rendering: <img src={...cover...}> or similar direct src bindings.
    const bespokeCoverSrc =
      /<img\b[\s\S]{0,200}?src=\{[^}]*(cover_image_url|series_cover_image_url|coverImageUrl|image_url)[^}]*\}/

    for (const file of files) {
      const rel = relativeToSource(file)
      if (RAW_IMG_ALLOWLIST.has(rel)) continue
      const content = readFileSync(file, 'utf-8')
      if (bespokeCoverSrc.test(content)) {
        violations.push(`${rel}: binds cover URL directly to <img>; use ComicIssueCover/ImageWithLoading`)
      }
    }

    expect(violations, violations.join('\n')).toHaveLength(0)
  })
})
