/**
 * Generate route-specific HTML files with proper SEO metadata.
 * This addresses issue #3485 where raw HTML has the same title/description/canonical on every route.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { ROUTE_SEO_TABLE } from '../src/seo/routeSeo.ts'
import { DEFAULT_PRODUCTION_ORIGIN } from './generate-sitemap.mjs'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const frontendDir = resolve(scriptDirectory, '..')
const buildDir = resolve(frontendDir, '..', 'static', 'react')

/**
 * Base HTML template with placeholders for SEO metadata
 */
const BASE_HTML_TEMPLATE = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title><%= title %></title>
    <meta name="description" content="<%= description %>" />
    <% if (canonicalUrl) { %>
    <link rel="canonical" href="<%= canonicalUrl %>" />
    <% } %>
    <% if (robots) { %>
    <meta name="robots" content="<%= robots %>" />
    <% } %>
    <meta property="og:type" content="website" />
    <meta property="og:title" content="<%= ogTitle %>" />
    <meta property="og:description" content="<%= ogDescription %>" />
    <meta property="og:url" content="<%= ogUrl %>" />
    <% if (structuredData) { %>
    <script id="comic-pile-structured-data" type="application/ld+json">
      <%= structuredData %>
    </script>
    <% } %>
    <style>
      #bootstrap-shell {
        position: fixed;
        inset: 0;
        z-index: 9999;
        display: flex;
        min-height: 100vh;
        flex-direction: column;
        justify-content: space-between;
        background: radial-gradient(circle at top, #2b2118 0%, #110e0a 48%, #090806 100%);
        color: #f5f0e8;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      .bootstrap-shell__main {
        width: min(100% - 2rem, 38rem);
        margin: auto;
        padding: 2rem 0 7rem;
        text-align: center;
      }

      .bootstrap-shell__mark {
        display: inline-grid;
        width: 4rem;
        height: 4rem;
        place-items: center;
        border: 1px solid rgba(245, 240, 232, 0.18);
        border-radius: 1rem;
        background: rgba(17, 14, 10, 0.72);
        box-shadow: 0 1.5rem 4rem rgba(0, 0, 0, 0.35);
        font-size: 2rem;
      }

      .bootstrap-shell__title {
        margin: 1rem 0 0.35rem;
        font-size: clamp(1.75rem, 7vw, 2.75rem);
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .bootstrap-shell__status {
        min-height: 3rem;
        margin: 0 auto;
        color: #b8aea1;
        line-height: 1.5;
      }

      .bootstrap-shell__maintainer {
        margin: 1rem auto 0;
        max-width: 30rem;
        color: #b8aea1;
        font-size: 0.8125rem;
        line-height: 1.5;
      }

      .bootstrap-shell__maintainer a {
        color: #d4a35f;
        font-weight: 600;
        text-decoration: none;
      }

      .bootstrap-shell__lede {
        margin: 0.5rem auto 0;
        max-width: 30rem;
        color: #f5f0e8;
        font-size: 1rem;
        font-weight: 600;
        line-height: 1.5;
      }

      .bootstrap-shell__points {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 0.5rem 1.25rem;
        margin: 1rem auto 0;
        padding: 0;
        max-width: 32rem;
        list-style: none;
        color: #b8aea1;
        font-size: 0.8125rem;
        line-height: 1.5;
      }

      .bootstrap-shell__pulse {
        width: 2.5rem;
        height: 0.25rem;
        margin: 1.5rem auto 0;
        overflow: hidden;
        border-radius: 999px;
        background: rgba(245, 240, 232, 0.12);
      }

      .bootstrap-shell__pulse::after {
        display: block;
        width: 50%;
        height: 100%;
        border-radius: inherit;
        background: #d4a35f;
        content: "";
        animation: bootstrap-pulse 1.15s ease-in-out infinite alternate;
      }

      .bootstrap-shell__nav {
        position: fixed;
        right: 0;
        bottom: 0;
        left: 0;
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        min-height: 4rem;
        border-top: 1px solid rgba(245, 240, 232, 0.1);
        background: rgba(17, 14, 10, 0.94);
        backdrop-filter: blur(12px);
      }

      .bootstrap-shell__nav span {
        display: grid;
        place-items: center;
        color: #8f8579;
        font-size: 1.35rem;
      }

      @keyframes bootstrap-pulse {
        from { transform: translateX(-75%); }
        to { transform: translateX(175%); }
      }

      @media (prefers-reduced-motion: reduce) {
        .bootstrap-shell__pulse::after { animation: none; }
      }
    </style>
  </head>
  <body>
    <div id="bootstrap-shell" role="status" aria-live="polite" aria-label="ComicPile is starting">
      <main class="bootstrap-shell__main">
        <div class="bootstrap-shell__mark" aria-hidden="true">📚</div>
        <h1 class="bootstrap-shell__title">ComicPile</h1>
        <div data-prerendered-landing>
          <p class="bootstrap-shell__lede">
            A dice-driven reading queue for your comic collection.
          </p>
          <ul class="bootstrap-shell__points">
            <li>Build your queue of series and issues remaining</li>
            <li>Roll the die to pick your next read</li>
            <li>Read, rate, and keep your place</li>
          </ul>
          <p class="bootstrap-shell__maintainer">
            A personal open-source project maintained by
            <a href="https://github.com/JoshCLWren" target="_blank" rel="noreferrer">Josh</a>
            (JoshCLWren on GitHub).
          </p>
        </div>
        <p class="bootstrap-shell__status" data-bootstrap-status data-state="loading">
          Opening your reading desk and checking your session…
        </p>
        <div class="bootstrap-shell__pulse" aria-hidden="true"></div>
      </main>
      <nav class="bootstrap-shell__nav" aria-label="ComicPile navigation loading">
        <span aria-hidden="true">🎲</span>
        <span aria-hidden="true">📚</span>
        <span aria-hidden="true">📜</span>
        <span aria-hidden="true">🔀</span>
      </nav>
    </div>
    <div id="root"></div>
    <noscript>
      <p style="max-width: 32rem; margin: 2rem auto; text-align: center; line-height: 1.5;">
        ComicPile is a dice-driven reading queue for your comic collection: build your
        stack, roll the die, and read what comes up. It is a personal open-source
        project maintained by
        <a href="https://github.com/JoshCLWren" target="_blank" rel="noreferrer">Josh</a>
        (JoshCLWren on GitHub). The interactive queue needs JavaScript; please enable
        it to sign in and roll.
      </p>
    </noscript>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>`

/**
 * Generate structured data JSON-LD for indexable routes
 */
function generateStructuredData() {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        name: "ComicPile",
        url: DEFAULT_PRODUCTION_ORIGIN,
        description: "ComicPile is a dice-driven reading queue for your comic collection. Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.",
      },
      {
        "@type": "SoftwareApplication",
        name: "ComicPile",
        url: DEFAULT_PRODUCTION_ORIGIN,
        description: "ComicPile is a dice-driven reading queue for your comic collection. Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.",
        applicationCategory: "WebApplication",
        featureList: ["Weighted by your history", "Continuity-aware", "No external dependencies", "Built for the long stack"],
      },
    ],
  })
}

/**
 * Simple template engine for replacing placeholders
 */
function renderTemplate(template, data) {
  return template
    .replace(/<%= title %>/g, data.title || '')
    .replace(/<%= description %>/g, data.description || '')
    .replace(/<%= canonicalUrl %>/g, data.canonicalUrl || '')
    .replace(/<%= robots %>/g, data.robots || '')
    .replace(/<%= ogTitle %>/g, data.ogTitle || '')
    .replace(/<%= ogDescription %>/g, data.ogDescription || '')
    .replace(/<%= ogUrl %>/g, data.ogUrl || '')
    .replace(/<%= structuredData %>/g, data.structuredData || '')
}

/**
 * Generate HTML for a specific route
 */
function extractAssetTags(builtIndexHtml) {
  if (!builtIndexHtml) {
    return ''
  }
  const tags = []
  const stylesheetRegex = /<link[^>]*rel=["']stylesheet["'][^>]*>/gi
  const moduleScriptRegex = /<script[^>]*type=["']module["'][^>]*><\/script>/gi
  for (const match of builtIndexHtml.match(stylesheetRegex) || []) {
    tags.push(match.trim())
  }
  for (const match of builtIndexHtml.match(moduleScriptRegex) || []) {
    tags.push(match.trim())
  }
  return tags.join('\n    ')
}

function generateRouteHtml(route, assetTags = '') {
  const canonicalUrl = route.canonicalPath ? `${DEFAULT_PRODUCTION_ORIGIN}${route.canonicalPath}` : null
  const robots = route.visibility === 'public-indexable' ? 'index, follow' : 'noindex, nofollow'
  const ogUrl = canonicalUrl || `${DEFAULT_PRODUCTION_ORIGIN}${route.pattern}`
  const structuredData = route.visibility === 'public-indexable' ? generateStructuredData() : null
  const assetMarkup = assetTags || '    <script type="module" src="/src/main.tsx"></script>'

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>${route.title}</title>
    <meta name="description" content="${route.description}" />
    ${canonicalUrl ? `<link rel="canonical" href="${canonicalUrl}" />` : ''}
    <meta name="robots" content="${robots}" />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="${route.title}" />
    <meta property="og:description" content="${route.description}" />
    <meta property="og:url" content="${ogUrl}" />
    ${structuredData ? `
    <script id="comic-pile-structured-data" type="application/ld+json">
      ${structuredData}
    </script>` : ''}
    <style>
      #bootstrap-shell {
        position: fixed;
        inset: 0;
        z-index: 9999;
        display: flex;
        min-height: 100vh;
        flex-direction: column;
        justify-content: space-between;
        background: radial-gradient(circle at top, #2b2118 0%, #110e0a 48%, #090806 100%);
        color: #f5f0e8;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      .bootstrap-shell__main {
        width: min(100% - 2rem, 38rem);
        margin: auto;
        padding: 2rem 0 7rem;
        text-align: center;
      }

      .bootstrap-shell__mark {
        display: inline-grid;
        width: 4rem;
        height: 4rem;
        place-items: center;
        border: 1px solid rgba(245, 240, 232, 0.18);
        border-radius: 1rem;
        background: rgba(17, 14, 10, 0.72);
        box-shadow: 0 1.5rem 4rem rgba(0, 0, 0, 0.35);
        font-size: 2rem;
      }

      .bootstrap-shell__title {
        margin: 1rem 0 0.35rem;
        font-size: clamp(1.75rem, 7vw, 2.75rem);
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .bootstrap-shell__status {
        min-height: 3rem;
        margin: 0 auto;
        color: #b8aea1;
        line-height: 1.5;
      }

      .bootstrap-shell__maintainer {
        margin: 1rem auto 0;
        max-width: 30rem;
        color: #b8aea1;
        font-size: 0.8125rem;
        line-height: 1.5;
      }

      .bootstrap-shell__maintainer a {
        color: #d4a35f;
        font-weight: 600;
        text-decoration: none;
      }

      .bootstrap-shell__lede {
        margin: 0.5rem auto 0;
        max-width: 30rem;
        color: #f5f0e8;
        font-size: 1rem;
        font-weight: 600;
        line-height: 1.5;
      }

      .bootstrap-shell__points {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 0.5rem 1.25rem;
        margin: 1rem auto 0;
        padding: 0;
        max-width: 32rem;
        list-style: none;
        color: #b8aea1;
        font-size: 0.8125rem;
        line-height: 1.5;
      }

      .bootstrap-shell__pulse {
        width: 2.5rem;
        height: 0.25rem;
        margin: 1.5rem auto 0;
        overflow: hidden;
        border-radius: 999px;
        background: rgba(245, 240, 232, 0.12);
      }

      .bootstrap-shell__pulse::after {
        display: block;
        width: 50%;
        height: 100%;
        border-radius: inherit;
        background: #d4a35f;
        content: "";
        animation: bootstrap-pulse 1.15s ease-in-out infinite alternate;
      }

      .bootstrap-shell__nav {
        position: fixed;
        right: 0;
        bottom: 0;
        left: 0;
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        min-height: 4rem;
        border-top: 1px solid rgba(245, 240, 232, 0.1);
        background: rgba(17, 14, 10, 0.94);
        backdrop-filter: blur(12px);
      }

      .bootstrap-shell__nav span {
        display: grid;
        place-items: center;
        color: #8f8579;
        font-size: 1.35rem;
      }

      @keyframes bootstrap-pulse {
        from { transform: translateX(-75%); }
        to { transform: translateX(175%); }
      }

      @media (prefers-reduced-motion: reduce) {
        .bootstrap-shell__pulse::after { animation: none; }
      }
    </style>
  </head>
  <body>
    <div id="bootstrap-shell" role="status" aria-live="polite" aria-label="ComicPile is starting">
      <main class="bootstrap-shell__main">
        <div class="bootstrap-shell__mark" aria-hidden="true">📚</div>
        <h1 class="bootstrap-shell__title">ComicPile</h1>
        <div data-prerendered-landing>
          <p class="bootstrap-shell__lede">
            A dice-driven reading queue for your comic collection.
          </p>
          <ul class="bootstrap-shell__points">
            <li>Build your queue of series and issues remaining</li>
            <li>Roll the die to pick your next read</li>
            <li>Read, rate, and keep your place</li>
          </ul>
          <p class="bootstrap-shell__maintainer">
            A personal open-source project maintained by
            <a href="https://github.com/JoshCLWren" target="_blank" rel="noreferrer">Josh</a>
            (JoshCLWren on GitHub).
          </p>
        </div>
        <p class="bootstrap-shell__status" data-bootstrap-status data-state="loading">
          Opening your reading desk and checking your session…
        </p>
        <div class="bootstrap-shell__pulse" aria-hidden="true"></div>
      </main>
      <nav class="bootstrap-shell__nav" aria-label="ComicPile navigation loading">
        <span aria-hidden="true">🎲</span>
        <span aria-hidden="true">📚</span>
        <span aria-hidden="true">📜</span>
        <span aria-hidden="true">🔀</span>
      </nav>
    </div>
    <div id="root"></div>
    <noscript>
      <p style="max-width: 32rem; margin: 2rem auto; text-align: center; line-height: 1.5;">
        ComicPile is a dice-driven reading queue for your comic collection: build your
        stack, roll the die, and read what comes up. It is a personal open-source
        project maintained by
        <a href="https://github.com/JoshCLWren" target="_blank" rel="noreferrer">Josh</a>
        (JoshCLWren on GitHub). The interactive queue needs JavaScript; please enable
        it to sign in and roll.
      </p>
    </noscript>
    ${assetMarkup}
  </body>
</html>`
}

/**
 * Main function to generate all route HTML files
 */
function main() {
  if (!existsSync(buildDir)) {
    mkdirSync(buildDir, { recursive: true })
  }

  // Capture the asset references emitted by Vite's build before we overwrite
  // the generated index.html, so route HTML files bootstrap the real app.
  const builtIndexHtmlPath = resolve(buildDir, 'index.html')
  const builtIndexHtml = existsSync(builtIndexHtmlPath)
    ? readFileSync(builtIndexHtmlPath, 'utf-8')
    : ''
  const assetTags = extractAssetTags(builtIndexHtml)

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

    const html = generateRouteHtml(route, assetTags)
    writeFileSync(htmlPath, html)

    console.log(`✓ Generated ${routePath}`)
  }

  console.log(`✓ Generated route HTML files`)
}

// Export functions for testing
export { generateRouteHtml, generateStructuredData }

// Execute if run directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main()
}