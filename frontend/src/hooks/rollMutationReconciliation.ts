import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

export const ROLL_BOOTSTRAP_RECONCILED_EVENT = 'comic-pile:roll-bootstrap-reconciled'

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
