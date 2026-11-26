import type { ComicVineMetadataHydrationState } from '../hooks/useComicVineMetadataHydration'

interface ComicVineMetadataStatusProps {
  state: ComicVineMetadataHydrationState
}

/**
 * Shared presentation of exact-issue ComicVine deep metadata (issue #5841).
 *
 * The message is truthful about what the server last reported. Loading copy is
 * rendered only while a real request is in flight; the Retry action is a
 * normal, accessible button that is disabled for the duration of that request
 * so a second click cannot start a duplicate hydration.
 */
export default function ComicVineMetadataStatus({ state }: ComicVineMetadataStatusProps) {
  if (!state.presentation || !state.message) return null

  const isFailure = state.presentation === 'failed'
    || state.presentation === 'unavailable'
    || state.presentation === 'rate_limited'
    || state.presentation === 'timeout'
    || state.presentation === 'invalid_response'
  const messageClass = isFailure
    ? 'text-[11px] text-[var(--theme-error)]'
    : 'text-[11px] text-[var(--theme-text-muted)] italic'

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy={state.isHydrating}
      className="space-y-1"
    >
      {state.isHydrating ? (
        <p
          className={messageClass}
          data-testid="creator-status-hydrating"
        >
          Hydrating creator credits…
        </p>
      ) : (
        <p
          className={messageClass}
          data-testid={`creator-status-${state.presentation}`}
        >
          {state.message}
        </p>
      )}
      {state.canRetry && (
        <button
          type="button"
          onClick={() => void state.retry()}
          disabled={state.isHydrating}
          data-testid="creator-metadata-retry"
          className="inline-flex min-h-8 items-center rounded-lg px-2 text-xs font-bold text-[var(--theme-primary-action)] hover:bg-[var(--theme-bg-hover)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
        >
          {state.isHydrating ? 'Retrying…' : 'Retry refresh'}
        </button>
      )}
    </div>
  )
}
