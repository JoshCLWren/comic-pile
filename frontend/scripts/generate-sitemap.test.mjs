import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { indexableRoutes, ROUTE_SEO_TABLE } from '../src/seo/routeSeo.ts'
import {
  DEFAULT_OUT_DIR,
  DEFAULT_PRODUCTION_ORIGIN,
  escapeXml,
  generateRobotsTxt,
  generateSitemapXml,
  resolveProductionOrigin,
  SOURCE_ROBOTS_PATH,
  writeArtifacts,
} from './generate-sitemap.mjs'

const SITEMAP_LOCATION = /<loc>([^<]*)<\/loc>/g

function locationsIn(xml) {
  return Array.from(xml.matchAll(SITEMAP_LOCATION), (match) => match[1])
}

function readPolicySource() {
  return readFileSync(SOURCE_ROBOTS_PATH, 'utf-8')
}

test('sitemap lists exactly the canonical public-indexable routes', () => {
  const entries = indexableRoutes()
  const xml = generateSitemapXml(entries, DEFAULT_PRODUCTION_ORIGIN)

  assert.deepEqual(
    locationsIn(xml),
    entries.map((entry) => `${DEFAULT_PRODUCTION_ORIGIN}${entry.canonicalPath}`),
  )
  assert.ok(locationsIn(xml).includes(`${DEFAULT_PRODUCTION_ORIGIN}/`))
  assert.ok(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n'))
  assert.ok(xml.includes('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'))
})

test('no private or public-noindex route leaks into the sitemap', () => {
  const xml = generateSitemapXml(indexableRoutes(), DEFAULT_PRODUCTION_ORIGIN)

  for (const entry of ROUTE_SEO_TABLE) {
    if (entry.visibility === 'public-indexable') continue
    const concretePath = entry.pattern.replace(/:[^/]+/, 'sample')
    const location = `${DEFAULT_PRODUCTION_ORIGIN}${concretePath}`
    assert.ok(!xml.includes(location), `${entry.visibility} route ${concretePath} must be absent`)
  }
})

test('an indexable route without a canonical path fails generation', () => {
  const malformed = [
    { pattern: '/pricing', visibility: 'public-indexable', canonicalPath: null, title: '', description: '' },
  ]

  assert.throws(
    () => generateSitemapXml(malformed, DEFAULT_PRODUCTION_ORIGIN),
    /has no canonicalPath/,
  )
})

test('resolveProductionOrigin falls back to the canonical production origin', () => {
  assert.equal(resolveProductionOrigin({}), DEFAULT_PRODUCTION_ORIGIN)
  assert.equal(resolveProductionOrigin({ VITE_PRODUCTION_ORIGIN: '' }), DEFAULT_PRODUCTION_ORIGIN)
  assert.equal(resolveProductionOrigin({ VITE_PRODUCTION_ORIGIN: '   ' }), DEFAULT_PRODUCTION_ORIGIN)
  assert.equal(
    resolveProductionOrigin({ VITE_PRODUCTION_ORIGIN: 'https://stage.example.com/' }),
    'https://stage.example.com',
  )
})

test('resolveProductionOrigin rejects malformed overrides', () => {
  assert.throws(
    () => resolveProductionOrigin({ VITE_PRODUCTION_ORIGIN: 'comicpile.example.com' }),
    /absolute URL/,
  )
  assert.throws(
    () => resolveProductionOrigin({ VITE_PRODUCTION_ORIGIN: 'ftp://comicpile.example.com' }),
    /HTTP\(S\)/,
  )
  assert.throws(
    () => resolveProductionOrigin({ VITE_PRODUCTION_ORIGIN: 'https://comicpile.example.com/app' }),
    /origin only/,
  )
})

test('robots.txt is byte-identical to the version-controlled policy at the canonical origin', () => {
  const source = readPolicySource()

  assert.equal(generateRobotsTxt(source, DEFAULT_PRODUCTION_ORIGIN), source)
  assert.ok(source.includes(`Sitemap: ${DEFAULT_PRODUCTION_ORIGIN}/sitemap.xml`))
  assert.ok(source.includes('Disallow: /debug/'))
})

test('robots.txt override rewrites only the sitemap origin', () => {
  const source = readPolicySource()
  const overridden = generateRobotsTxt(source, 'https://stage.example.com')

  assert.ok(overridden.includes('Sitemap: https://stage.example.com/sitemap.xml'))
  assert.equal(
    overridden.replace(
      /^Sitemap: \S+$/m,
      `Sitemap: ${DEFAULT_PRODUCTION_ORIGIN}/sitemap.xml`,
    ),
    source,
  )
})

test('escapeXml escapes every XML special character', () => {
  assert.equal(escapeXml('&<>"\''), '&amp;&lt;&gt;&quot;&apos;')
  assert.equal(escapeXml('https://comic-pile.vercel.app/'), 'https://comic-pile.vercel.app/')
})

test('writeArtifacts derives both build artifacts from the canonical sources', () => {
  const outDir = mkdtempSync(path.join(tmpdir(), 'comic-pile-sitemap-'))

  try {
    const result = writeArtifacts(outDir, DEFAULT_PRODUCTION_ORIGIN)
    const sitemap = readFileSync(path.join(outDir, 'sitemap.xml'), 'utf-8')
    const robots = readFileSync(path.join(outDir, 'robots.txt'), 'utf-8')

    assert.equal(result.urlCount, indexableRoutes().length)
    assert.deepEqual(
      locationsIn(sitemap),
      indexableRoutes().map((entry) => `${DEFAULT_PRODUCTION_ORIGIN}${entry.canonicalPath}`),
    )
    assert.equal(robots, readPolicySource())
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
})

test('default output directory matches the vite build outDir', () => {
  assert.equal(path.join(path.basename(path.dirname(DEFAULT_OUT_DIR)), path.basename(DEFAULT_OUT_DIR)), path.join('static', 'react'))
})
