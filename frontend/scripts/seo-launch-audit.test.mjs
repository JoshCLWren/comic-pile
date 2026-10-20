/**
 * Focused tests for the production SEO launch audit (issue #3072).
 *
 * The audit is the machine-checkable half of the launch contract: it proves a
 * deployed origin honors the canonical indexability policy, and it is the
 * evidence an operator uses for the Google Search Console steps that code
 * cannot perform.
 *
 * The integration cases run the audit against a real local HTTP server that
 * imitates a deployment, so the request path, the redirect handling, and the
 * finding rules are exercised end to end without mocking any module.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import http from 'node:http'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { indexableRoutes } from '../src/seo/routeSeo.ts'
import {
  auditOrigin,
  DEFAULT_BASELINE_PATH,
  evaluateRoute,
  isCrawlDisallowed,
  parseArguments,
  parseRobotsPolicy,
  parseSitemapLocations,
  readBaselineRecord,
  readHeadSignals,
  renderAuditMarkdown,
  resolveBaselinePath,
  robotsValueBlocksIndexing,
  routeSamplePath,
  validateBaselineRecord,
} from './seo-launch-audit.mjs'

const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url))
const ROBOTS_SOURCE = resolve(SCRIPT_DIRECTORY, '..', 'public', 'robots.txt')
const PRODUCTION_ORIGIN = 'https://comic-pile.vercel.app'

const LANDING_DESCRIPTION = 'ComicPile is a dice-driven reading queue.'
const NOINDEX_HTML = [
  '<!doctype html><html lang="en"><head>',
  '<meta charset="utf-8" />',
  '<title>Queue — Comic Pile</title>',
  '<meta name="description" content="ComicPile personal comic reading queue." />',
  '<meta name="robots" content="noindex, nofollow" />',
  '</head><body><div id="root"></div></body></html>',
].join('\n')

/**
 * Build the landing document for one origin.
 *
 * @param {string} origin - Origin the document is served from.
 * @returns {string} The landing HTML document.
 */
function landingHtml(origin) {
  return [
    '<!doctype html><html lang="en"><head>',
    '<meta charset="utf-8" />',
    '<title>ComicPile — A dice-driven reading queue for your comic collection</title>',
    `<meta name="description" content="${LANDING_DESCRIPTION}" />`,
    `<link rel="canonical" href="${origin}/" />`,
    '<meta name="robots" content="index, follow" />',
    '</head><body><main data-prerendered-landing>ComicPile</main></body></html>',
  ].join('\n')
}

const LANDING_HTML = landingHtml(PRODUCTION_ORIGIN)
/**
 * Start a local HTTP server that imitates a ComicPile deployment.
 *
 * @param {object} options - Server options.
 * @param {boolean} options.disallowPrivateInRobots - When false, the served
 *   `robots.txt` allows the private route families.
 * @param {boolean} options.serveNoindex - When false, private routes serve the
 *   indexable landing document, which reproduces the production regression
 *   where authenticated pages claim `index, follow`.
 * @returns {Promise<{origin: string, close: Function}>} The running server.
 */
async function startServer(options) {
  const policySource = readFileSync(ROBOTS_SOURCE, 'utf-8')
  let origin = ''

  const server = http.createServer((request, response) => {
    const path = (request.url ?? '/').split('?')[0]
    if (path === '/robots.txt') {
      const policy = options.disallowPrivateInRobots
        ? policySource
        : policySource.replace(/^Disallow:.*$/gm, '')
      const body = policy.replace(/^Sitemap: \S+$/m, `Sitemap: ${origin}/sitemap.xml`)
      response.writeHead(200, { 'content-type': 'text/plain' })
      response.end(body)
      return
    }
    if (path === '/sitemap.xml') {
      const locations = indexableRoutes().map((entry) => `${origin}${entry.canonicalPath}`)
      const body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ...locations.map((location) => `  <url><loc>${location}</loc></url>`),
        '</urlset>',
      ].join('\n')
      response.writeHead(200, { 'content-type': 'application/xml' })
      response.end(body)
      return
    }
    if (path === '/') {
      response.writeHead(200, { 'content-type': 'text/html' })
      response.end(landingHtml(origin))
      return
    }
    if (options.serveNoindex) {
      response.writeHead(200, {
        'content-type': 'text/html',
        'x-robots-tag': 'noindex, nofollow',
      })
      response.end(NOINDEX_HTML)
      return
    }
    response.writeHead(200, { 'content-type': 'text/html' })
    response.end(landingHtml(origin))
  })

  await new Promise((resolvePromise) => {
    server.listen(0, '127.0.0.1', resolvePromise)
  })
  const address = server.address()
  const port = address === null ? 0 : address.port
  origin = `http://127.0.0.1:${port}`
  return {
    origin,
    close: () => new Promise((resolvePromise) => server.close(resolvePromise)),
  }
}

test('robots policy parsing keeps rules and sitemap references', () => {
  const policy = parseRobotsPolicy(
    [
      '# comment',
      'User-agent: *',
      'Allow: /',
      'Allow: /assets/',
      'Disallow: /login',
      'Disallow: /thread/',
      'Sitemap: https://comic-pile.vercel.app/sitemap.xml',
    ].join('\n'),
  )

  assert.deepEqual(policy.rules, [
    { type: 'allow', pattern: '/' },
    { type: 'allow', pattern: '/assets/' },
    { type: 'disallow', pattern: '/login' },
    { type: 'disallow', pattern: '/thread/' },
  ])
  assert.deepEqual(policy.sitemapReferences, ['https://comic-pile.vercel.app/sitemap.xml'])
})

test('the longest robots rule wins and an equal-length allow beats a disallow', () => {
  const policy = parseRobotsPolicy(
    ['User-agent: *', 'Allow: /', 'Disallow: /creators', 'Allow: /creators/compare'].join('\n'),
  )

  assert.equal(isCrawlDisallowed('/queue', policy.rules), false)
  assert.equal(isCrawlDisallowed('/creators', policy.rules), true)
  assert.equal(isCrawlDisallowed('/creators/compare', policy.rules), false)
  assert.equal(isCrawlDisallowed('/creators/some-creator', policy.rules), true)
})

test('sitemap locations are read from the served document', () => {
  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    '  <url><loc>https://comic-pile.vercel.app/</loc></url>',
    '</urlset>',
  ].join('\n')

  assert.deepEqual(parseSitemapLocations(xml), ['https://comic-pile.vercel.app/'])
  assert.deepEqual(parseSitemapLocations('<urlset></urlset>'), [])
})

test('head signals are read from the served document', () => {
  const signals = readHeadSignals(LANDING_HTML)

  assert.equal(signals.title, 'ComicPile — A dice-driven reading queue for your comic collection')
  assert.equal(signals.description, 'ComicPile is a dice-driven reading queue.')
  assert.equal(signals.robotsMeta, 'index, follow')
  assert.equal(signals.canonical, 'https://comic-pile.vercel.app/')
  assert.equal(readHeadSignals('<html><head></head></html>').canonical, null)
})

test('a noindex robots directive blocks indexing', () => {
  assert.equal(robotsValueBlocksIndexing('noindex, nofollow'), true)
  assert.equal(robotsValueBlocksIndexing('index, follow'), false)
  assert.equal(robotsValueBlocksIndexing(null), false)
})

test('route patterns become concrete request paths', () => {
  assert.equal(routeSamplePath('/'), '/')
  assert.equal(routeSamplePath('/queue'), '/queue')
  assert.equal(routeSamplePath('/thread/:id'), '/thread/1')
  assert.equal(routeSamplePath('/creators/:creatorKey'), '/creators/some-creator')
})

test('an indexable route with a canonical URL and no noindex passes', () => {
  const findings = evaluateRoute(
    { pattern: '/', visibility: 'public-indexable', canonicalPath: '/' },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/',
      status: 200,
      head: readHeadSignals(LANDING_HTML),
      headerRobots: null,
      disallowed: false,
      redirectCount: 0,
    },
  )

  assert.deepEqual(findings, [])
})

test('an indexable route that claims noindex is a blocking finding', () => {
  const findings = evaluateRoute(
    { pattern: '/', visibility: 'public-indexable', canonicalPath: '/' },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/',
      status: 200,
      head: { title: 'ComicPile', description: null, robotsMeta: 'noindex, nofollow', canonical: null },
      headerRobots: 'noindex, nofollow',
      disallowed: false,
      redirectCount: 0,
    },
  )

  const codes = findings.map((entry) => entry.code)
  assert.ok(codes.includes('indexable-route-noindex-meta'))
  assert.ok(codes.includes('indexable-route-noindex-header'))
  assert.ok(codes.includes('indexable-route-missing-canonical'))
})

test('an indexable route with a foreign canonical URL is a blocking finding', () => {
  const findings = evaluateRoute(
    { pattern: '/', visibility: 'public-indexable', canonicalPath: '/' },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/',
      status: 200,
      head: {
        title: 'ComicPile',
        description: null,
        robotsMeta: 'index, follow',
        canonical: 'https://comic-pile.vercel.app/queue',
      },
      headerRobots: null,
      disallowed: false,
      redirectCount: 0,
    },
  )

  assert.ok(findings.some((entry) => entry.code === 'indexable-route-canonical-mismatch'))
})

test('a private route with no index-blocking signal is a blocking finding', () => {
  const findings = evaluateRoute(
    { pattern: '/queue', visibility: 'private', canonicalPath: null },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/queue',
      status: 200,
      head: readHeadSignals(LANDING_HTML),
      headerRobots: null,
      disallowed: false,
      redirectCount: 0,
    },
  )

  assert.ok(findings.some((entry) => entry.code === 'non-indexable-route-indexable'))
  assert.equal(
    findings.some((entry) => entry.severity === 'error'),
    true,
  )
})

test('a private route blocked only by robots.txt still needs a noindex directive', () => {
  const findings = evaluateRoute(
    { pattern: '/queue', visibility: 'private', canonicalPath: null },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/queue',
      status: 200,
      head: readHeadSignals(LANDING_HTML),
      headerRobots: null,
      disallowed: true,
      redirectCount: 0,
    },
  )

  assert.deepEqual(
    findings.map((entry) => entry.code),
    ['non-indexable-route-missing-noindex'],
  )
  assert.equal(findings[0].severity, 'error')
})

test('a private route that robots.txt allows is a blocking finding', () => {
  const findings = evaluateRoute(
    { pattern: '/queue', visibility: 'private', canonicalPath: null },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/queue',
      status: 200,
      head: readHeadSignals(NOINDEX_HTML),
      headerRobots: 'noindex, nofollow',
      disallowed: false,
      redirectCount: 0,
    },
  )

  assert.deepEqual(
    findings.map((entry) => entry.code),
    ['non-indexable-route-not-disallowed'],
  )
})

test('a private route blocked by robots.txt and a noindex directive passes', () => {
  const findings = evaluateRoute(
    { pattern: '/queue', visibility: 'private', canonicalPath: null },
    {
      origin: PRODUCTION_ORIGIN,
      path: '/queue',
      status: 200,
      head: readHeadSignals(NOINDEX_HTML),
      headerRobots: 'noindex, nofollow',
      disallowed: true,
      redirectCount: 0,
    },
  )

  assert.deepEqual(findings, [])
})

test('a compliant deployment audits without blocking findings', async () => {
  const server = await startServer({ disallowPrivateInRobots: true, serveNoindex: true })
  try {
    const report = await auditOrigin({ origin: server.origin })
    assert.equal(report.summary.errors, 0, JSON.stringify(report.findings, null, 2))
    assert.equal(report.summary.warnings, 0, JSON.stringify(report.findings, null, 2))
    assert.equal(report.summary.routesAudited > 0, true)
    assert.deepEqual(report.sitemap.locations, report.sitemap.expectedLocations)
  } finally {
    await server.close()
  }
})

test('a deployment that exposes private routes reports them as indexable', async () => {
  const server = await startServer({ disallowPrivateInRobots: true, serveNoindex: false })
  try {
    const report = await auditOrigin({ origin: server.origin })
    const leaks = report.findings.filter(
      (entry) => entry.code === 'non-indexable-route-missing-noindex',
    )
    assert.equal(leaks.length > 0, true)
    assert.equal(report.summary.errors > 0, true)
    const queueFinding = leaks.find((entry) => entry.route === '/queue')
    assert.notEqual(queueFinding, undefined)
  } finally {
    await server.close()
  }
})

test('a deployment that allows and exposes private routes reports a full indexability leak', async () => {
  const server = await startServer({ disallowPrivateInRobots: false, serveNoindex: false })
  try {
    const report = await auditOrigin({ origin: server.origin })
    const leaks = report.findings.filter((entry) => entry.code === 'non-indexable-route-indexable')
    assert.equal(leaks.length > 0, true)
    const queueFinding = leaks.find((entry) => entry.route === '/queue')
    assert.notEqual(queueFinding, undefined)
  } finally {
    await server.close()
  }
})

test('the markdown report lists the audited routes and the open operator steps', async () => {
  const server = await startServer({ disallowPrivateInRobots: true, serveNoindex: true })
  try {
    const report = await auditOrigin({ origin: server.origin })
    const markdown = renderAuditMarkdown(report, null)

    assert.ok(markdown.includes('## Indexable public URLs'))
    assert.ok(markdown.includes('## Utility and authenticated URLs'))
    assert.ok(markdown.includes('`/queue`'))
    assert.ok(markdown.includes('## Operator steps still open'))
    assert.ok(markdown.includes('Google Search Console ownership'))
  } finally {
    await server.close()
  }
})

test('a complete baseline record validates', () => {
  const record = {
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    offsiteOpportunities: [
      { name: 'A', url: 'https://example.com/a', relevance: 'self-hosted tools', outreach: 'not-started' },
      { name: 'B', url: 'https://example.com/b', relevance: 'comics community', outreach: 'not-started' },
      { name: 'C', url: 'https://example.com/c', relevance: 'developer directory', outreach: 'not-started' },
    ],
    linkPolicy: 'earned-only',
  }

  assert.deepEqual(validateBaselineRecord(record), [])
})

test('an incomplete baseline record reports every open operator step', () => {
  const problems = validateBaselineRecord({
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: null,
    searchConsole: {
      ownershipVerified: null,
      sitemapSubmitted: null,
      indexedPageCount: null,
      impressions: null,
      clicks: null,
    },
    offsiteOpportunities: [
      { name: 'A', url: 'https://example.com/a', relevance: 'self-hosted tools', outreach: 'not-started' },
    ],
    linkPolicy: 'earned-only',
  })

  const joined = problems.join('\n')
  assert.ok(joined.includes('ownership is not verified'))
  assert.ok(joined.includes('sitemap is not recorded as submitted'))
  assert.ok(joined.includes('indexedPageCount has not been recorded'))
  assert.ok(joined.includes('At least 3 realistic off-site discovery opportunities'))
  assert.ok(joined.includes('recordedAt has not been recorded yet'))
})

test('an otherwise complete but undated baseline record reports missing date', () => {
  const problems = validateBaselineRecord({
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: null,
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    offsiteOpportunities: [
      { name: 'A', url: 'https://example.com/a', relevance: 'self-hosted tools', outreach: 'not-started' },
      { name: 'B', url: 'https://example.com/b', relevance: 'comics community', outreach: 'not-started' },
      { name: 'C', url: 'https://example.com/c', relevance: 'developer directory', outreach: 'not-started' },
    ],
    linkPolicy: 'earned-only',
  })

  const joined = problems.join('\n')
  assert.ok(joined.includes('recordedAt has not been recorded yet'))
  assert.equal(problems.filter(p => p.includes('off-site discovery')).length, 0)
})

test('a baseline record cannot claim a paid link scheme', () => {
  const problems = validateBaselineRecord({
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    offsiteOpportunities: [
      { name: 'A', url: 'https://example.com/a', relevance: 'self-hosted tools', outreach: 'published', paid: true },
      { name: 'B', url: 'https://example.com/b', relevance: 'comics community', outreach: 'not-started' },
      { name: 'C', url: 'https://example.com/c', relevance: 'developer directory', outreach: 'not-started' },
    ],
    linkPolicy: 'paid',
  })

  const joined = problems.join('\n')
  assert.ok(joined.includes('linkPolicy must be "earned-only"'))
  assert.ok(joined.includes('is marked as a paid link'))
})

test('a baseline record with null opportunities reports useful errors instead of crashing', () => {
  const problems = validateBaselineRecord({
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    offsiteOpportunities: [
      { name: 'A', url: 'https://example.com/a', relevance: 'self-hosted tools', outreach: 'not-started' },
      null,
      { name: 'C', url: 'https://example.com/c', relevance: 'developer directory', outreach: 'not-started' },
    ],
    linkPolicy: 'earned-only',
  })

  const joined = problems.join('\n')
  assert.ok(joined.includes('Every off-site opportunity must be an object'))
  assert.ok(joined.includes('At least 3 realistic off-site discovery opportunities'))
})

test('a missing offsiteOpportunities key reports missing opportunities instead of crashing', () => {
  const record = {
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    linkPolicy: 'earned-only',
  }

  assert.doesNotThrow(() => validateBaselineRecord(record))
  const problems = validateBaselineRecord(record)
  const joined = problems.join('\n')
  assert.ok(joined.includes('At least 3 realistic off-site discovery opportunities'))
})

test('a null offsiteOpportunities reports missing opportunities instead of crashing', () => {
  const problems = validateBaselineRecord({
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    offsiteOpportunities: null,
    linkPolicy: 'earned-only',
  })

  const joined = problems.join('\n')
  assert.ok(joined.includes('At least 3 realistic off-site discovery opportunities'))
  assert.equal(joined.includes('Every off-site opportunity must be an object'), false)
})

test('a non-array offsiteOpportunities reports missing opportunities instead of crashing', () => {
  const problems = validateBaselineRecord({
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: true,
      sitemapSubmitted: true,
      indexedPageCount: 1,
      impressions: 0,
      clicks: 0,
    },
    offsiteOpportunities: { name: 'A', url: 'https://example.com/a', relevance: 'tools', outreach: 'not-started' },
    linkPolicy: 'earned-only',
  })

  const joined = problems.join('\n')
  assert.ok(joined.includes('At least 3 realistic off-site discovery opportunities'))
  assert.equal(joined.includes('Every off-site opportunity must be an object'), false)
})


test('the CLI parses its arguments', () => {
  const options = parseArguments([
    '--base-url',
    'https://example.com',
    '--json',
    'out.json',
    '--markdown',
    'out.md',
    '--baseline',
    'record.json',
  ])

  assert.equal(options.origin, 'https://example.com')
  assert.equal(options.jsonPath, 'out.json')
  assert.equal(options.markdownPath, 'out.md')
  assert.equal(options.baselinePath, 'record.json')
})

test('a missing baseline file is reported instead of throwing', () => {
  const result = readBaselineRecord(resolve(SCRIPT_DIRECTORY, 'does-not-exist.json'))

  assert.equal(result.record, null)
  assert.equal(result.problems.length, 1)
})

test('baseline paths resolve from the repository root', () => {
  const resolved = resolveBaselinePath('docs/operations/seo-launch-baseline.json')

  assert.ok(resolved.endsWith('docs/operations/seo-launch-baseline.json'))
  assert.equal(resolved.startsWith('/'), true)
  assert.equal(resolveBaselinePath('/tmp/record.json'), '/tmp/record.json')
})

test('an unfinished launch record validates the expected incomplete state', () => {
  const unfinishedRecord = {
    issue: 3072,
    origin: PRODUCTION_ORIGIN,
    recordedAt: '2026-10-19',
    searchConsole: {
      ownershipVerified: false,
      sitemapSubmitted: false,
      indexedPageCount: null,
      impressions: null,
      clicks: null,
    },
    offsiteOpportunities: [
      { name: 'A', url: 'https://example.com/a', relevance: 'self-hosted tools', outreach: 'not-started' },
      { name: 'B', url: 'https://example.com/b', relevance: 'comics community', outreach: 'not-started' },
      { name: 'C', url: 'https://example.com/c', relevance: 'developer directory', outreach: 'not-started' },
    ],
    linkPolicy: 'earned-only',
  }

  const open = validateBaselineRecord(unfinishedRecord)
  assert.ok(open.some((problem) => problem.includes('ownership is not verified')))
  assert.ok(open.some((problem) => problem.includes('sitemap is not recorded as submitted')))
  assert.ok(open.some((problem) => problem.includes('indexedPageCount has not been recorded')))
})
