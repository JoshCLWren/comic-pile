import type { RatePayload, RollResponse, OverrideRollPayload, SnoozeSessionResponse, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

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
  rate: (data: RatePayload) => Promise<Thread>
  snooze: () => Promise<SnoozeSessionResponse>
  skip: () => Promise<RollResponse>
  bootstrap: () => Promise<RollBootstrapResponse>
}

export interface RollBootstrapApi {
  get: (timezone?: string) => Promise<RollBootstrapResponse>
  switchPrerequisite: (request: import('../types/rollBootstrap').RollPrerequisiteSwitchRequest) => Promise<import('../types/rollBootstrap').RollPrerequisiteSwitchResponse>
}

export interface CacheEffectsApi {
  applyRatedThreadCache: (client: import('@tanstack/react-query').QueryClient, thread: Thread) => Promise<void>
  invalidateCurrentSessionAfterSnooze: (client: import('@tanstack/react-query').QueryClient) => Promise<void>
}

export interface SkipApi {
  skip: () => Promise<RollResponse>
  unskip: (threadId: number) => Promise<void>
}

export interface SnoozeApi {
  snooze: () => Promise<SnoozeSessionResponse>
  unsnooze: (threadId: number) => Promise<void>
}

/** Injectable dependencies for the Roll mutation hooks (snooze/skip/rate). */
export interface RollMutationDeps {
  protectedApi?: ProtectedRollMutationApi
  bootstrapApi?: RollBootstrapApi
  cacheEffects?: CacheEffectsApi
  snoozeApi?: SnoozeApi
  skipApi?: SkipApi
}

/** The subset of `dependenciesApi` used by the Roll page's batch blocker load. */
export interface RollDependenciesApi {
  getBatchBlockingInfo: (threadIds: number[]) => Promise<import('../types').BatchBlockingInfoResponse>
}
