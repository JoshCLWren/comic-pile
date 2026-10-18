import { describe, expect, test } from 'vitest'
import { generateRouteHtml, generateStructuredData } from '../../scripts/generate-route-html.mjs'

describe('SEO HTML generation', () => {
  test('CBL Sources page has correct title and metadata', () => {
    const route = {
      pattern: '/cbl-sources',
      title: 'CBL Sources — Comic Pile',
      description: 'Browse trusted reading-order sources and add them as Reading Plans in ComicPile.',
      canonicalPath: '/cbl-sources',
      visibility: 'private',
    }

    const html = generateRouteHtml(route)

    expect(html).toContain('<title>CBL Sources — Comic Pile</title>')
    expect(html).toContain('Browse trusted reading-order sources and add them as Reading Plans in ComicPile.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="CBL Sources — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="Browse trusted reading-order sources and add them as Reading Plans in ComicPile." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/cbl-sources" />')
  })

  test('Login page has correct title and metadata', () => {
    const route = {
      pattern: '/login',
      title: 'Sign in — Comic Pile',
      description: 'ComicPile account utility page. This page is not indexed by search engines.',
      canonicalPath: '/login',
      visibility: 'private',
    }

    const html = generateRouteHtml(route)

    expect(html).toContain('<title>Sign in — Comic Pile</title>')
    expect(html).toContain('ComicPile account utility page. This page is not indexed by search engines.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="Sign in — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="ComicPile account utility page. This page is not indexed by search engines." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/login" />')
  })

  test('Queue page has correct title and metadata', () => {
    const route = {
      pattern: '/queue',
      title: 'Queue — Comic Pile',
      description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.',
      canonicalPath: '/queue',
      visibility: 'public-indexable',
    }

    const html = generateRouteHtml(route)

    expect(html).toContain('<title>Queue — Comic Pile</title>')
    expect(html).toContain('ComicPile personal comic reading queue. Sign in to roll for your next read.')
    expect(html).toContain('<meta name="robots" content="index, follow" />')
    expect(html).toContain('<meta property="og:title" content="Queue — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="ComicPile personal comic reading queue. Sign in to roll for your next read." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/queue" />')
    expect(html).toContain('<script id="comic-pile-structured-data" type="application/ld+json">')
  })

  test('Landing page has correct title and metadata', () => {
    const route = {
      pattern: '/',
      title: 'ComicPile',
      description: 'A dice-driven reading queue for your comic collection.',
      canonicalPath: '/',
      visibility: 'public-indexable',
    }

    const html = generateRouteHtml(route)

    expect(html).toContain('<title>ComicPile</title>')
    expect(html).toContain('A dice-driven reading queue for your comic collection.')
    expect(html).toContain('<meta name="robots" content="index, follow" />')
    expect(html).toContain('<meta property="og:title" content="ComicPile" />')
    expect(html).toContain('<meta property="og:description" content="A dice-driven reading queue for your comic collection." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/" />')
    expect(html).toContain('<script id="comic-pile-structured-data" type="application/ld+json">')
  })

  test('Structured data is generated correctly for public-indexable routes', () => {
    const structuredData = generateStructuredData()

    expect(structuredData).toContain('"@context": "https://schema.org"')
    expect(structuredData).toContain('"@type": "WebSite"')
    expect(structuredData).toContain('"@type": "SoftwareApplication"')
    expect(structuredData).toContain('"name": "ComicPile"')
    expect(structuredData).toContain('featureList')
    expect(structuredData).toContain('Weighted by your history')
    expect(structuredData).toContain('Continuity-aware')
  })
})
