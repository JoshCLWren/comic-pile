import type {
  ProtectedRollMutationApi,
  RollStateApi,
  RollPendingUserId,
} from '../services/apiTypes'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollStateApi } from '../services/rollStateApi'
import type { RollState } from '../types/rollState'
import { queryClient } from '../query/queryClient'
import { applyRollStateSnapshot } from '../query/cacheEffects'
import { clearAllPendingSelections } from '../services/rollPendingSelection'
import {
  isNumber,
  isObject,
  isWindowDefined,
  isFunction,
  isNonNullObject,
} from '../utils/runtimeChecks'

export const ROLL_STATE_RECONCILED_EVENT = 'comic-pile:roll-state-reconciled'

const AUTH_RECOVERY_DELAYS_MS = [250, 500, 1000, 2000, 4000]

export type ProtectedRollMutationRecovery<T> =
  | { status: 'retried'; value: T }
  | { status: 'stale' }

function normalizePendingThreadId(
  value: number | string | null | undefined,
): number | null {
  if (value === null || value === undefined) return null
  const normalized = Number(value)
  return Number.isFinite(normalized) ? normalized : null
}

export function isAmbiguousNetworkFailure(error: unknown): boolean {
  if (!error || !isNonNullObject(error)) return false

  // SAFETY: isNonNullObject(error) above guarantees a readable object; the cast only widens to optional fields.
  const candidate = error as { code?: string; message?: string; response?: unknown }
  if (candidate.response) return false

  return candidate.code === 'ECONNABORTED'
    || candidate.code === 'ETIMEDOUT'
    || candidate.message?.toLowerCase().includes('timeout') === true
    || candidate.message === 'Network Error'
}

function isRetryableRollRecoveryFailure(error: unknown): boolean {
  if (isAuthenticationMutationFailure(error)) return true
  if (!error || !isNonNullObject(error)) return false
  const response = error.response
  return isObject(response) && isNumber(response.status) && response.status === 503
}

export function isAuthenticationMutationFailure(error: unknown): boolean {
  if (!error || !isNonNullObject(error)) return false

  // SAFETY: isNonNullObject(error) above guarantees a readable object; .response is an optional field.
  const response = (error as {
    response?: { status?: number; data?: { detail?: unknown } }
  }).response

  if (response?.status === 401) return true
  return response?.status === 403 && response.data?.detail === 'Not authenticated'
}

export function publishRollState(state: RollState): void {
  // Active Roll observers consume this cache-only snapshot immediately; the
  // event remains for non-React reconciliation listeners and focused tests.
  applyRollStateSnapshot(queryClient, state)
  if (!isWindowDefined() || !isFunction(CustomEvent)) return

  window.dispatchEvent(new CustomEvent<RollState>(
    ROLL_STATE_RECONCILED_EVENT,
    { detail: state },
  ))
}

export async function fetchAndPublishRollState(
  stateApi: RollStateApi = rollStateApi,
  userId?: RollPendingUserId,
): Promise<RollState> {
  const state = await stateApi.get(userId)
  publishRollState(state)
  return state
}

export interface AmbiguousRollMutationReconciliation {
  committed: boolean
  /** Authoritative state fetched and published while reconciling. */
  rollState: RollState
}

export async function reconcileAmbiguousRollMutation(
  expectedPendingThreadId?: number,
  stateApi: RollStateApi = rollStateApi,
  userId?: RollPendingUserId,
): Promise<AmbiguousRollMutationReconciliation> {
  const state = await fetchAndPublishRollState(stateApi, userId)
  const pendingThreadId = normalizePendingThreadId(state.pending_thread_id)

  const committed = expectedPendingThreadId === undefined
    ? pendingThreadId === null
    : pendingThreadId !== expectedPendingThreadId
  if (committed) clearAllPendingSelections(userId)

  return { committed, rollState: state }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export async function recoverProtectedRollMutation<T>(
  expectedPendingThreadId: number,
  retryMutation: () => Promise<T>,
  wait: (ms: number) => Promise<void> = delay,
  mutationApi: ProtectedRollMutationApi = protectedRollMutationApi,
  userId?: RollPendingUserId,
): Promise<ProtectedRollMutationRecovery<T>> {
  for (let attempt = 0; attempt <= AUTH_RECOVERY_DELAYS_MS.length; attempt += 1) {
    if (attempt > 0) {
      await wait(AUTH_RECOVERY_DELAYS_MS[attempt - 1])
    }

    let state: RollState
    try {
      state = await mutationApi.rollState(userId)
    } catch (error: unknown) {
      if (isRetryableRollRecoveryFailure(error) && attempt < AUTH_RECOVERY_DELAYS_MS.length) {
        continue
      }
      throw error
    }

    publishRollState(state)

    if (normalizePendingThreadId(state.pending_thread_id) !== expectedPendingThreadId) {
      return { status: 'stale' }
    }

    return { status: 'retried', value: await retryMutation() }
  }

  return { status: 'stale' }
}
