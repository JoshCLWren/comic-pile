import { useCallback, useEffect, useRef, useState } from 'react'
import {
  comicVineApi,
  type ComicVineIssueIntelligence,
  type MetadataRefreshResponse,
} from '../services/api-comicvine'
import { getApiErrorStatus } from '../utils/apiError'

/**
 * Truthful presentation states for one confirmed owned issue's deep metadata.
 *
 * `hydrating` is the only loading state and it is true strictly while the
 * awaited provider request is in flight. There is no queued/running state: a
 * repair ledger that still reports one is presented as `not-hydrated` with a
 * user-controlled retry (#5841, superseding #5695's polling UI).
 */
export type ComicVineHydrationState =
  | 'loading'
  | 'hydrating'
  | 'credits'
  | 'no-credits'
  | 'not-hydrated'
  | 'unavailable'
  | 'rate-limited'
  | 'timeout'
  | 'invalid-response'
  | 'failed'

export interface UseComicVineMetadataHydrationArgs {
  issueId: number | null | undefined
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  isError: boolean
  refetch: () => Promise<ComicVineIssueIntelligence | null>
  /** A deliberate exact-issue open may start one bounded awaited hydration. */
  autoHydrate?: boolean
}

export interface UseComicVineMetadataHydrationResult {
  state: ComicVineHydrationState | null
  isHydrating: boolean
  /** The Retry action applies to the current state and confirmed issue. */
  showRetry: boolean
  /** Retry is enabled: no in-flight request and no provider cooldown. */
  canRetry: boolean
  retryAfterSeconds: number
  /** Awaits one bounded hydration for the currently confirmed identity only. */
  retry: () => Promise<void>
}

const DEFAULT_RETRY_AFTER_SECONDS = 10

/**
 * Deduplicates concurrent hydrations for the same confirmed identity across
 * every mounted surface (Roll, shared issue card, direct-read panel). A remap
 * produces a different key, so it never shares an in-flight request with the
 * identity it replaced.
 */
const inFlightHydrations = new Map<string, Promise<MetadataRefreshResponse | undefined>>()

function identityKeyFor(issueId: number | null | undefined, metadata: ComicVineIssueIntelligence | null): string {
  return `${issueId ?? 'none'}:${metadata?.comicvine_issue_id ?? 'none'}`
}

function statusFromMetadata(metadata: ComicVineIssueIntelligence): ComicVineHydrationState | null {
  if (metadata.creators.length > 0) return 'credits'
  switch (metadata.metadata_status) {
    case 'complete':
    case 'deep_fetched':
    case 'deep_fetched_no_credits':
    case 'no_credits':
    case 'no-credits':
      return 'no-credits'
    case 'not_deep_fetched':
    case 'refresh_pending':
    case 'refresh_running':
    case 'pending':
    case 'running':
      return 'not-hydrated'
    case 'refresh_deferred':
    case 'rate_limited':
    case 'rate-limited':
    case 'throttled':
      return 'rate-limited'
    case 'unavailable':
    case 'provider_unavailable':
      return 'unavailable'
    case 'timeout':
      return 'timeout'
    case 'invalid_response':
    case 'invalid-response':
      return 'invalid-response'
    case 'refresh_failed':
    case 'failed':
      return 'failed'
    default:
      return null
  }
}

function classifyOutcome(outcome: string | null | undefined): ComicVineHydrationState | null {
  switch (outcome) {
    case 'no_credits':
    case 'no-credits':
    case 'deep_fetched_no_credits':
      return 'no-credits'
    case 'not_deep_fetched':
    case 'refresh_pending':
    case 'refresh_running':
      return 'not-hydrated'
    case 'unavailable':
    case 'provider_unavailable':
      return 'unavailable'
    case 'rate_limited':
    case 'rate-limited':
    case 'throttled':
      return 'rate-limited'
    case 'timeout':
      return 'timeout'
    case 'invalid_response':
    case 'invalid-response':
      return 'invalid-response'
    case 'refresh_failed':
    case 'failed':
      return 'failed'
    default:
      return null
  }
}

function classifyFailure(error: unknown): ComicVineHydrationState {
  const status = getApiErrorStatus(error)
  if (status === 429) return 'rate-limited'
  if (status === 408 || status === 504) return 'timeout'
  if (status != null && status >= 500) return 'unavailable'
  if (status === 422) return 'invalid-response'
  return 'unavailable'
}

function isRetryAfterHeader(value: unknown): value is string {
  return typeof value === 'string'
}

function readRetryAfter(error: unknown): number | null {
  if (typeof error !== 'object' || error === null || !('response' in error)) return null
  const response: unknown = (error as { response?: unknown }).response
  if (typeof response !== 'object' || response === null || !('headers' in response)) return null
  const headers: unknown = (response as { headers?: unknown }).headers
  if (typeof headers !== 'object' || headers === null || !('retry-after' in headers)) return null
  const raw: unknown = (headers as Record<string, unknown>)['retry-after']
  if (!isRetryAfterHeader(raw)) return null
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null
}

/**
 * Shared action/state contract for ComicVine deep metadata on one exact owned
 * issue (#5840, #5841). It performs at most one awaited hydration per identity,
 * never polls, classifies every failure distinctly, and ignores late responses
 * after a remap or unmount so identity A cannot overwrite B.
 */
export function useComicVineMetadataHydration({
  issueId,
  metadata,
  isLoading,
  isError,
  refetch,
  autoHydrate = true,
}: UseComicVineMetadataHydrationArgs): UseComicVineMetadataHydrationResult {
  const identityKey = identityKeyFor(issueId, metadata)
  const metadataRef = useRef(metadata)
  metadataRef.current = metadata
  const mountedRef = useRef(true)
  const generationRef = useRef(0)
  const autoHydratedIdentityRef = useRef<string | null>(null)

  const [failure, setFailure] = useState<ComicVineHydrationState | null>(null)
  const [isHydrating, setIsHydrating] = useState(false)
  const [cooldownUntil, setCooldownUntil] = useState(0)
  // Re-render once when a provider Retry-After window elapses. This flips a
  // single cooldown boundary; it never triggers a request or a refetch.
  const [, setCooldownTick] = useState(0)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      generationRef.current += 1
    }
  }, [])

  useEffect(() => {
    // A confirmed identity change invalidates every late attempt from the old
    // identity and clears its transient presentation state.
    generationRef.current += 1
    autoHydratedIdentityRef.current = null
    setFailure(null)
    setIsHydrating(false)
    setCooldownUntil(0)
  }, [identityKey])

  useEffect(() => {
    if (cooldownUntil <= Date.now()) return
    const timeoutId = setTimeout(
      () => setCooldownTick((tick) => tick + 1),
      Math.max(0, cooldownUntil - Date.now()),
    )
    return () => clearTimeout(timeoutId)
  }, [cooldownUntil])

  const retry = useCallback(async () => {
    if (issueId == null) return
    const key = identityKeyFor(issueId, metadataRef.current)
    const generation = generationRef.current
    if (!mountedRef.current || generation !== generationRef.current) return
    // A second click while the awaited request is in flight is a no-op; so is
    // a click inside a provider-declared Retry-After window.
    if (inFlightHydrations.has(key) || cooldownUntil > Date.now()) return

    setFailure(null)
    setIsHydrating(true)
    const task = comicVineApi.refreshMetadata(issueId)
    inFlightHydrations.set(key, task)
    try {
      const response = await task
      if (!mountedRef.current || generation !== generationRef.current) return
      const retryAfter = response?.retry_after_seconds
      if (typeof retryAfter === 'number' && retryAfter > 0) {
        setCooldownUntil(Date.now() + retryAfter * 1000)
      }
      const outcome = classifyOutcome(response?.outcome)
      // Complete/no-credits/not-hydrated are confirmed by the canonical read
      // below. Only a negative explicit outcome is a local presentation fact.
      if (
        outcome != null
        && outcome !== 'credits'
        && outcome !== 'no-credits'
        && outcome !== 'not-hydrated'
      ) {
        setFailure(outcome)
      }
      await refetch()
    } catch (error) {
      if (!mountedRef.current || generation !== generationRef.current) return
      const outcome = classifyFailure(error)
      setFailure(outcome)
      if (outcome === 'rate-limited') {
        setCooldownUntil(Date.now() + (readRetryAfter(error) ?? DEFAULT_RETRY_AFTER_SECONDS) * 1000)
      }
      // Re-read canonical state after a failure: mapping and any valid cached
      // cover/credits for the same identity must stay visible.
      await refetch()
    } finally {
      inFlightHydrations.delete(key)
      if (mountedRef.current && generation === generationRef.current) {
        setIsHydrating(false)
      }
    }
  }, [cooldownUntil, issueId, refetch])

  // One deliberate exact-issue open with missing deep metadata performs one
  // bounded awaited hydration. There is no timer, no re-arm and no fanout.
  useEffect(() => {
    if (!autoHydrate || issueId == null || isLoading || isError || metadata == null) return
    if (autoHydratedIdentityRef.current === identityKey) return
    if (statusFromMetadata(metadata) !== 'not-hydrated') return
    autoHydratedIdentityRef.current = identityKey
    void retry()
  }, [autoHydrate, identityKey, isError, isLoading, metadata, retry])

  const remainingSeconds = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000))
  const state: ComicVineHydrationState | null = isLoading
    ? 'loading'
    : isHydrating
      ? 'hydrating'
      : failure ?? (metadata ? statusFromMetadata(metadata) : null)
  const retryable = state === 'hydrating'
    || state === 'not-hydrated'
    || state === 'unavailable'
    || state === 'rate-limited'
    || state === 'timeout'
    || state === 'invalid-response'
    || state === 'failed'

  const showRetry = issueId != null && retryable
  return {
    state,
    isHydrating,
    showRetry,
    canRetry: showRetry && !isHydrating && remainingSeconds === 0,
    retryAfterSeconds: remainingSeconds,
    retry,
  }
}
