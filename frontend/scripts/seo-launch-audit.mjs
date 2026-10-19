/**
 * Production SEO launch audit for issue #3072.
 *
 * Issue #3072 owns the launch chores that no factory can perform: verifying
 * Google Search Console ownership, submitting the sitemap, inspecting URLs,
 * and recording search metrics all need a human with account access.
 *
 * This module automates the part that can be owned truthfully. It proves that
 * a deployed origin actually honors the canonical indexability policy in
 * `frontend/src/seo/routeSeo.ts`, and it produces the machine-checkable
 * evidence an operator needs for the remaining manual steps:
 *
 * - every intended public URL is crawlable with one stable canonical URL;
 * - every utility and authenticated URL is blocked from indexing;
 * - the served `robots.txt` disallows the private route families and points
 *   at the sitemap;
 * - the served `sitemap.xml` lists exactly the indexable routes.
 *
 * The audit never claims that a manual step happened. It reports what the
 * deployment serves, fails when a private URL is still indexable, and lists
 * the operator steps that remain open.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { ROUTE_SEO_TABLE, indexableRoutes } from '../src/seo/routeSeo.ts'
import { DEFAULT_PRODUCTION_ORIGIN } from './generate-sitemap.mjs'

const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url))
const REPOSITORY_ROOT = resolve(SCRIPT_DIRECTORY, '..', '..')
const DEFAULT_OUTPUT_DIRECTORY = resolve(REPOSITORY_ROOT, 'dogfood-output', 'seo-launch-audit')
const DEFAULT_BASELINE_PATH = resolve(REPOSITORY_ROOT, 'docs', 'operations', 'seo-launch-baseline.json')
const USER_AGENT = 'ComicPile-Seo-Launch-Audit/1.0 (+https://comic-pile.vercel.app)'
const MAX_REDIRECT_HOPS = 5
const BASELINE_ISSUE_NUMBER = 3072
const REQUIRED_LINK_POLICY = 'earned-only'
const MINIMUM_OFFSITE_OPPORTUNITIES = 3
const OFFSITE_OUTREACH_STATES = ['not-started', 'contacted', 'declined', 'published']

export { DEFAULT_BASELINE_PATH, REPOSITORY_ROOT }

/**
 * Build one audit finding.
 *
 * @param {'error'|'warning'} severity - Blocking or advisory severity.
 * @param {string} code - Stable machine-readable finding code.
 * @param {string} message - Human-readable explanation.
 * @param {string} [route] - Route pattern the finding belongs to.
 * @returns {object} The finding record.
 */
function makeFinding(severity, code, message, route) {
  const record = { severity, code, message }
  if (route !== undefined) {
    record.route = route
  }
  return record
}

/**
 * Parse a `robots.txt` document into crawl rules and sitemap references.
 *
 * @param {string} text - Raw `robots.txt` body.
 * @returns {{rules: Array<{type: string, pattern: string}>, sitemapReferences: string[]}} Parsed policy.
 */
export function parseRobotsPolicy(text) {
  const rules = []
  const sitemapReferences = []
  for (const rawLine of String(text ?? '').split('\n')) {
    const line = rawLine.trim()
    if (line.length === 0 || line.startsWith('#')) {
      continue
    }
    const separator = line.indexOf(':')
    if (separator === -1) {
      continue
    }
    const directive = line.slice(0, separator).trim().toLowerCase()
    const value = line.slice(separator + 1).trim()
    if (directive === 'allow' || directive === 'disallow') {
      if (value.length === 0) {
        continue
      }
      rules.push({ type: directive, pattern: value })
      continue
    }
    if (directive === 'sitemap') {
      sitemapReferences.push(value)
    }
  }
  return { rules, sitemapReferences }
}

/**
 * Apply `robots.txt` longest-prefix matching to a path.
 *
 * An equally long `Allow` wins over `Disallow`, which is the rule crawlers use.
 *
 * @param {string} path - Absolute path such as `/queue`.
 * @param {Array<{type: string, pattern: string}>} rules - Parsed crawl rules.
 * @returns {boolean} True when the path is excluded from crawling.
 */
export function isCrawlDisallowed(path, rules) {
  let winner = null
  for (const rule of rules) {
    if (!path.startsWith(rule.pattern)) {
      continue
    }
    if (
      winner === null ||
      rule.pattern.length > winner.pattern.length ||
      (rule.pattern.length === winner.pattern.length && rule.type === 'allow')
    ) {
      winner = rule
    }
  }
  return winner !== null && winner.type === 'disallow'
}

/**
 * Extract the `<loc>` values from a sitemap document.
 *
 * @param {string} xml - Raw sitemap body.
 * @returns {string[]} Every absolute URL listed in the document.
 */
export function parseSitemapLocations(xml) {
  const locations = []
  const pattern = /<loc>\s*([^<]*?)\s*<\/loc>/gi
  for (const match of String(xml ?? '').matchAll(pattern)) {
    const value = (match[1] ?? '').trim()
    if (value.length > 0) {
      locations.push(value)
    }
  }
  return locations
}

/**
 * Collect every attribute of an HTML tag as a lowercase-keyed map.
 *
 * @param {string} tag - Raw tag source, for example `<meta name="robots" ...>`.
 * @returns {Map<string, string>} Attribute names mapped to their values.
 */
function attributesOf(tag) {
  const attributes = new Map()
  const pattern = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
  for (const match of tag.matchAll(pattern)) {
    const name = (match[1] ?? '').toLowerCase()
    const value = match[2] ?? match[3] ?? ''
    if (!attributes.has(name)) {
      attributes.set(name, value)
    }
  }
  return attributes
}

/**
 * Collect every occurrence of one HTML tag in a document.
 *
 * @param {string} html - Raw HTML document.
 * @param {string} tagName - Tag to collect, for example `meta`.
 * @returns {string[]} Raw tag sources in document order.
 */
function collectTags(html, tagName) {
  const pattern = new RegExp(`<${tagName}\\b[^>]*>`, 'gi')
  return Array.from(String(html ?? '').matchAll(pattern), (match) => match[0])
}

/**
 * Read the crawl-relevant signals out of a served HTML document.
 *
 * @param {string} html - Raw HTML document.
 * @returns {{title: string|null, description: string|null, robotsMeta: string|null, canonical: string|null}} Head signals.
 */
export function readHeadSignals(html) {
  const titleMatch = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(String(html ?? ''))
  let description = null
  let robotsMeta = null
  for (const tag of collectTags(html, 'meta')) {
    const attributes = attributesOf(tag)
    const name = attributes.get('name') ?? ''
    if (name === 'description' && description === null) {
      description = attributes.get('content') ?? null
    }
    if (name === 'robots' && robotsMeta === null) {
      robotsMeta = attributes.get('content') ?? null
    }
  }
  let canonical = null
  for (const tag of collectTags(html, 'link')) {
    const attributes = attributesOf(tag)
    if ((attributes.get('rel') ?? '').toLowerCase() === 'canonical' && canonical === null) {
      canonical = attributes.get('href') ?? null
    }
  }
  return {
    title: titleMatch === null ? null : (titleMatch[1] ?? '').trim(),
    description,
    robotsMeta,
    canonical,
  }
}

/**
 * Report whether a robots directive forbids indexing.
 *
 * @param {string|null|undefined} value - Robots meta or `X-Robots-Tag` value.
 * @returns {boolean} True when the directive contains `noindex`.
 */
export function robotsValueBlocksIndexing(value) {
  if (value === null || value === undefined) {
    return false
  }
  return /noindex/i.test(String(value))
}

/**
 * Turn a route pattern into a concrete path for a live request.
 *
 * @param {string} pattern - Route pattern such as `/thread/:id`.
 * @returns {string} A concrete path such as `/thread/1`.
 */
export function routeSamplePath(pattern) {
  const segments = pattern.split('/').map((segment) => {
    if (!segment.startsWith(':')) {
      return segment
    }
    if (segment === ':id') {
      return '1'
    }
    if (segment === ':group') {
      return 'group-1'
    }
    if (segment === ':creatorKey') {
      return 'some-creator'
    }
    return 'sample'
  })
  return segments.join('/')
}

/**
 * Report whether a route pattern contains a parameter segment.
 *
 * @param {string} pattern - Route pattern.
 * @returns {boolean} True when the pattern has a `:param` segment.
 */
export function isParameterizedRoute(pattern) {
  return pattern.split('/').some((segment) => segment.startsWith(':'))
}

/**
 * Evaluate one audited route against the canonical indexability policy.
 *
 * @param {{pattern: string, visibility: string, canonicalPath: string|null}} route - Route table entry.
 * @param {object} context - Observed deployment facts for the route.
 * @param {string} context.origin - Audited origin.
 * @param {string} context.path - Concrete request path.
 * @param {number} context.status - Final HTTP status.
 * @param {{robotsMeta: string|null, canonical: string|null}} context.head - Head signals.
 * @param {string|null} context.headerRobots - `X-Robots-Tag` header value.
 * @param {boolean} context.disallowed - Whether `robots.txt` disallows the path.
 * @param {number} context.redirectCount - Number of redirects that were followed.
 * @returns {object[]} Findings for the route.
 */
export function evaluateRoute(route, context) {
  const findings = []
  const origin = context.origin
  const status = context.status
  const head = context.head
  const headerRobots = context.headerRobots
  const metaNoindex = robotsValueBlocksIndexing(head.robotsMeta)
  const headerNoindex = robotsValueBlocksIndexing(headerRobots)
  const blockedByRobots = context.disallowed

  if (status >= 500) {
    findings.push(
      makeFinding(
        'error',
        'route-server-error',
        `The route answered with HTTP ${status}; a crawlable surface must not serve a server error.`,
        route.pattern,
      ),
    )
  }

  if (route.visibility === 'public-indexable') {
    if (status !== 200) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-not-served',
          `The indexable route answered with HTTP ${status}; it must serve the landing page directly.`,
          route.pattern,
        ),
      )
    }
    if (context.redirectCount > 0) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-redirects',
          `The indexable route answered through ${context.redirectCount} redirect(s); the canonical URL must be served directly.`,
          route.pattern,
        ),
      )
    }
    const expectedCanonical = route.canonicalPath === null ? null : `${origin}${route.canonicalPath}`
    if (head.canonical === null) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-missing-canonical',
          'The indexable route served no canonical link; search engines need one stable canonical URL.',
          route.pattern,
        ),
      )
    } else if (expectedCanonical !== null && head.canonical !== expectedCanonical) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-canonical-mismatch',
          `The canonical link is "${head.canonical}" but the policy expects "${expectedCanonical}".`,
          route.pattern,
        ),
      )
    }
    if (metaNoindex) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-noindex-meta',
          `The indexable route served robots meta "${head.robotsMeta}"; it must stay indexable.`,
          route.pattern,
        ),
      )
    }
    if (headerNoindex) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-noindex-header',
          `The indexable route served "X-Robots-Tag: ${headerRobots}"; it must stay indexable.`,
          route.pattern,
        ),
      )
    }
    if (blockedByRobots) {
      findings.push(
        makeFinding(
          'error',
          'indexable-route-disallowed',
          'The indexable route is disallowed by robots.txt; the crawl target must stay allowed.',
          route.pattern,
        ),
      )
    }
    return findings
  }

  const blockedSomewhere = blockedByRobots || metaNoindex || headerNoindex
  const carriesNoindex = metaNoindex || headerNoindex
  if (!blockedSomewhere) {
    findings.push(
      makeFinding(
        'error',
        'non-indexable-route-indexable',
        'The route is not an allowed crawl target, yet robots.txt allows it and it served no noindex directive; it is still indexable.',
        route.pattern,
      ),
    )
  } else {
    if (!carriesNoindex) {
      findings.push(
        makeFinding(
          'error',
          'non-indexable-route-missing-noindex',
          'The route carries no explicit noindex directive; a URL that is only disallowed in robots.txt can still be indexed from an external link.',
          route.pattern,
        ),
      )
    }
    if (!blockedByRobots) {
      findings.push(
        makeFinding(
          'error',
          'non-indexable-route-not-disallowed',
          'robots.txt does not disallow the route; crawlers must never fetch it.',
          route.pattern,
        ),
      )
    }
  }
  if (status === 404 && !isParameterizedRoute(route.pattern)) {
    findings.push(
      makeFinding(
        'warning',
        'non-indexable-route-not-found',
        'The route answered with HTTP 404; confirm the deployment still serves this public path.',
        route.pattern,
      ),
    )
  }
  if (context.redirectCount > 1) {
    findings.push(
      makeFinding(
        'warning',
        'redirect-chain',
        `The route answered through ${context.redirectCount} redirects; redirect chains weaken crawl signals.`,
        route.pattern,
      ),
    )
  }
  return findings
}

/**
 * Fetch one URL while recording every redirect hop.
 *
 * @param {string} url - Absolute URL to request.
 * @param {Function} fetchImpl - Fetch implementation to use.
 * @returns {Promise<{url: string, status: number, headers: Headers, body: string, redirectCount: number}>} The response.
 */
export async function fetchWithRedirects(url, fetchImpl) {
  let current = url
  let redirectCount = 0
  for (let hop = 0; hop <= MAX_REDIRECT_HOPS; hop += 1) {
    const response = await fetchImpl(current, {
      redirect: 'manual',
      headers: { 'user-agent': USER_AGENT },
    })
    const location = response.headers.get('location')
    if (response.status >= 300 && response.status < 400 && location !== null && location.length > 0) {
      redirectCount += 1
      current = new URL(location, current).toString()
      continue
    }
    return {
      url: current,
      status: response.status,
      headers: response.headers,
      body: await response.text(),
      redirectCount,
    }
  }
  return {
    url: current,
    status: 0,
    headers: new Headers(),
    body: '',
    redirectCount,
  }
}

/**
 * Audit one deployed origin against the canonical indexability policy.
 *
 * @param {object} options - Audit options.
 * @param {string} [options.origin] - Origin to audit, for example `https://comic-pile.vercel.app`.
 * @param {Function} [options.fetchImpl] - Fetch implementation used for every request.
 * @param {Array<object>} [options.routes] - Route table entries to audit.
 * @param {string} [options.generatedAt] - ISO timestamp recorded in the report.
 * @returns {Promise<object>} The audit report.
 */
export async function auditOrigin(options) {
  const origin = options.origin ?? DEFAULT_PRODUCTION_ORIGIN
  const fetchImpl = options.fetchImpl ?? globalThis.fetch
  const routes = options.routes ?? ROUTE_SEO_TABLE
  const generatedAt = options.generatedAt ?? new Date().toISOString()
  const findings = []

  const robotsResponse = await fetchWithRedirects(`${origin}/robots.txt`, fetchImpl)
  const robotsText = robotsResponse.status === 200 ? robotsResponse.body : ''
  const robotsPolicy = parseRobotsPolicy(robotsText)
  if (robotsResponse.status !== 200) {
    findings.push(
      makeFinding(
        'error',
        'robots-missing',
        `robots.txt answered with HTTP ${robotsResponse.status}; crawlers need the crawler policy.`,
      ),
    )
  } else {
    if (!robotsPolicy.sitemapReferences.includes(`${origin}/sitemap.xml`)) {
      findings.push(
        makeFinding(
          'error',
          'robots-sitemap-reference-missing',
          `robots.txt does not advertise "${origin}/sitemap.xml"; the sitemap cannot be discovered by crawlers.`,
        ),
      )
    }
  }

  const sitemapResponse = await fetchWithRedirects(`${origin}/sitemap.xml`, fetchImpl)
  const sitemapText = sitemapResponse.status === 200 ? sitemapResponse.body : ''
  const sitemapLocations = parseSitemapLocations(sitemapText)
  const expectedLocations = indexableRoutes().map(
    (entry) => `${origin}${entry.canonicalPath}`,
  )
  if (sitemapResponse.status !== 200) {
    findings.push(
      makeFinding(
        'error',
        'sitemap-missing',
        `sitemap.xml answered with HTTP ${sitemapResponse.status}; the crawlable routes have no sitemap.`,
      ),
    )
  } else if (sitemapLocations.length === 0) {
    findings.push(
      makeFinding(
        'error',
        'sitemap-not-valid',
        'sitemap.xml served no <loc> entries; the document is not a usable sitemap.',
      ),
    )
  } else {
    for (const expected of expectedLocations) {
      if (!sitemapLocations.includes(expected)) {
        findings.push(
          makeFinding(
            'error',
            'sitemap-missing-url',
            `sitemap.xml does not list the indexable route "${expected}".`,
          ),
        )
      }
    }
    for (const location of sitemapLocations) {
      if (!expectedLocations.includes(location)) {
        findings.push(
          makeFinding(
            'error',
            'sitemap-unexpected-url',
            `sitemap.xml lists "${location}", which is not an indexable route.`,
          ),
        )
      }
    }
  }

  const auditedRoutes = []
  for (const route of routes) {
    const path = routeSamplePath(route.pattern)
    const response = await fetchWithRedirects(`${origin}${path}`, fetchImpl)
    const head = readHeadSignals(response.body)
    const headerRobots = response.headers.get('x-robots-tag')
    const disallowed = isCrawlDisallowed(path, robotsPolicy.rules)
    const routeFindings = evaluateRoute(route, {
      origin,
      path,
      status: response.status,
      head,
      headerRobots,
      disallowed,
      redirectCount: response.redirectCount,
    })
    findings.push(...routeFindings)
    auditedRoutes.push({
      pattern: route.pattern,
      path,
      visibility: route.visibility,
      status: response.status,
      finalUrl: response.url,
      redirectCount: response.redirectCount,
      title: head.title,
      robotsMeta: head.robotsMeta,
      canonical: head.canonical,
      headerRobots,
      disallowed,
      findings: routeFindings,
    })
  }

  const errors = findings.filter((entry) => entry.severity === 'error')
  const warnings = findings.filter((entry) => entry.severity === 'warning')
  return {
    origin,
    generatedAt,
    robots: {
      status: robotsResponse.status,
      sitemapReferences: robotsPolicy.sitemapReferences,
      rules: robotsPolicy.rules,
    },
    sitemap: {
      status: sitemapResponse.status,
      locations: sitemapLocations,
      expectedLocations,
    },
    routes: auditedRoutes,
    findings,
    summary: {
      routesAudited: auditedRoutes.length,
      indexableRoutes: auditedRoutes.filter((entry) => entry.visibility === 'public-indexable').length,
      nonIndexableRoutes: auditedRoutes.filter((entry) => entry.visibility !== 'public-indexable')
        .length,
      errors: errors.length,
      warnings: warnings.length,
    },
  }
}

/**
 * Validate the structured launch baseline record.
 *
 * @param {object} record - Parsed baseline record.
 * @returns {string[]} Problems that still block a complete launch record.
 */
export function validateBaselineRecord(record) {
  const problems = []
  if (record === null || record === undefined) {
    return ['The baseline record is missing.']
  }
  if (record.issue !== BASELINE_ISSUE_NUMBER) {
    problems.push(`The baseline record must reference issue ${BASELINE_ISSUE_NUMBER}.`)
  }
  if (!/^https?:\/\/[^\s]+$/.test(String(record.origin ?? ''))) {
    problems.push('The baseline record must name the audited origin.')
  }
  if (record.recordedAt !== null && record.recordedAt !== undefined) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(record.recordedAt))) {
      problems.push('recordedAt must be an ISO date such as 2026-10-19.')
    }
  }
  if (record.linkPolicy !== REQUIRED_LINK_POLICY) {
    problems.push(
      `linkPolicy must be "${REQUIRED_LINK_POLICY}"; paid, exchanged, or manufactured links are not allowed.`,
    )
  }
  const searchConsole = record.searchConsole
  if (searchConsole === null || searchConsole === undefined) {
    problems.push('The baseline record has no searchConsole section.')
  } else {
    if (searchConsole.ownershipVerified !== true) {
      problems.push('Google Search Console ownership is not verified yet.')
    }
    if (searchConsole.sitemapSubmitted !== true) {
      problems.push('The production sitemap is not recorded as submitted yet.')
    }
    for (const field of ['indexedPageCount', 'impressions', 'clicks']) {
      const value = searchConsole[field]
      if (value === null || value === undefined) {
        problems.push(`searchConsole.${field} has not been recorded yet.`)
        continue
      }
      if (!Number.isInteger(value) || value < 0) {
        problems.push(`searchConsole.${field} must be a non-negative whole number.`)
      }
    }
  }
  const opportunities = record.offsiteOpportunities
  if (!Array.isArray(opportunities) || opportunities.length < MINIMUM_OFFSITE_OPPORTUNITIES) {
    problems.push(
      `At least ${MINIMUM_OFFSITE_OPPORTUNITIES} realistic off-site discovery opportunities must be identified.`,
    )
  } else {
    for (const opportunity of opportunities) {
      const name = opportunity === null || opportunity === undefined ? '' : String(opportunity.name ?? '')
      const url = opportunity === null || opportunity === undefined ? '' : String(opportunity.url ?? '')
      const relevance =
        opportunity === null || opportunity === undefined ? '' : String(opportunity.relevance ?? '')
      if (name.length === 0) {
        problems.push('Every off-site opportunity needs a name.')
      }
      if (!/^https?:\/\/[^\s]+$/.test(url)) {
        problems.push(`The off-site opportunity "${name}" needs an absolute URL.`)
      }
      if (relevance.length === 0) {
        problems.push(`The off-site opportunity "${name}" needs a relevance reason.`)
      }
      if (opportunity.paid === true) {
        problems.push(`The off-site opportunity "${name}" is marked as a paid link.`)
      }
      if (!OFFSITE_OUTREACH_STATES.includes(String(opportunity.outreach ?? ''))) {
        problems.push(
          `The off-site opportunity "${name}" needs an outreach state of ${OFFSITE_OUTREACH_STATES.join(', ')}.`,
        )
      }
    }
  }
  return problems
}

/**
 * List the operator steps that the baseline record has not completed yet.
 *
 * @param {object|null} record - Parsed baseline record.
 * @param {string[]} [readProblems] - Problems found while reading the record.
 * @returns {string[]} Human-readable pending steps.
 */
export function pendingOperatorSteps(record, readProblems = []) {
  if (record === null || record === undefined) {
    return [
      'Create the launch baseline record and verify Google Search Console ownership.',
      'Submit the production sitemap.',
      'Record the baseline index and search metrics.',
    ]
  }
  return [...readProblems, ...validateBaselineRecord(record)]
}

/**
 * Render the audit report as Markdown for the launch evidence record.
 *
 * @param {object} report - Audit report.
 * @param {object|null} [baseline] - Parsed baseline record.
 * @param {string[]} [baselineProblems] - Problems found while reading the record.
 * @returns {string} Markdown report.
 */
export function renderAuditMarkdown(report, baseline, baselineProblems = []) {
  const lines = []
  const verdict = report.summary.errors > 0 ? 'FAIL' : 'PASS'
  lines.push('# ComicPile SEO launch audit')
  lines.push('')
  lines.push(`- Origin: \`${report.origin}\``)
  lines.push(`- Generated: \`${report.generatedAt}\``)
  lines.push(
    `- Verdict: **${verdict}** (${report.summary.errors} error(s), ${report.summary.warnings} warning(s))`,
  )
  lines.push(
    `- Routes audited: ${report.summary.routesAudited} (${report.summary.indexableRoutes} indexable, ${report.summary.nonIndexableRoutes} blocked from indexing)`,
  )
  lines.push('')
  lines.push('## Indexable public URLs')
  lines.push('')
  lines.push('| Route | Path | Status | Canonical | Robots meta | Verdict |')
  lines.push('| --- | --- | --- | --- | --- | --- |')
  for (const route of report.routes) {
    if (route.visibility !== 'public-indexable') {
      continue
    }
    lines.push(
      `| \`${route.pattern}\` | \`${route.path}\` | ${route.status} | ${route.canonical ?? '(none)'} | ${route.robotsMeta ?? '(none)'} | ${routeVerdict(route)} |`,
    )
  }
  lines.push('')
  lines.push('## Utility and authenticated URLs')
  lines.push('')
  lines.push('| Route | Path | Status | robots.txt | noindex signal | Verdict |')
  lines.push('| --- | --- | --- | --- | --- | --- |')
  for (const route of report.routes) {
    if (route.visibility === 'public-indexable') {
      continue
    }
    const noindexSignal = robotsValueBlocksIndexing(route.robotsMeta)
      ? `meta: ${route.robotsMeta}`
      : robotsValueBlocksIndexing(route.headerRobots)
        ? `header: ${route.headerRobots}`
        : '(none)'
    lines.push(
      `| \`${route.pattern}\` | \`${route.path}\` | ${route.status} | ${route.disallowed ? 'disallowed' : 'allowed'} | ${noindexSignal} | ${routeVerdict(route)} |`,
    )
  }
  lines.push('')
  lines.push('## Findings')
  lines.push('')
  if (report.findings.length === 0) {
    lines.push('No findings. The deployment matches the canonical indexability policy.')
  } else {
    for (const entry of report.findings) {
      const location = entry.route === undefined ? '' : ` \`${entry.route}\``
      lines.push(`- **${entry.severity}** \`${entry.code}\`${location} — ${entry.message}`)
    }
  }
  lines.push('')
  lines.push('## Operator steps still open')
  lines.push('')
  const pending = pendingOperatorSteps(baseline, baselineProblems)
  if (pending.length === 0) {
    lines.push('The launch baseline record is complete.')
  } else {
    for (const step of pending) {
      lines.push(`- [ ] ${step}`)
    }
  }
  lines.push('')
  return lines.join('\n')
}

/**
 * Summarize one audited route as a short verdict.
 *
 * @param {object} route - Audited route record.
 * @returns {string} `ok`, `failed`, or `warn`.
 */
function routeVerdict(route) {
  if (route.findings.some((entry) => entry.severity === 'error')) {
    return 'failed'
  }
  if (route.findings.length > 0) {
    return 'warn'
  }
  return 'ok'
}

/**
 * Resolve a baseline record path against the repository root.
 *
 * The audit is a repository-scoped tool, so a relative path always means a
 * path inside the repository regardless of the directory it runs from.
 *
 * @param {string} value - Absolute or repository-relative path.
 * @returns {string} The resolved path.
 */
export function resolveBaselinePath(value) {
  if (value.startsWith('/')) {
    return value
  }
  return resolve(REPOSITORY_ROOT, value)
}

/**
 * Parse command line arguments for the audit CLI.
 *
 * @param {string[]} argv - Raw arguments.
 * @returns {object} Parsed options.
 */
export function parseArguments(argv) {
  const options = {
    origin: DEFAULT_PRODUCTION_ORIGIN,
    jsonPath: null,
    markdownPath: null,
    baselinePath: null,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    const value = argv[index + 1]
    if (argument === '--base-url' && value !== undefined) {
      options.origin = value
      index += 1
      continue
    }
    if (argument === '--json' && value !== undefined) {
      options.jsonPath = value
      index += 1
      continue
    }
    if (argument === '--markdown' && value !== undefined) {
      options.markdownPath = value
      index += 1
      continue
    }
    if (argument === '--baseline' && value !== undefined) {
      options.baselinePath = value
      index += 1
      continue
    }
  }
  return options
}

/**
 * Read and parse a baseline record from disk.
 *
 * @param {string|null} path - Path to the baseline record.
 * @returns {{record: object|null, problems: string[]}} The record and any read problems.
 */
export function readBaselineRecord(path) {
  if (path === null) {
    return { record: null, problems: [] }
  }
  let text
  try {
    text = readFileSync(path, 'utf-8')
  } catch {
    return { record: null, problems: [`The baseline record at "${path}" could not be read.`] }
  }
  try {
    return { record: JSON.parse(text), problems: [] }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    return { record: null, problems: [`The baseline record at "${path}" is not valid JSON: ${reason}`] }
  }
}

/**
 * Write a report artifact to disk.
 *
 * @param {string} path - Destination path.
 * @param {string} content - File content.
 * @returns {string} The path that was written.
 */
function writeArtifact(path, content) {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, content, 'utf-8')
  return path
}

async function main() {
  const options = parseArguments(process.argv.slice(2))
  const baselinePath =
    options.baselinePath === null ? DEFAULT_BASELINE_PATH : resolveBaselinePath(options.baselinePath)
  const baseline = readBaselineRecord(baselinePath)
  const report = await auditOrigin({ origin: options.origin })
  const markdown = renderAuditMarkdown(report, baseline.record, baseline.problems)
  const jsonPath = options.jsonPath ?? resolve(DEFAULT_OUTPUT_DIRECTORY, 'seo-launch-audit.json')
  const markdownPath = options.markdownPath ?? resolve(DEFAULT_OUTPUT_DIRECTORY, 'seo-launch-audit.md')
  writeArtifact(jsonPath, `${JSON.stringify(report, null, 2)}\n`)
  writeArtifact(markdownPath, markdown)
  console.log(
    `SEO launch audit: ${report.summary.errors} error(s), ${report.summary.warnings} warning(s) across ${report.summary.routesAudited} route(s).`,
  )
  console.log(`Origin: ${report.origin}`)
  console.log(`JSON report: ${jsonPath.replace(`${REPOSITORY_ROOT}/`, '')}`)
  console.log(`Markdown report: ${markdownPath.replace(`${REPOSITORY_ROOT}/`, '')}`)
  console.log(`Operator steps still open: ${pendingOperatorSteps(baseline.record, baseline.problems).length}`)
  if (report.summary.errors > 0) {
    process.exitCode = 1
  }
}

const executedPath = process.argv[1]
if (executedPath && executedPath === fileURLToPath(import.meta.url)) {
  await main()
}
