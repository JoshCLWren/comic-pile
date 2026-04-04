type LoadingSpinnerSize = 'sm' | 'md' | 'lg'

interface LoadingSpinnerProps {
  message?: string
  fullScreen?: boolean
  size?: LoadingSpinnerSize
}

export default function LoadingSpinner({
  message = 'Loading...',
  fullScreen = false,
  size = 'md',
}: LoadingSpinnerProps) {
  const sizeClasses: Record<LoadingSpinnerSize, string> = {
    sm: 'w-4 h-4 border-2',
    md: 'w-6 h-6 border-2',
    lg: 'w-8 h-8 border-3',
  }

  const spinnerClass = sizeClasses[size]

  const content = (
    <div className="flex flex-col items-center justify-center gap-3">
      <div
        className={`${spinnerClass} border-stone-600 border-t-amber-500 rounded-full animate-spin`}
        role="status"
        aria-label="Loading"
      />
      {message && <span className="text-stone-400 text-sm">{message}</span>}
    </div>
  )

  if (fullScreen) {
    return <div className="flex items-center justify-center h-screen">{content}</div>
  }

  return content
}
