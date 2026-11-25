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

  it('keeps cover-bearing source on shared presentation components', () => {
    const files = collectSourceFiles(SOURCE_ROOT).filter((file) => {
      const rel = relativeToSource(file)
      return !rel.startsWith('unit/') && !rel.startsWith('test/')
    })
    const violations: string[] = []
    const coverFieldPattern = /\b(cover_image_url|series_cover_image_url)\b/
    const sharedPresentationPattern =
      /ComicIssueCover|CompactIssueCardTrigger|ComicIssueReadingCard|ComicIssueCard|ImageWithLoading|DirectReadIssuePanel|ReaderIssueActions/

    for (const file of files) {
      const rel = relativeToSource(file)
      if (
        rel === 'components/ImageWithLoading.tsx' ||
        rel === 'components/ComicIssueCard.tsx' ||
        rel === 'components/CompactIssueCardTrigger.tsx' ||
        rel === 'components/ComicIssueReadingCard.tsx' ||
        rel === 'types/index.ts' ||
        rel === 'services/api-comicvine.ts' ||
        rel === 'services/issueCardsApi.ts' ||
        rel === 'generated/openapi.ts'
      ) {
        continue
      }
      const content = readFileSync(file, 'utf-8')
      if (!coverFieldPattern.test(content)) continue
      if (sharedPresentationPattern.test(content)) continue
      // Allow data plumbing/hooks that pass cover fields through without rendering.
      const rendersJsx = /<[A-Za-z]/.test(content)
      if (!rendersJsx) continue
      violations.push(
        `${rel}: references cover fields in JSX but does not use a shared cover presentation component`,
      )
    }

    expect(violations, violations.join('\n')).toHaveLength(0)
  })
})
