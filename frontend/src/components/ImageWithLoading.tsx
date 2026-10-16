import { useState, useEffect } from 'react'
import LoadingSpinner from './LoadingSpinner'

export interface ImageSource {
  /** `srcset` for this source variant (e.g. a WebP or AVIF transform). */
  srcSet: string
  /** MIME type of the variant, e.g. `image/webp` or `image/avif`. */
  type: string
  /** Optional media condition for the source. */
  media?: string
  /** Optional sizes attribute for the source. */
  sizes?: string
}

interface ImageWithLoadingProps {
  /** Accessibility label for the image. Required so every caller makes an
   *  explicit decision: meaningful alt text, or `alt=""` for decorative. */
  alt: string
  src: string
  className?: string
  loading?: 'eager' | 'lazy'
  width?: number | string
  height?: number | string
  srcSet?: string
  sizes?: string
  /** Modern `<picture>` source variants (WebP/AVIF). Only used where the
   *  asset pipeline controls the source and can safely transform it. */
  sources?: ImageSource[]
  onError?: () => void
  placeholderClassName?: string
  onLoad?: (img: HTMLImageElement) => void
}

/**
 * Image component with loading state handling.
 *
 * Reserves the final image footprint with a single wrapper element and
 * overlays a loading treatment on top of it while the image loads, so the
 * loading indicator never adds extra layout space or shifts surrounding
 * content when the image arrives.
 *
 * ``placeholderClassName`` lets callers fill the reserved footprint with a
 * themed loading surface (for example ``animate-pulse``) so the loading state
 * occupies the same space as the final image instead of flashing a disjoint
 * background. ``onLoad`` reports the loaded image element so callers can react
 * to its intrinsic dimensions.
 *
 * Accessibility: ``alt`` is required. Pass a concise contextual label for
 * meaningful content images, or ``alt=""`` for genuinely decorative/redundant
 * images. There is no silent empty-alt default.
 *
 * Modern formats: pass ``sources`` (WebP/AVIF) to render a `<picture>` so the
 * browser selects the smallest supported variant without transforming the
 * source at runtime. Intrinsic ``width``/``height`` reserve the aspect ratio
 * up front to prevent image-driven CLS, and ``loading`` defaults to ``lazy``
 * (use ``eager`` only for the hero/LCP image).
 */
export default function ImageWithLoading({
  src,
  alt,
  className = '',
  loading = 'lazy',
  width,
  height,
  srcSet,
  sizes,
  sources,
  onError,
  placeholderClassName,
  onLoad,
}: ImageWithLoadingProps) {
  const [isLoaded, setIsLoaded] = useState(false)
  const [hasError, setHasError] = useState(false)

  useEffect(() => {
    // Reset state when src changes
    setIsLoaded(false)
    setHasError(false)
  }, [src])

  const imgProps = {
    src,
    alt,
    loading,
    width,
    height,
    srcSet,
    sizes,
    className: `${className} transition-opacity duration-300 ${isLoaded && !hasError ? 'opacity-100' : 'opacity-0'} ${hasError ? 'hidden' : ''}`,
    onLoad: (event: React.SyntheticEvent<HTMLImageElement>) => {
      setIsLoaded(true)
      onLoad?.(event.currentTarget)
    },
    onError: () => {
      setHasError(true)
      setIsLoaded(true)
      onError?.()
    },
  }

  return (
    <div className={`relative ${className}`}>
      {!isLoaded && !hasError && (
        <div
          className={`absolute inset-0 flex items-center justify-center ${placeholderClassName ?? ''}`}
        >
          <LoadingSpinner size="sm" message="" />
        </div>
      )}
      {sources && sources.length > 0 ? (
        <picture>
          {sources.map((source, index) => (
            <source
              key={index}
              srcSet={source.srcSet}
              type={source.type}
              media={source.media}
              sizes={source.sizes}
            />
          ))}
          <img {...imgProps} />
        </picture>
      ) : (
        <img {...imgProps} />
      )}
    </div>
  )
}
