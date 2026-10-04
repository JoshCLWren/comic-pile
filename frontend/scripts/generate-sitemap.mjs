/**
 * Sitemap generation script for ComicPile.
 *
 * Reads the canonical route indexability table from routeSeo.ts and generates
 * a sitemap.xml file containing only public-indexable routes with canonical
 * absolute URLs for the production origin. Also generates robots.txt with
 * the correct sitemap URL.
 *
 * Runs as a Vite build hook to keep the sitemap synchronized with route changes.
 */

import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { writeFileSync, mkdirSync, existsSync } from 'node:fs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Route indexability classification from routeSeo.ts.
 * This must stay in sync with frontend/src/seo/routeSeo.ts.
 */
const ROUTE_SEO_TABLE = [
  { pattern: '/', visibility: 'public-indexable', canonicalPath: '/', title: 'ComicPile — A dice-driven reading queue for your comic collection', description: 'ComicPile is a dice-driven reading queue for your comic collection. Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.' },
  { pattern: '/login', visibility: 'public-noindex', canonicalPath: null, title: 'Sign in — Comic Pile', description: 'ComicPile account utility page. This page is not indexed by search engines.' },
  { pattern: '/register', visibility: 'public-noindex', canonicalPath: null, title: 'Create your queue — Comic Pile', description: 'ComicPile account utility page. This page is not indexed by search engines.' },
  { pattern: '/forgot-password', visibility: 'public-noindex', canonicalPath: null, title: 'Forgot password — Comic Pile', description: 'ComicPile account utility page. This page is not indexed by search engines.' },
  { pattern: '/reset-password', visibility: 'public-noindex', canonicalPath: null, title: 'Reset password — Comic Pile', description: 'ComicPile account utility page. This page is not indexed by search engines.' },
  { pattern: '/demo', visibility: 'public-noindex', canonicalPath: null, title: 'Try the demo — Comic Pile', description: 'ComicPile account utility page. This page is not indexed by search engines.' },
  { pattern: '/rate', visibility: 'public-noindex', canonicalPath: null, title: 'Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/analytics', visibility: 'public-noindex', canonicalPath: null, title: 'Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/help', visibility: 'public-noindex', canonicalPath: null, title: 'Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/queue', visibility: 'private', canonicalPath: null, title: 'Queue — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/thread/:id', visibility: 'private', canonicalPath: null, title: 'Thread — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/creators', visibility: 'private', canonicalPath: null, title: 'Creators — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/creators/:creatorKey', visibility: 'private', canonicalPath: null, title: 'Creator — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/history', visibility: 'private', canonicalPath: null, title: 'History — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/sessions/:id', visibility: 'private', canonicalPath: null, title: 'Session — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/crossovers', visibility: 'private', canonicalPath: null, title: 'Crossovers — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/crossovers/:group', visibility: 'private', canonicalPath: null, title: 'Crossover — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/continuity-plans', visibility: 'private', canonicalPath: null, title: "Continuity plans — Comic Pile", description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/continuity-plans/new', visibility: 'private', canonicalPath: null, title: 'New continuity plan — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/continuity-plans/:id', visibility: 'private', canonicalPath: null, title: 'Continuity plan — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/whats-new', visibility: 'private', canonicalPath: null, title: "What's new — Comic Pile", description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/glossary', visibility: 'private', canonicalPath: null, title: 'Glossary — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
  { pattern: '/identity-inbox', visibility: 'private', canonicalPath: null, title: 'Identity inbox — Comic Pile', description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.' },
]

/**
 * Get the production origin from environment.
 * Must be set via VITE_PRODUCTION_ORIGIN at build time.
 */
function getProductionOrigin() {
  const origin = process.env.VITE_PRODUCTION_ORIGIN
  if (!origin) {
    throw new Error(
      'VITE_PRODUCTION_ORIGIN environment variable is required for sitemap generation. ' +
      'Set it to your production origin (e.g., https://comicpile.example.com).'
    )
  }
  return origin.replace(/\/+$/, '') // Remove trailing slash
}

/**
 * Generate sitemap.xml content from indexable routes.
 */
function generateSitemap(productionOrigin) {
  const indexableRoutes = ROUTE_SEO_TABLE.filter(entry => entry.visibility === 'public-indexable')
  
  if (indexableRoutes.length === 0) {
    throw new Error('No public-indexable routes found in ROUTE_SEO_TABLE')
  }

  const urls = indexableRoutes.map(entry => {
    const canonicalPath = entry.canonicalPath
    if (!canonicalPath) {
      throw new Error(`Indexable route ${entry.pattern} has no canonicalPath`)
    }
    const url = `${productionOrigin}${canonicalPath}`
    return `  <url>\n    <loc>${escapeXml(url)}</loc>\n  </url>`
  }).join('\n')

  const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`

  return sitemap
}

/**
 * Generate robots.txt content with the correct sitemap URL.
 */
function generateRobotsTxt(productionOrigin) {
  const sitemapUrl = `${productionOrigin}/sitemap.xml`
  
  return `# ComicPile crawler policy (issue #3065).
#
# Only the public landing page is indexable. Crawlers match the longest
# (most specific) rule, so the Disallow lines below win over \`Allow: /\`
# for utility, auth, demo, and authenticated routes while \`/\` stays allowed.
# Hashed JS/CSS under /assets/ and /static/ must stay allowed or crawlers
# cannot render the landing page.
User-agent: *
Allow: /
Allow: /assets/
Allow: /static/
Allow: /vite.svg
Allow: /favicon.svg
Disallow: /login
Disallow: /register
Disallow: /forgot-password
Disallow: /reset-password
Disallow: /demo
Disallow: /rate
Disallow: /analytics
Disallow: /help
Disallow: /queue
Disallow: /thread/
Disallow: /creators
Disallow: /history
Disallow: /sessions/
Disallow: /crossovers
Disallow: /continuity-plans
Disallow: /whats-new
Disallow: /glossary
Disallow: /identity-inbox
Disallow: /api/
Disallow: /debug/

Sitemap: ${sitemapUrl}
`
}

/**
 * Escape XML special characters.
 */
function escapeXml(str) {
  return str
    .replace(/&/g, '&')
    .replace(/</g, '<')
    .replace(/>/g, '>')
    .replace(/"/g, '"')
    .replace(/'/g, '&apos;')
}

/**
 * Main generation function.
 */
function main() {
  try {
    const productionOrigin = getProductionOrigin()
    const sitemap = generateSitemap(productionOrigin)
    const robotsTxt = generateRobotsTxt(productionOrigin)

    // Output to build directory (../static/react from frontend root)
    const outDir = resolve(__dirname, '..', '..', 'static', 'react')
    if (!existsSync(outDir)) {
      mkdirSync(outDir, { recursive: true })
    }

    const sitemapPath = resolve(outDir, 'sitemap.xml')
    const robotsPath = resolve(outDir, 'robots.txt')
    
    writeFileSync(sitemapPath, sitemap, 'utf-8')
    writeFileSync(robotsPath, robotsTxt, 'utf-8')

    console.log(`✓ Generated sitemap.xml at ${sitemapPath}`)
    console.log(`✓ Generated robots.txt at ${robotsPath}`)
    console.log(`  Production origin: ${productionOrigin}`)
    console.log(`  Indexable routes: ${ROUTE_SEO_TABLE.filter(e => e.visibility === 'public-indexable').length}`)
  } catch (error) {
    console.error('✗ Sitemap generation failed:', error instanceof Error ? error.message : String(error))
    process.exit(1)
  }
}

main()