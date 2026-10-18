/**
 * Generate route-specific HTML files with proper SEO metadata.
 *
 * This addresses issue #3485 where raw HTML served the same title, description,
 * and canonical URL on every route. Instead of maintaining a second full copy
 * of the bootstrap page, the script rewrites only the SEO metadata block inside
 * Vite's own build output. Every generated route file is therefore byte-identical
 * to `frontend/index.html` everywhere except the head metadata, so future fixes
 * to the bootstrap page automatically flow into every route file.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { ROUTE_SEO_TABLE } from '../src/seo/routeSeo.ts'
import { resolveProductionOrigin } from './generate-sitemap.mjs'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const frontendDir = resolve(scriptDirectory, '..')
const buildDir = resolve(frontendDir, '..', 'static', 'react')
const productionOrigin = resolveProductionOrigin(process.env)

/**
 * Escape a value for use in HTML text content or a double-quoted attribute.
 *
 * @param {string} value - Raw title or description text.
 * @returns {string} HTML-safe text.
 */
function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

/**
 * Generate structured data JSON-LD for indexable routes.
 *
 * @returns {string} Compact JSON-LD document.
 */
function generateStructuredData() {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        name: "ComicPile",
        url: productionOrigin,
        description: "ComicPile is a dice-driven reading queue for your comic collection. Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.",
      },
      {
        "@type": "SoftwareApplication",
        name: "ComicPile",
        url: productionOrigin,
        description: "ComicPile is a dice-driven reading queue for your comic collection. Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.",
        applicationCategory: "WebApplication",
        featureList: ["Weighted by your history", "Continuity-aware", "No external dependencies", "Built for the long stack"],
      },
    ],
  })
}

/**
 * Build the route-specific head metadata tags.
 *
 * @param {{pattern: string, title: string, description: string, canonicalPath: string | null, visibility: string}} route - Route SEO entry.
 * @returns {string[]} Metadata tags ready to inject after `<meta charset>`.
 */
function buildRouteHeadTags(route) {
  const canonicalUrl = route.canonicalPath ? `${productionOrigin}${route.canonicalPath}` : null
  const robots = route.visibility === 'public-indexable' ? 'index, follow' : 'noindex, nofollow'
  const ogUrl = canonicalUrl || `${productionOrigin}${route.pattern}`
  const title = escapeHtml(route.title)
  const description = escapeHtml(route.description)

  const tags = [
    `<title>${title}</title>`,
    `<meta name="description" content="${description}" />`,
  ]
  if (canonicalUrl) {
    tags.push(`<link rel="canonical" href="${canonicalUrl}" />`)
  }
  tags.push(`<meta name="robots" content="${robots}" />`)
  tags.push('<meta property="og:type" content="website" />')
  tags.push(`<meta property="og:title" content="${title}" />`)
  tags.push(`<meta property="og:description" content="${description}" />`)
  tags.push(`<meta property="og:url" content="${ogUrl}" />`)
  if (route.visibility === 'public-indexable') {
    tags.push(
      `<script id="comic-pile-structured-data" type="application/ld+json">\n` +
        `      ${generateStructuredData()}\n` +
        `    </script>`,
    )
  }
  return tags
}

/**
 * Remove every SEO metadata tag from the built page so exactly one route-specific
 * set remains after injection.
 *
 * @param {string} builtIndexHtml - Vite's built `index.html` content.
 * @returns {string} HTML without title, description, canonical, robots, Open Graph,
 *   or landing JSON-LD metadata.
 */
function stripRouteSeoMetadata(builtIndexHtml) {
  return builtIndexHtml
    .replace(/<title[^>]*>[\s\S]*?<\/title>/i, '')
    .replace(/<meta\s+name="description"[^>]*>/gi, '')
    .replace(/<link\s+rel="canonical"[^>]*>/gi, '')
    .replace(/<meta\s+name="robots"[^>]*>/gi, '')
    .replace(/<meta\s+property="og:[a-z]+"[^>]*>/gi, '')
    .replace(
      /<script[^>]*id="comic-pile-structured-data"[^>]*>[\s\S]*?<\/script>/gi,
      '',
    )
}

/**
 * Insert route metadata right after the charset declaration in `<head>`.
 *
 * @param {string} strippedHtml - Built HTML with prior metadata removed.
 * @param {string[]} headTags - Route metadata tags.
 * @returns {string} HTML with the route metadata in place.
 */
function insertHeadTags(strippedHtml, headTags) {
  const tags = headTags.join('\n    ')
  const charsetPattern = /<meta\s+charset="[^"]*"\s*\/?>/i
  if (charsetPattern.test(strippedHtml)) {
    return strippedHtml.replace(
      charsetPattern,
      (match) => `${match}\n    ${tags}`,
    )
  }
  return strippedHtml.replace(/<head[^>]*>/i, (match) => `${match}\n    ${tags}`)
}

/**
 * Generate HTML for a specific route by rewriting the built page's metadata.
 *
 * @param {{pattern: string, title: string, description: string, canonicalPath: string | null, visibility: string}} route - Route SEO entry.
 * @param {string} builtIndexHtml - Vite's built `index.html` content to derive the page from.
 * @returns {string} Full HTML document for the route.
 * @throws If no built HTML is supplied; the script only runs after `vite build`.
 */
function generateRouteHtml(route, builtIndexHtml) {
  if (!builtIndexHtml) {
    throw new Error(
      'generateRouteHtml requires the built index.html content; run after `vite build`.',
    )
  }
  return insertHeadTags(stripRouteSeoMetadata(builtIndexHtml), buildRouteHeadTags(route))
}

/**
 * Generate one route HTML file per non-parameterized route from the single
 * built `index.html`.
 */
function main() {
  if (!existsSync(buildDir)) {
    mkdirSync(buildDir, { recursive: true })
  }

  const builtIndexHtmlPath = resolve(buildDir, 'index.html')
  if (!existsSync(builtIndexHtmlPath)) {
    throw new Error(
      `Missing Vite build output at ${builtIndexHtmlPath}; run \`vite build\` before generating route HTML.`,
    )
  }
  const builtIndexHtml = readFileSync(builtIndexHtmlPath, 'utf-8')

  // Generate HTML for each route
  for (const route of ROUTE_SEO_TABLE) {
    // Skip parameterized routes as they can't have static HTML files
    if (route.pattern.includes(':')) {
      continue
    }

    const routePath = route.pattern === '/' ? 'index.html' : `${route.pattern.slice(1)}.html`
    const htmlPath = resolve(buildDir, routePath)

    // Create directory if it doesn't exist
    const htmlDir = dirname(htmlPath)
    if (!existsSync(htmlDir)) {
      mkdirSync(htmlDir, { recursive: true })
    }

    const html = generateRouteHtml(route, builtIndexHtml)
    writeFileSync(htmlPath, html)

    console.log(`✓ Generated ${routePath}`)
  }

  console.log(`✓ Generated route HTML files`)
}

// Export functions for testing
export { generateRouteHtml, generateStructuredData }

// Execute if run directly
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main()
}
