import { isNonNullObject } from '../utils/runtimeChecks'

/**
 * Shared, outage-aware retry budget for read-only React Query traffic (#4271).
 *
 * The app can render several independent query observers at once (Roll, Queue,
 * Reader). Giving every query its own three retries multiplies backend traffic
 * exactly when the API is already degraded, for example while Vercel Python
 * instances are cold-starting. This module replaces that per-query fan-out with
 * one coordinated budget:
 *
 * 1. Every transient failure is recorded. Ordinary single-query retries keep
 *    the historical three-attempt cap.
 * 2. Two transient failures inside {@link OUTAGE_FAILURE_WINDOW_MS} recognize a
 *    shared outage. From that moment queries stop retrying independently.
 * 3. A recognized outage allows exactly one probe retry
 *    ({@link MAX_PROBE_RETRIES_PER_OUTAGE}) after {@link PROBE_RETRY_DELAY_MS}.
 *    When it fails, automatic retrying stops completely: no timers remain, so
 *    nothing can poll indefinitely.
 * 4. The first successful request clears the outage and the query client
 *    refetches the failed active queries once per distinct query key
 *    (`resumeQueriesAfterOutage`). A probe succeeds the same way.
 * 5. While authentication is in a known degraded state the AuthProvider owns
 *    probing (`/v1/auth/me` with its own bounded budget), so query retries are
 *    suppressed entirely. A successful auth recovery uses the same single-key
 *    resume, so the reader sees one refetch per failed query, not one per
 *    observer.
 *
 * Deterministic upper bound for one concurrent burst of `K` failing distinct
 * query keys: `K` initial requests + at most one retry queued before the outage
 * is recognized + at most one probe = `K + 2` requests. After a failed probe
 * there are zero further automatic requests until a request succeeds or the
 * reader acts (focus, navigation, explicit Retry), and any resulting success
 * refetches the remaining failed keys once each.
 *
 * The budget is intentionally module-level state because TanStack Query's retry
 * callback is evaluated per query and has no shared context. Reset it in tests
 * with {@link resetQueryRetryBudget}.
 */

/** Recognized-outage retry behavior shared by every app query. */
export const QUERY_OUTAGE_BUDGET = {
  /** Automatic retries one query may schedule before an outage is recognized. */
  maxRetriesPerQuery: 3,
  /** Rolling window that counts transient failures toward an outage. */
  outageFailureWindowMs: 10_000,
  /** Distinct transient failures inside the window that recognize an outage. */
  outageFailureThreshold: 2,
  /** Automatic retries allowed for the whole app once an outage is recognized. */
  maxProbeRetriesPerOutage: 1,
  /** Delay before that single outage probe. */
  probeRetryDelayMs: 4_000,
  /** Base delay for ordinary exponential query retries. */
  retryBaseDelayMs: 1_000,
  /** Cap for ordinary exponential query retries. */
  retryMaxDelayMs: 8_000,
} as const

/** Read-only view of the shared budget, used by tests and diagnostics. */
export interface QueryRetryBudgetSnapshot {
  authDegraded: boolean
  outageActive: boolean
  probeRetriesUsed: number
  recentTransientFailures: number
}

interface TransportFailureFields {
  status?: number
  detail?: string
  code?: string
  name?: string
}

let authDegraded = false
let outageStartedAt: number | null = null
let probeRetriesUsed = 0
let transientFailureTimestamps: number[] = []

/**
 * Read the transport fields retry classification needs from an unknown error.
 *
 * @param error - Rejected query value; may be an AxiosError, a plain Error, or
 *   the interceptor's network-error replacement.
 * @returns The status, auth detail, and cancellation markers when present.
 */
function readTransportFailure(error: unknown): TransportFailureFields {
  if (!error || !isNonNullObject(error)) {
    return {}
  }

  // SAFETY: isNonNullObject(error) guarantees a readable object; the cast only
  // widens to the optional transport fields this module reads.
  const candidate = error as {
    code?: string
    name?: string
    response?: { status?: number; data?: { detail?: string } }
  }
  return {
    status: candidate.response?.status,
    detail: candidate.response?.data?.detail,
    code: candidate.code,
    name: candidate.name,
  }
}

/**
 * Whether a rejection is a cancellation rather than a backend failure.
 *
 * @param error - Rejected query value.
 * @returns True for axios / AbortController cancellation errors.
 */
export function isCanceledQueryFailure(error: unknown): boolean {
  const failure = readTransportFailure(error)
  return failure.code === 'ERR_CANCELED'
    || failure.name === 'CanceledError'
    || failure.name === 'AbortError'
}

/**
 * Whether a rejection is an authentication failure.
 *
 * @param error - Rejected query value.
 * @returns True for 401 and the auth-specific 403 detail. These are never
 *   retried by TanStack; the axios interceptor owns refresh handling.
 */
export function isAuthQueryFailure(error: unknown): boolean {
  const failure = readTransportFailure(error)
  return failure.status === 401
    || (failure.status === 403 && failure.detail === 'Not authenticated')
}

/**
 * Whether a rejection is worth an automatic retry.
 *
 * @param error - Rejected query value.
 * @returns False for auth, cancellation, and deterministic 4xx failures; true
 *   for network/timeout, 408, 429, 3xx, 5xx, and unclassified failures.
 */
export function isTransientQueryFailure(error: unknown): boolean {
  if (isCanceledQueryFailure(error) || isAuthQueryFailure(error)) {
    return false
  }

  const { status } = readTransportFailure(error)
  if (status === undefined) {
    return true
  }
  if (status >= 400 && status < 500) {
    return status === 408 || status === 429
  }
  return true
}

function pruneFailureWindow(now: number): void {
  transientFailureTimestamps = transientFailureTimestamps.filter(
    (timestamp) => now - timestamp <= QUERY_OUTAGE_BUDGET.outageFailureWindowMs,
  )
}

function resetOutageState(): void {
  outageStartedAt = null
  probeRetriesUsed = 0
  transientFailureTimestamps = []
}

function consumeProbeRetry(): boolean {
  if (probeRetriesUsed >= QUERY_OUTAGE_BUDGET.maxProbeRetriesPerOutage) {
    return false
  }
  probeRetriesUsed += 1
  return true
}

/**
 * Decide whether one query failure may schedule another attempt.
 *
 * TanStack Query calls this with the zero-based failure count. The function is
 * the single place that recognizes an outage, so concurrent queries coordinate
 * through it instead of each launching their own retry chain.
 *
 * @param failureCount - Zero-based count of failures for this query.
 * @param error - Rejected query value.
 * @returns True when a retry may be scheduled now.
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (!isTransientQueryFailure(error)) {
    return false
  }
  if (authDegraded) {
    // AuthProvider owns recovery probing; query retries would race it.
    return false
  }

  if (outageStartedAt !== null) {
    return consumeProbeRetry()
  }

  if (failureCount >= QUERY_OUTAGE_BUDGET.maxRetriesPerQuery) {
    return false
  }

  const now = Date.now()
  pruneFailureWindow(now)
  transientFailureTimestamps.push(now)
  if (transientFailureTimestamps.length >= QUERY_OUTAGE_BUDGET.outageFailureThreshold) {
    outageStartedAt = now
    return consumeProbeRetry()
  }
  return true
}

/**
 * Delay before a retry that {@link shouldRetryQuery} just allowed.
 *
 * @param failureCount - Zero-based count of failures for this query.
 * @returns The outage probe delay when this retry is the probe, otherwise
 *   capped exponential backoff. Deterministic so tests and operators can
 *   reason about the upper bound without jitter.
 */
export function queryRetryDelay(failureCount: number): number {
  // TanStack Query evaluates retryDelay BEFORE calling the retry predicate.
  // A pending second transient failure will become the one shared probe;
  // compute its delay from the failure window rather than a flag set by the
  // later shouldRetryQuery callback. Otherwise the probe fires at 1s.
  if (
    outageStartedAt !== null
    || transientFailureTimestamps.length >= QUERY_OUTAGE_BUDGET.outageFailureThreshold - 1
  ) {
    return QUERY_OUTAGE_BUDGET.probeRetryDelayMs
  }
  const exponent = Math.max(failureCount, 0)
  return Math.min(
    QUERY_OUTAGE_BUDGET.retryBaseDelayMs * 2 ** exponent,
    QUERY_OUTAGE_BUDGET.retryMaxDelayMs,
  )
}

/** Suppress query retries while authentication owns recovery probing. */
export function markAuthDegraded(): void {
  authDegraded = true
}

/**
 * Report that authentication recovered.
 *
 * @returns True when the previous state was degraded, so the caller can resume
 *   failed queries exactly once. A normal authenticated transition returns
 *   false and leaves backend-outage tracking untouched.
 */
export function markAuthRecovered(): boolean {
  const recovered = authDegraded
  authDegraded = false
  if (recovered) {
    resetOutageState()
  }
  return recovered
}

/**
 * Report one successful query or auth recovery request.
 *
 * @returns True when a recognized outage just ended, so the query client can
 *   refetch the queries that failed during it once per distinct key.
 */
export function noteSuccessfulQuery(): boolean {
  if (outageStartedAt === null) {
    return false
  }
  resetOutageState()
  return true
}

/**
 * Report that a session ended (logout, account switch, or session rejection).
 *
 * Clears both the auth-degraded flag and any tracked outage so a new account
 * never inherits the previous session's retry state.
 */
export function resetQueryRetryBudget(): void {
  authDegraded = false
  resetOutageState()
}

/**
 * Snapshot the current budget for tests and diagnostics.
 *
 * @returns A read-only copy of the current coordination state.
 */
export function getQueryRetryBudgetSnapshot(): QueryRetryBudgetSnapshot {
  return {
    authDegraded,
    outageActive: outageStartedAt !== null,
    probeRetriesUsed,
    recentTransientFailures: transientFailureTimestamps.length,
  }
}
