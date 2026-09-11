import type { RollResponse, OverrideRollPayload } from '../types'

export interface RollApi {
  roll: () => Promise<RollResponse>
  override: (data: OverrideRollPayload) => Promise<RollResponse>
  dismissPending: () => Promise<void>
  skip: () => Promise<RollResponse>
  reroll: () => Promise<RollResponse>
  setDie: (die: number) => Promise<void>
  clearManualDie: () => Promise<void>
}

export interface ProtectedRollMutationApi {
  rate: (payload: { thread_id: number; rating: number; issues_read?: number; finish_session?: boolean; issue_number?: string }) => Promise<import('../types').Thread>
  snooze: () => Promise<void>
  skip: (threadId: number) => Promise<void>
  bootstrap: (state: import('../types/rollBootstrap').RollBootstrapResponse) => Promise<void>
}

export interface RollBootstrapApi {
  get: () => Promise<import('../types/rollBootstrap').RollBootstrapResponse>
}

export interface CacheEffectsApi {
  applyRatedThreadCache: (client: import('@tanstack/react-query').QueryClient, thread: import('../types').Thread) => Promise<void>
  invalidateCurrentSessionAfterSnooze: (client: import('@tanstack/react-query').QueryClient) => Promise<void>
}

export interface SkipApi {
  skip: () => Promise<RollResponse>
  unskip: (threadId: number) => Promise<void>
}

export interface SnoozeApi {
  snooze: () => Promise<void>
  unsnooze: (threadId: number) => Promise<void>
}
