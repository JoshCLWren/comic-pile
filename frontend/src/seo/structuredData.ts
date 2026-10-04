/**
 * JSON-LD structured data for ComicPile's crawlable public surface (issue #3067).
 *
 * Structured data must only make claims that are visible on the page itself.
 * The landing page is the only indexable route, so the WebSite and
 * SoftwareApplication nodes describe exactly what the landing page shows.
 * No FAQPage schema is emitted anywhere: ComicPile ships no visible FAQ.
 */

export const STRUCTURED_DATA_SCRIPT_ID = 'comic-pile-structured-data'
export const BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID = 'comic-pile-breadcrumb-structured-data'

export const SITE_NAME = 'ComicPile'
export const SITE_DESCRIPTION =
  'ComicPile is a dice-driven reading queue for your comic collection. ' +
  'Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.'

/**
 * Feature claims copied from visible landing-page copy. Each string must stay
 * literally present in the rendered landing page so the schema never claims
 * more than the page shows.
 */
export const LANDING_FEATURES: readonly string[] = [
  'Weighted by your history',
  'Continuity-aware',
  'No external dependencies',
  'Built for the long stack',
]

export interface WebSiteNode {
  '@type': 'WebSite'
  name: string
  url: string
  description: string
}

export interface SoftwareApplicationNode {
  '@type': 'SoftwareApplication'
  name: string
  url: string
  description: string
  applicationCategory: string
  featureList: string[]
}

export interface StructuredDataGraph {
  '@context': string
  '@graph': [WebSiteNode, SoftwareApplicationNode]
}

/**
 * Build the landing-page structured data graph for a site URL.
 *
 * @param siteUrl Canonical site URL. Use `window.location.origin` at runtime
 *   and `/` for the static prerendered `index.html`.
 * @returns The WebSite + SoftwareApplication JSON-LD graph.
 */
export function buildLandingStructuredData(siteUrl: string): StructuredDataGraph {
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'WebSite',
        name: SITE_NAME,
        url: siteUrl,
        description: SITE_DESCRIPTION,
      },
      {
        '@type': 'SoftwareApplication',
        name: SITE_NAME,
        url: siteUrl,
        description: SITE_DESCRIPTION,
        applicationCategory: 'WebApplication',
        featureList: [...LANDING_FEATURES],
      },
    ],
  }
}

/**
 * Idempotently upsert a JSON-LD script tag by id so repeated renders never
 * duplicate the node and identical content never forces a DOM write.
 *
 * @param scriptId Stable id for the script tag.
 * @param data Structured data payload; serialized with JSON.stringify.
 */
export function upsertStructuredDataScript<T>(scriptId: string, data: T): void {
  const selector = `script#${scriptId}`
  const content = JSON.stringify(data)
  const existing = document.head.querySelector<HTMLScriptElement>(selector)
  if (existing) {
    if (existing.textContent === content) {
      return
    }
    existing.textContent = content
    return
  }
  const tag = document.createElement('script')
  tag.id = scriptId
  tag.type = 'application/ld+json'
  tag.textContent = content
  document.head.appendChild(tag)
}

/**
 * Remove a managed JSON-LD script tag. Used when leaving an indexable route
 * or unmounting a breadcrumb trail so stale schema never survives.
 *
 * @param scriptId Stable id of the script tag to remove.
 */
export function removeStructuredDataScript(scriptId: string): void {
  document.head.querySelectorAll(`script#${scriptId}`).forEach(tag => tag.remove())
}
