/**
 * A reusable loading spinner component with consistent styling.
 *
 * @param {Object} props - Component props
 * @param {string} [props.message='Loading...'] - Optional loading message to display
 * @param {boolean} [props.fullScreen=false] - If true, centers the spinner in the viewport
 * @param {'sm'|'md'|'lg'} [props.size='md'] - Size variant: 'sm', 'md', or 'lg'
 * @returns {JSX.Element} The loading spinner component
 */
export default function LoadingSpinner({ message = 'Loading...', fullScreen = false, size = 'md' }) {
  const sizeClasses = {
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
