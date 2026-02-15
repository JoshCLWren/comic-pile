interface LoadingSpinnerProps {
  message?: string
  fullScreen?: boolean
  size?: 'sm' | 'md' | 'lg'
}

/**
 * A reusable loading spinner component with consistent styling.
 *
 * @param props - Component props
 * @param props.message - Optional loading message to display
 * @param props.fullScreen - If true, centers the spinner in the viewport
 * @param props.size - Size variant: 'sm', 'md', or 'lg'
 * @returns The loading spinner component
 */
export default function LoadingSpinner({ message = 'Loading...', fullScreen = false, size = 'md' }: LoadingSpinnerProps) {
  const sizeClasses: Record<string, string> = {
    sm: 'w-4 h-4 border-2',
    md: 'w-6 h-6 border-2',
    lg: 'w-8 h-8 border-3',
  }

  const spinnerClass = sizeClasses[size] || sizeClasses.md

  const content = (
    <div className="flex flex-col items-center justify-center gap-3">
      <div
        className={`${spinnerClass} border-slate-600 border-t-teal-400 rounded-full animate-spin`}
        role="status"
        aria-label="Loading"
      />
      {message && <span className="text-slate-400 text-sm">{message}</span>}
    </div>
  )

  if (fullScreen) {
    return <div className="flex items-center justify-center h-screen">{content}</div>
  }

  return content
}
