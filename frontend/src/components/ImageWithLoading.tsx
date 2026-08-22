import { useState, useEffect } from 'react'
import LoadingSpinner from './LoadingSpinner'

interface ImageWithLoadingProps {
  src: string
  alt?: string
  className?: string
  loading?: 'eager' | 'lazy'
  width?: number | string
  height?: number | string
  onError?: () => void
}

/**
 * Image component with loading state handling.
 *
 * Reserves the final image footprint with a single wrapper element and
 * overlays an animated spinner on top of it while the image loads, so the
 * loading indicator never adds extra layout space or shifts surrounding
 * content when the image arrives.
 */
export default function ImageWithLoading({
  src,
  alt = '',
  className = '',
  loading = 'lazy',
  width,
  height,
  onError,
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
        <div className="absolute inset-0 flex items-center justify-center">
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
        onLoad={() => setIsLoaded(true)}
        onError={() => {
          setHasError(true)
          setIsLoaded(true)
          onError?.()
        }}
      />
    </div>
  )
}
