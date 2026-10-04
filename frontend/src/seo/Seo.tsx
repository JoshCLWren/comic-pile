import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { matchRouteSeo } from './routeSeo'
import {
  buildLandingStructuredData,
  removeStructuredDataScript,
  STRUCTURED_DATA_SCRIPT_ID,
  upsertStructuredDataScript,
} from './structuredData'

function upsertMetaTag(name: string, content: string): void {
  const selector = `meta[name="${name}"]`
  let tag = document.head.querySelector<HTMLMetaElement>(selector)
  if (!tag) {
    tag = document.createElement('meta')
    tag.setAttribute('name', name)
    document.head.appendChild(tag)
  }
  tag.setAttribute('content', content)
}

/**
 * Keep exactly one canonical link for indexable routes and none otherwise.
 * Extra canonical tags (e.g. left by a previous route) are removed so the
 * "one stable canonical URL" acceptance criterion holds across navigation.
 */
function syncCanonicalLink(canonicalPath: string | null): void {
  const existing = Array.from(document.head.querySelectorAll('link[rel="canonical"]'))
  if (canonicalPath === null) {
    existing.forEach(tag => tag.remove())
    return
  }
  const href = `${window.location.origin}${canonicalPath}`
  const [first, ...rest] = existing
  rest.forEach(tag => tag.remove())
  if (first instanceof HTMLLinkElement) {
    first.setAttribute('href', href)
    return
  }
  if (first) {
    first.remove()
  }
  const link = document.createElement('link')
  link.setAttribute('rel', 'canonical')
  link.setAttribute('href', href)
  document.head.appendChild(link)
}

/**
 * Applies the canonical route indexability table to `document.head` on every
 * navigation. Indexable public pages emit one stable canonical URL;
 * utility and private routes emit `noindex, nofollow` and no canonical.
 * Pure head side effect — it renders nothing and never touches app routing.
 */
export default function Seo() {
  const location = useLocation()

  useEffect(() => {
    const entry = matchRouteSeo(location.pathname)
    document.title = entry.title
    upsertMetaTag('description', entry.description)
    upsertMetaTag(
      'robots',
      entry.visibility === 'public-indexable' ? 'index, follow' : 'noindex, nofollow',
    )
    syncCanonicalLink(entry.canonicalPath)
    if (entry.visibility === 'public-indexable') {
      upsertStructuredDataScript(
        STRUCTURED_DATA_SCRIPT_ID,
        buildLandingStructuredData(window.location.origin),
      )
    } else {
      removeStructuredDataScript(STRUCTURED_DATA_SCRIPT_ID)
    }
  }, [location.pathname])

  return null
}
