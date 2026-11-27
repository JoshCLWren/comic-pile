import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  ComicVineHydrationOutcome,
  ComicVineIssueIntelligence,
} from '../services/api-comicvine'
import { comicVineApi } from '../services/api-comicvine'
import { queryClient } from '../query/queryClient'
import { invalidateComicVineHydrationProjections } from '../query/cacheEffects'

/**
 * Truthful, bounded presentation states for exact-issue ComicVine deep
 * metadata. There is deliberately no `queued` or `refreshing` state: a request
 * that is not in flight has no progress to report, and a stored stale row is
 * simply not hydrated yet.
 */
export type ComicVineMetadataPresentation =
  | 'not_hydrated'
  | 'no_credits'
  | 'unavailable'
  | 'rate_limited'
  | 'timeout'
  | 'invalid_response'
  | 'not_confirmed'
  | 'provider_not_configured'
  | 'failed'

export interface ComicVineMetadataHydrationState {
  /** `null` means there is nothing to say (credits are visible or status is unknown). */
  presentation: ComicVineMetadataPresentation | null
  message: string | null
  /** True only while a real hydration request is in flight. */
  isHydrating: boolean
  /** False for terminal results the reader cannot fix by retrying here. */
  canRetry: boolean
  retryAfterSeconds: number | null
  retry: () => Promise<void>
}

interface PresentationDetails {
  presentation: ComicVineMetadataPresentation
  message: string
  retryable: boolean
}

interface OutcomeState {
  details: PresentationDetails
  message: string
  retryAfterSeconds: number | null
}

const NO_CREDITS: PresentationDetails = {
  presentation: 'no_credits',
  message: 'ComicVine currently has no creator credits',
  retryable: false,
}

const NOT_HYDRATED: PresentationDetails = {
  presentation: 'not_hydrated',
  message: 'Creator credits not yet hydrated',
  retryable: true,
}

const FAILED: PresentationDetails = {
  presentation: 'failed',
  message: 'Creator credits could not be loaded. Your mapping is safe — try again.',
  retryable: true,
}

const OUTCOME_DETAILS: Record<ComicVineHydrationOutcome, PresentationDetails> = {
  complete: FAILED,
  persist_failed: FAILED,
  no_credits: NO_CREDITS,
  not_confirmed: {
    presentation: 'not_confirmed',
    message: 'No confirmed ComicVine issue is mapped to this comic. Map it to continue.',
    retryable: false,
  },
  provider_not_configured: {
    presentation: 'provider_not_configured',
    message: 'ComicVine credentials are not configured on this server.',
    retryable: false,
  },
  provider_unavailable: {
    presentation: 'unavailable',
    message: 'ComicVine is unavailable right now. Your mapping is safe — try again.',
    retryable: true,
  },
  rate_limited: {
    presentation: 'rate_limited',
    message: 'ComicVine rate limited this request. Try again',
    retryable: true,
  },
  timeout: {
    presentation: 'timeout',
    message: 'ComicVine did not answer in time. Your mapping is safe — try again.',
    retryable: true,
  },
  invalid_response: {
    presentation: 'invalid_response',
    message: 'ComicVine returned an invalid response. Try again.',
    retryable: true,
  },
}

/**
 * Map a stored server status without inventing progress. Roster-only and
 * explicitly stale rows are "not hydrated"; the obsolete pending/running
 * states carry no in-flight request, so they are also truthfully not hydrated
 * rather than a spinner that never settles.
 */
function detailsForStoredStatus(status: string | undefined): PresentationDetails | null {
  switch (status) {
    case 'not_deep_fetched':
      return { ...NOT_HYDRATED, message: 'Creator credits not yet fetched' }
    case 'needs_hydration':
    case 'refresh_pending':
    case 'refresh_running':
      return NOT_HYDRATED
    case 'deep_fetched_no_credits':
    case 'complete':
      return NO_CREDITS
    case 'refresh_deferred':
      return OUTCOME_DETAILS.provider_unavailable
    case 'refresh_failed':
      return FAILED
    default:
      return null
  }
}


function messageWithDelay(base: string, retryAfterSeconds: number | null): string {
  if (retryAfterSeconds == null || retryAfterSeconds <= 0) {
    return base.endsWith('.') ? base : `${base}.`
  }
  const withoutPeriod = base.endsWith('.') ? base.slice(0, -1) : base
  return `${withoutPeriod} in ${retryAfterSeconds}s.`
}

export interface UseComicVineMetadataHydrationOptions {
  issueId: number | null | undefined
  metadata: ComicVineIssueIntelligence | null
  /** Awaitable refetch of the exact owned-issue intelligence query. */
  refetchIntelligence: () => Promise<ComicVineIssueIntelligence | null>
  /**
   * False for list/queue/series rows or other non-detail surfaces. Only an
   * exact issue the reader deliberately opened may hydrate automatically.
   */
  enabled?: boolean
}

/**
 * Shared presentation and action contract for exact owned-issue ComicVine
 * metadata (issue #5841).
 *
 * One bounded `metadata:refresh` request is fired for a deliberately opened
 * roster-only issue. Every other attempt is the reader's explicit Retry. There
 * are no timers, no polling, no automatic repeats and no detached work. The
 * request is single-flight, identity-scoped and generation-guarded, so a late
 * response for identity A cannot repaint a remapped identity B, and navigating
 * away or unmounting cannot refetch a stale issue.
 */
export function useComicVineMetadataHydration({
  issueId,
  metadata,
  refetchIntelligence,
  enabled = true,
}: UseComicVineMetadataHydrationOptions): ComicVineMetadataHydrationState {
  const [outcomeState, setOutcomeState] = useState<OutcomeState | null>(null)
  const [isHydrating, setIsHydrating] = useState(false)

  const identity = metadata?.comicvine_issue_id ?? null
  const issueIdRef = useRef(issueId)
  const identityRef = useRef(identity)
  const refetchRef = useRef(refetchIntelligence)
  const generationRef = useRef(0)
  const inFlightRef = useRef(false)
  const mountedRef = useRef(true)
  const nextRetryAtRef = useRef(0)
  const autoHydrationKeyRef = useRef<string | null>(null)
  const identityKeyRef = useRef<string | null>(null)

  issueIdRef.current = issueId
  identityRef.current = identity
  refetchRef.current = refetchIntelligence

  // Identity replacement (or navigation to another issue) invalidates every
  // in-flight response and terminal message from the previous identity.
  useEffect(() => {
    const key = `${issueId}:${identity}`
    // StrictMode replays effects with unchanged props; only a real navigation
    // or remap may invalidate the previous identity's request.
    if (identityKeyRef.current === key) return
    identityKeyRef.current = key
    generationRef.current += 1
    // The previous identity's request is now stale. Do not let its single-flight
    // flag swallow an explicit Retry for the newly confirmed identity; the
    // generation guard in `runHydration` still rejects its late response.
    inFlightRef.current = false
    setIsHydrating(false)
    nextRetryAtRef.current = 0
    setOutcomeState(null)
    autoHydrationKeyRef.current = null
  }, [issueId, identity])

  // The setup must remount the flag: React StrictMode runs setup -> cleanup ->
  // setup in development. A cleanup with no matching setup would leave the
  // flag false forever, discarding every later response and skipping the
  // isHydrating reset in `finally` (permanent "Hydrating creator credits").
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const runHydration = useCallback(async (respectRetryAfter: boolean) => {
    const targetIssueId = issueIdRef.current
    if (targetIssueId == null || inFlightRef.current) return

    if (respectRetryAfter && Date.now() < nextRetryAtRef.current) {
      const waitSeconds = Math.ceil((nextRetryAtRef.current - Date.now()) / 1000)
      const details = OUTCOME_DETAILS.rate_limited
      setOutcomeState({
        details,
        message: messageWithDelay(details.message, waitSeconds),
        retryAfterSeconds: waitSeconds,
      })
      return
    }

    const generation = generationRef.current
    const targetIdentity = identityRef.current
    inFlightRef.current = true
    setIsHydrating(true)
    try {
      const result = await comicVineApi.refreshMetadata(targetIssueId)
      if (!mountedRef.current || generation !== generationRef.current
        || targetIdentity !== identityRef.current) return

      // An older deployment may answer an empty 200. Treat that as "no
      // terminal outcome" instead of inventing a failure, and keep the stored
      // status truthful until the exact issue is re-read.
      if (result == null) {
        await refetchRef.current()
        if (!mountedRef.current || generation !== generationRef.current
        || targetIdentity !== identityRef.current) return
        void invalidateComicVineHydrationProjections(queryClient)
        return
      }

      const retryAfter = result.retry_after_seconds ?? null
      if (retryAfter != null && retryAfter > 0) {
        nextRetryAtRef.current = Date.now() + retryAfter * 1000
      }
      const outcome = result.outcome
      const refreshed = result.refreshed === true

      if (outcome === 'no_credits') {
        setOutcomeState({
          details: NO_CREDITS,
          message: NO_CREDITS.message,
          retryAfterSeconds: null,
        })
      } else if (refreshed && (outcome === 'complete' || outcome == null)) {
        // An older deployment may report refreshed=true without an outcome
        // field. Do not invent a failure: the scoped re-read below decides the
        // truthful presentation, so a stored no-credits result stays an empty
        // result rather than becoming a bogus retryable failure (#5841).
        setOutcomeState(null)
      } else if (outcome != null) {
        const details = OUTCOME_DETAILS[outcome] ?? FAILED
        setOutcomeState({
          details,
          message: messageWithDelay(details.message, retryAfter),
          retryAfterSeconds: retryAfter,
        })
      } else {
        setOutcomeState({
          details: FAILED,
          message: messageWithDelay(FAILED.message, retryAfter),
          retryAfterSeconds: retryAfter,
        })
      }

      // Re-read the exact issue so persisted names/roles and cover appear
      // without a remap. A failed attempt still confirms the mapping survived.
      await refetchRef.current()
      if (!mountedRef.current || generation !== generationRef.current
        || targetIdentity !== identityRef.current) return
      void invalidateComicVineHydrationProjections(queryClient)
    } catch {
      if (!mountedRef.current || generation !== generationRef.current
        || targetIdentity !== identityRef.current) return
      setOutcomeState({
        details: FAILED,
        message: 'Could not request creator credits. Try again.',
        retryAfterSeconds: null,
      })
    } finally {
      // Only the request for the still-current identity owns the single-flight
      // flag and loading state; a superseded A request must not clear B's flag
      // or hide B's in-flight progress when it settles late.
      if (generation === generationRef.current) {
        inFlightRef.current = false
        if (mountedRef.current) setIsHydrating(false)
      }
    }
  }, [])

  const retry = useCallback(async () => {
    await runHydration(true)
  }, [runHydration])

  // A roster-only exact issue gets exactly one awaited hydration on deliberate
  // open. `needs_hydration` is the server's explicit user-Retry signal and is
  // intentionally excluded, as are all list/queue/series surfaces.
  useEffect(() => {
    if (!enabled || issueId == null || identity == null || metadata == null) return
    if (metadata.creators.length > 0 || outcomeState != null) return
    if (metadata.metadata_status !== 'not_deep_fetched') return
    const key = `${issueId}:${identity}`
    if (autoHydrationKeyRef.current === key) return
    autoHydrationKeyRef.current = key
    void runHydration(false)
  }, [enabled, issueId, identity, metadata, outcomeState, runHydration])

  const hasCredits = (metadata?.creators.length ?? 0) > 0
  const storedDetails = hasCredits ? null : detailsForStoredStatus(metadata?.metadata_status)
  const storedRetryAfter = metadata?.refresh_retry_after_seconds ?? null
  const active = outcomeState ?? (storedDetails ? {
    details: storedDetails,
    message: messageWithDelay(storedDetails.message, storedRetryAfter),
    retryAfterSeconds: storedRetryAfter,
  } : null)

  return {
    presentation: hasCredits ? null : active?.details.presentation ?? null,
    message: hasCredits ? null : active?.message ?? null,
    isHydrating,
    canRetry: active?.details.retryable ?? false,
    retryAfterSeconds: active?.retryAfterSeconds ?? null,
    retry,
  }
}
