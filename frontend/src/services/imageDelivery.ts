const IMAGE_OPTIMIZATION_PATH = '/api/v1/images/optimize'

export const IMAGE_WIDTH_VARIANTS = [96, 240, 480, 720] as const

export type ImageWidthVariant = (typeof IMAGE_WIDTH_VARIANTS)[number]

export type ImageFormat = 'webp' | 'avif'

interface ImageUrlOptions {
  format?: ImageFormat
}

/**
 * Convert a canonical external image URL into the ComicPile-owned URL the
 * browser should request.
 *
 * External http(s) sources are routed through the edge-cacheable
 * `/api/v1/images/optimize` endpoint, which allowlists upstream hosts and
 * serves resized modern-format variants (WebP by default; AVIF on request when
 * the runtime encoder is available, otherwise WebP). Local, data, and blob URLs
 * are returned unchanged so the optimizer never sees non-remote sources.
 *
 * Canonical source URLs are never rewritten at rest; this transformation is a
 * render-time delivery concern only.
 */
export function optimizedImageUrl(
  sourceUrl: string | null | undefined,
  width: ImageWidthVariant | number,
  options?: ImageUrlOptions,
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
    if (options?.format) {
      params.set('format', options.format)
    }
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
 *
 * @param sourceUrl - Canonical external image URL.
 * @param widths - Width variants; defaults to the standard 96/240/480/720 buckets.
 * @param options.withFormats - When true, emit a `type="image/webp"` and a
 *   `type="image/avif"` candidate per width so AVIF-capable browsers pick the
 *   smaller AVIF variant. The endpoint serves WebP for an AVIF candidate when
 *   the runtime has no AVIF encoder, so the `src` fallback stays valid either
 *   way. Sources the optimizer does not rewrite emit only their single URL.
 */
export function optimizedImageSrcSet(
  sourceUrl: string | null | undefined,
  widths: readonly (ImageWidthVariant | number)[] = IMAGE_WIDTH_VARIANTS,
  options?: { withFormats?: boolean },
): string | null {
  if (!sourceUrl) return null

  const entries: string[] = []
  widths.forEach((width) => {
    const webp = optimizedImageUrl(sourceUrl, width)
    if (!webp) return
    if (!options?.withFormats) {
      entries.push(`${webp} ${width}w`)
      return
    }
    const avif = optimizedImageUrl(sourceUrl, width, { format: 'avif' })
    if (!avif || avif === webp) {
      entries.push(`${webp} ${width}w`)
      return
    }
    entries.push(`${webp} type="image/webp" ${width}w`)
    entries.push(`${avif} type="image/avif" ${width}w`)
  })

  return entries.length > 0 ? entries.join(', ') : null
}
