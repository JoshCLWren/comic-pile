import { Link } from 'react-router-dom'
import { ArrowLeftIcon, CubeIcon } from '@heroicons/react/24/outline'

export default function NotFoundPage() {
  return (
    <div className="min-h-screen bg-[var(--theme-bg-page)]" data-app-shell-ready>
      <div className="mx-auto max-w-lg px-4 py-12 md:px-6 md:py-16 text-center">
        <CubeIcon className="mx-auto h-12 w-12 text-[var(--theme-comic-accent)]" aria-hidden="true" />
        <h1 className="mt-6 text-2xl font-bold text-[var(--theme-text-primary)]">Page not found</h1>
        <p className="mt-3 text-[var(--theme-text-muted)]">
          The path you requested does not exist. It may have been moved or removed.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-stone-900 transition-colors hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
          >
            <ArrowLeftIcon className="h-4 w-4" aria-hidden="true" />
            Back to Roll
          </Link>
        </div>
      </div>
    </div>
  )
}
