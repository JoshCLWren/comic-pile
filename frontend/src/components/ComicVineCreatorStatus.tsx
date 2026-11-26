import type { ComicVineHydrationState } from '../hooks/useComicVineMetadataHydration'

export interface ComicVineCreatorStatusProps {
  state: ComicVineHydrationState | null
  isHydrating: boolean
  canRetry: boolean
  retryAfterSeconds: number
  onRetry: () => void
}

interface StatusPresentation {
  testId: string
  message: string
  isFailure: boolean
}

function present(state: ComicVineHydrationState, retryAfterSeconds: number): StatusPresentation | null {
  switch (state) {
    case 'hydrating':
      return {
        testId: 'creator-status-hydrating',
        message: 'Loading creator credits…',
        isFailure: false,
      }
    case 'not-hydrated':
      return {
        testId: 'creator-status-not-hydrated',
        message: 'Creator credits not yet fetched',
        isFailure: false,
      }
    case 'no-credits':
      return {
        testId: 'creator-status-no-credits',
        message: 'ComicVine currently has no creator credits',
        isFailure: false,
      }
    case 'rate-limited':
      return {
        testId: 'creator-status-rate-limited',
        message: retryAfterSeconds > 0
          ? `ComicVine is rate limiting requests. Retry in ${retryAfterSeconds}s.`
          : 'ComicVine is rate limiting requests.',
        isFailure: true,
      }
    case 'unavailable':
      return {
        testId: 'creator-status-unavailable',
        message: 'ComicVine is unavailable right now',
        isFailure: true,
      }
    case 'timeout':
      return {
        testId: 'creator-status-timeout',
        message: 'ComicVine took too long to respond',
        isFailure: true,
      }
    case 'invalid-response':
      return {
        testId: 'creator-status-invalid-response',
        message: 'ComicVine returned an invalid response',
        isFailure: true,
      }
    case 'failed':
      return {
        testId: 'creator-status-failed',
        message: 'Creator credits could not be loaded',
        isFailure: true,
      }
    default:
      return null
  }
}

/**
 * One presentation/action contract for deep-metadata state on an exact owned
 * issue. Every surface that renders ComicIdentity gets the same truthful
 * message and the same single Retry action; no page implements its own poller.
 */
export function ComicVineCreatorStatus({
  state,
  isHydrating,
  canRetry,
  retryAfterSeconds,
  onRetry,
}: ComicVineCreatorStatusProps) {
  if (state == null) return null
  const presentation = present(state, retryAfterSeconds)
  if (presentation == null) return null

  return (
    <div className="space-y-1">
      <p
        data-testid={presentation.testId}
        role={presentation.isFailure ? 'alert' : 'status'}
        aria-live={presentation.isFailure ? 'assertive' : 'polite'}
        className={`text-[11px] italic ${presentation.isFailure ? 'text-[var(--theme-error)]' : 'text-[var(--theme-text-muted)]'}`}
      >
        {presentation.message}
      </p>
      {canRetry && (
        <button
          type="button"
          data-testid="creator-retry"
          onClick={onRetry}
          disabled={isHydrating}
          aria-label="Retry creator credits"
          className="inline-flex min-h-6 items-center rounded font-bold text-[var(--theme-primary-action)] hover:underline disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        >
          {isHydrating ? 'Retrying…' : 'Retry'}
        </button>
      )}
    </div>
  )
}
