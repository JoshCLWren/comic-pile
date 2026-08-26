const IMAGE_OPTIMIZATION_PATH = '/api/v1/images/optimize'

export const IMAGE_WIDTH_VARIANTS = [96, 240, 480, 720] as const

export type ImageWidthVariant = (typeof IMAGE_WIDTH_VARIANTS)[number]

/**
 * Convert a canonical external image URL into the ComicPile-owned URL the
 * browser should request.
 *
 * External http(s) sources are routed through the edge-cacheable
 * `/api/v1/images/optimize` endpoint, which allowlists upstream hosts and
 * serves resized WebP variants. Local, data, and blob URLs are returned
 * unchanged so the optimizer never sees non-remote sources.
 *
 * Canonical source URLs are never rewritten at rest; this transformation is a
 * render-time delivery concern only.
 */
export function optimizedImageUrl(
  sourceUrl: string | null | undefined,
  width: ImageWidthVariant | number,
): string | null {
  if (!sourceUrl) return null

  if (/^(data|blob):/i.test(sourceUrl)) return sourceUrl

  try {
    const parsed = new URL(sourceUrl)
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return sourceUrl

    const params = new URLSearchParams({
      url: parsed.href,
      width: String(width),
    })
    return `${IMAGE_OPTIMIZATION_PATH}?${params.toString()}`
  } catch {
    // Relative or otherwise unparseable source: pass through untouched.
    return sourceUrl
  }
}

/**
 * Build a `srcset` attribute value covering the given width variants for one
 * canonical external image URL.
 *
 * Returns null when there is no usable source or fewer than one variant, so
 * callers can omit the attribute entirely instead of rendering an empty hint.
 */
export function optimizedImageSrcSet(
  sourceUrl: string | null | undefined,
  widths: readonly (ImageWidthVariant | number)[] = IMAGE_WIDTH_VARIANTS,
): string | null {
  if (!sourceUrl) return null

  const entries = widths.map((width) => {
    const url = optimizedImageUrl(sourceUrl, width)
    return url ? `${url} ${width}w` : null
  }).filter((entry): entry is string => entry !== null)

  return entries.length > 0 ? entries.join(', ') : null
}
