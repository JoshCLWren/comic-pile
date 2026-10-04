import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

// The prerendered shell in frontend/index.html is the crawlable HTML for `/`,
// the only public-indexable route (see seo/routeSeo.ts). These guards keep the
// indexable surface concrete to ComicPile and carry the real maintainer
// identity without JavaScript (issue #3071).
const frontendRoot = path.resolve(import.meta.dirname, '../..')

function readShellHtml(): string {
  return readFileSync(path.join(frontendRoot, 'index.html'), 'utf-8')
}

describe('prerendered public shell copy (issue #3071)', () => {
  it('uses the specific product title and description, not generic SaaS filler', () => {
    const html = readShellHtml()
    expect(html).toContain('ComicPile — A dice-driven reading queue for your comic collection')
    const genericPhrases = [
      /smart tracking/i,
      /join the community/i,
      /in 60 seconds/i,
      /no credit card/i,
      /sign up free/i,
      /unleash/i,
      /supercharge/i,
    ]
    for (const phrase of genericPhrases) {
      expect(html).not.toMatch(phrase)
    }
  })

  it('gives crawlers the maintainer identity in the prerendered landing content', () => {
    const html = readShellHtml()
    const prerendered = html.slice(
      html.indexOf('data-prerendered-landing'),
      html.indexOf('</main>'),
    )
    expect(prerendered).toContain('maintained by')
    expect(prerendered).toContain('JoshCLWren on GitHub')
    expect(prerendered).toContain('href="https://github.com/JoshCLWren"')
  })

  it('keeps the noscript notice specific and attributed', () => {
    const html = readShellHtml()
    const noscript = html.slice(html.indexOf('<noscript>'), html.indexOf('</noscript>'))
    expect(noscript).toMatch(/dice-driven reading queue for your comic collection/i)
    expect(noscript).toContain('maintained by')
    expect(noscript).toContain('href="https://github.com/JoshCLWren"')
  })

  it('never presents a fabricated author byline on the product surface', () => {
    const html = readShellHtml()
    expect(html).not.toMatch(/written by/i)
    expect(html).not.toMatch(/by our team/i)
  })
})
