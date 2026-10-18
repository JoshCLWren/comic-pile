import { describe, expect, test } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const buildDir = resolve(__dirname, '..', '..', '..', 'static', 'react')

describe('SEO HTML generation', () => {
  test('CBL Sources page has correct title and metadata', () => {
    const htmlPath = resolve(buildDir, 'cbl-sources.html')
    expect(existsSync(htmlPath)).toBe(true)
    
    const html = readFileSync(htmlPath, 'utf-8')
    expect(html).toContain('<title>CBL Sources — Comic Pile</title>')
    expect(html).toContain('Browse trusted reading-order sources and add them as Reading Plans in ComicPile.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="CBL Sources — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="Browse trusted reading-order sources and add them as Reading Plans in ComicPile." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/cbl-sources" />')
  })

  test('Login page has correct title and metadata', () => {
    const htmlPath = resolve(buildDir, 'login.html')
    expect(existsSync(htmlPath)).toBe(true)
    
    const html = readFileSync(htmlPath, 'utf-8')
    expect(html).toContain('<title>Sign in — Comic Pile</title>')
    expect(html).toContain('ComicPile account utility page. This page is not indexed by search engines.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="Sign in — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="ComicPile account utility page. This page is not indexed by search engines." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/login" />')
  })

  test('Queue page has correct title and metadata', () => {
    const htmlPath = resolve(buildDir, 'queue.html')
    expect(existsSync(htmlPath)).toBe(true)
    
    const html = readFileSync(htmlPath, 'utf-8')
    expect(html).toContain('<title>Queue — Comic Pile</title>')
    expect(html).toContain('ComicPile personal comic reading queue. Sign in to roll for your next read.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="Queue — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="ComicPile personal comic reading queue. Sign in to roll for your next read." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/queue" />')
  })
})