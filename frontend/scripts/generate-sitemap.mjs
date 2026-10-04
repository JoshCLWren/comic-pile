/**
 * Sitemap and robots.txt generation for ComicPile builds (issue #3066).
 *
 * The canonical route indexability table lives in `frontend/src/seo/routeSeo.ts`
 * and the canonical crawler policy lives in `frontend/public/robots.txt`.
 * Neither is duplicated here: this module derives both build artifacts from
 * those sources so a route or policy change can never drift away from what is
 * deployed. It runs as a Vite `closeBundle` hook (see `frontend/vite.config.ts`).
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { indexableRoutes } from '../src/seo/routeSeo.ts'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))

/** Version-controlled crawler policy that becomes the built `robots.txt`. */
export const SOURCE_ROBOTS_PATH = resolve(scriptDirectory, '..', 'public', 'robots.txt')

/** Default build output directory, matching `build.outDir` in `vite.config.ts`. */
export const DEFAULT_OUT_DIR = resolve(scriptDirectory, '..', '..', 'static', 'react')

/**
 * Canonical production origin used when the build does not override it.
 * Must stay aligned with `PRODUCTION_ORIGIN` in `app/main.py`.
 */
export const DEFAULT_PRODUCTION_ORIGIN = 'https://comic-pile.vercel.app'

/**
 * Resolve the absolute origin used for every generated URL.
 *
 * `VITE_PRODUCTION_ORIGIN` overrides the canonical production origin so a
 * deployment on another host can emit its own absolute URLs. An unset variable
 * falls back to the canonical origin instead of failing the build, because
 * every developer build, CI job, and container build runs without it.
 *
 * @param env - Environment variables to read.
 * @returns The origin with no trailing slash and no path.
 * @throws If the override is set but is not an absolute HTTP(S) origin.
 */
export function resolveProductionOrigin(env) {
  const raw = env.VITE_PRODUCTION_ORIGIN
  if (raw === undefined || raw.trim() === '') {
    return DEFAULT_PRODUCTION_ORIGIN
  }

  let parsed
  try {
    parsed = new URL(raw.trim())
  } catch {
    throw new Error(
      `VITE_PRODUCTION_ORIGIN must be an absolute URL, received "${raw}". ` +
      'Example: https://comic-pile.vercel.app',
    )
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error(`VITE_PRODUCTION_ORIGIN must be an HTTP(S) URL, received "${raw}".`)
  }
  if (parsed.pathname !== '/' || parsed.search !== '' || parsed.hash !== '') {
    throw new Error(
      `VITE_PRODUCTION_ORIGIN must be an origin only, received "${raw}". ` +
      'Drop the path, query, and fragment.',
    )
  }
  return parsed.origin
}

/**
 * Escape a string so it is safe to embed in XML text.
 *
 * @param value - Raw text.
 * @returns Text with every XML special character replaced by an entity.
 */
export function escapeXml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

/**
 * Render `sitemap.xml` for the given indexable routes.
 *
 * @param entries - Canonical route entries with `visibility: 'public-indexable'`.
 * @param productionOrigin - Absolute origin, e.g. `https://comic-pile.vercel.app`.
 * @returns Sitemap XML text ending in one newline.
 * @throws If there are no indexable routes or an entry lacks a canonical path.
 */
export function generateSitemapXml(entries, productionOrigin) {
  if (entries.length === 0) {
    throw new Error('No public-indexable routes found in the canonical route table')
  }

  const urlBlocks = entries.map((entry) => {
    const canonicalPath = entry.canonicalPath
    if (!canonicalPath) {
      throw new Error(`Indexable route ${entry.pattern} has no canonicalPath`)
    }
    const location = escapeXml(`${productionOrigin}${canonicalPath}`)
    return `  <url>\n    <loc>${location}</loc>\n  </url>`
  })

  return `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    `${urlBlocks.join('\n')}\n` +
    `</urlset>\n`
}

/**
 * Render `robots.txt` by rewriting only the `Sitemap:` origin of the policy source.
 *
 * Every other line is passed through untouched, so the crawler rules in
 * `frontend/public/robots.txt` stay the single source of truth. When the
 * resolved origin matches the one already in the source, the result is
 * byte-identical to it.
 *
 * @param sourceRobotsTxt - Contents of `frontend/public/robots.txt`.
 * @param productionOrigin - Absolute origin for the sitemap reference.
 * @returns Complete `robots.txt` text.
 */
export function generateRobotsTxt(sourceRobotsTxt, productionOrigin) {
  const sitemapLine = `Sitemap: ${productionOrigin}/sitemap.xml`
  if (!/^Sitemap: \S+$/m.test(sourceRobotsTxt)) {
    return `${sourceRobotsTxt.trimEnd()}\n\n${sitemapLine}\n`
  }
  return sourceRobotsTxt.replace(/^Sitemap: \S+$/m, sitemapLine)
}

/**
 * Generate `sitemap.xml` and `robots.txt` from the canonical sources.
 *
 * @param outDir - Directory that receives both artifacts.
 * @param productionOrigin - Absolute origin used for every generated URL.
 * @returns Paths of the written artifacts and the number of sitemap URLs.
 * @throws If the policy source is missing or generation fails.
 */
export function writeArtifacts(outDir, productionOrigin) {
  const entries = indexableRoutes()
  const sitemapXml = generateSitemapXml(entries, productionOrigin)
  const sourceRobotsTxt = readFileSync(SOURCE_ROBOTS_PATH, 'utf-8')
  const robotsTxt = generateRobotsTxt(sourceRobotsTxt, productionOrigin)

  if (!existsSync(outDir)) {
    mkdirSync(outDir, { recursive: true })
  }

  const sitemapPath = resolve(outDir, 'sitemap.xml')
  const robotsPath = resolve(outDir, 'robots.txt')
  writeFileSync(sitemapPath, sitemapXml, 'utf-8')
  writeFileSync(robotsPath, robotsTxt, 'utf-8')

  return { sitemapPath, robotsPath, urlCount: entries.length }
}

function main() {
  const productionOrigin = resolveProductionOrigin(process.env)
  const result = writeArtifacts(DEFAULT_OUT_DIR, productionOrigin)

  console.log(`✓ Generated sitemap.xml at ${result.sitemapPath}`)
  console.log(`✓ Generated robots.txt at ${result.robotsPath}`)
  console.log(`  Production origin: ${productionOrigin}`)
  console.log(`  Indexable URLs: ${result.urlCount}`)
}

const executedPath = process.argv[1]
if (executedPath && executedPath === fileURLToPath(import.meta.url)) {
  try {
    main()
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    console.error('✗ Sitemap generation failed:', reason)
    process.exit(1)
  }
}
