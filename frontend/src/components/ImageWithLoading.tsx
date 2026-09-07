import { useState, useEffect } from 'react'
import LoadingSpinner from './LoadingSpinner'

interface ImageWithLoadingProps {
  src: string
  alt?: string
  className?: string
  loading?: 'eager' | 'lazy'
  width?: number | string
  height?: number | string
  srcSet?: string
  sizes?: string
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
 */
export default function ImageWithLoading({
  src,
  alt = '',
  className = '',
  loading = 'lazy',
  width,
  height,
  srcSet,
  sizes,
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

  return (
    <div className={`relative ${className}`}>
      {!isLoaded && !hasError && (
        <div
          className={`absolute inset-0 flex items-center justify-center ${placeholderClassName ?? ''}`}
        >
          <LoadingSpinner size="sm" message="" />
        </div>
      )}
      <img
        src={src}
        alt={alt}
        loading={loading}
        className={`${className} transition-opacity duration-300 ${isLoaded && !hasError ? 'opacity-100' : 'opacity-0'} ${hasError ? 'hidden' : ''}`}
        width={width}
        height={height}
        srcSet={srcSet}
        sizes={sizes}
        onLoad={(event) => {
          setIsLoaded(true)
          onLoad?.(event.currentTarget)
        }}
        onError={() => {
          setHasError(true)
          setIsLoaded(true)
          onError?.()
        }}
      />
    </div>
  )
}
