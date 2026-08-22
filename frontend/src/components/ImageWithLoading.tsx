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
 * Image component with loading state handling
 * Shows a spinner while the image is loading, then displays the image
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
    <>
      {!isLoaded && !hasError && (
        <div className={className}>
<div className="relative w-full h-full flex items-center justify-center">
             <LoadingSpinner size="sm" />
             {!width && !height && (
               <div className="w-16 h-24 bg-stone-900/50 rounded" />
             )}
             {width && height && (
               <div className={`w-[${width}] h-[${height}] bg-stone-900/50 rounded`} />
             )}
           </div>
        </div>
      )}
      <img
        src={src}
        alt={alt}
        loading={loading}
        className={`transition-opacity duration-300 ${isLoaded && !hasError ? 'opacity-100' : 'opacity-0'} ${hasError ? 'hidden' : ''}`}
        width={width}
        height={height}
        onLoad={() => setIsLoaded(true)}
        onError={() => {
          setHasError(true)
          setIsLoaded(true)
          onError?.()
        }}
      />
    </>
  )
}