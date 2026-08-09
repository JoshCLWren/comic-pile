import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

export const ROLL_BOOTSTRAP_RECONCILED_EVENT = 'comic-pile:roll-bootstrap-reconciled'

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
  if (!error || typeof error !== 'object') return false

  const candidate = error as { code?: string; message?: string; response?: unknown }
  if (candidate.response) return false

  return candidate.code === 'ECONNABORTED'
    || candidate.code === 'ETIMEDOUT'
    || candidate.message?.toLowerCase().includes('timeout') === true
    || candidate.message === 'Network Error'
}

export function isAuthenticationMutationFailure(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false

  const response = (error as {
    response?: { status?: number; data?: { detail?: unknown } }
  }).response

  if (response?.status === 401) return true
  return response?.status === 403 && response.data?.detail === 'Not authenticated'
}

export function publishRollBootstrap(state: RollBootstrapResponse): void {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return

  window.dispatchEvent(new CustomEvent<RollBootstrapResponse>(
    ROLL_BOOTSTRAP_RECONCILED_EVENT,
    { detail: state },
  ))
}

export async function fetchAndPublishRollBootstrap(): Promise<RollBootstrapResponse> {
  const state = await rollBootstrapApi.get()
  publishRollBootstrap(state)
  return state
}

export async function reconcileAmbiguousRollMutation(
  expectedPendingThreadId?: number,
): Promise<boolean> {
  const state = await fetchAndPublishRollBootstrap()
  const pendingThreadId = normalizePendingThreadId(state.pending_thread_id)

  if (expectedPendingThreadId === undefined) {
    return pendingThreadId === null
  }

  return pendingThreadId !== expectedPendingThreadId
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
): Promise<ProtectedRollMutationRecovery<T>> {
  for (let attempt = 0; attempt <= AUTH_RECOVERY_DELAYS_MS.length; attempt += 1) {
    if (attempt > 0) {
      await wait(AUTH_RECOVERY_DELAYS_MS[attempt - 1])
    }

    let state: RollBootstrapResponse
    try {
      state = await protectedRollMutationApi.bootstrap()
    } catch (error: unknown) {
      if (isAuthenticationMutationFailure(error) && attempt < AUTH_RECOVERY_DELAYS_MS.length) {
        continue
      }
      throw error
    }

    publishRollBootstrap(state)

    if (normalizePendingThreadId(state.pending_thread_id) !== expectedPendingThreadId) {
      return { status: 'stale' }
    }

    return { status: 'retried', value: await retryMutation() }
  }

  return { status: 'stale' }
}
