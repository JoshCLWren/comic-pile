import type {
  RatePayload,
  RateResponsePayload,
  RollResponse,
  OverrideRollPayload,
} from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

export interface RollApi {
  roll: () => Promise<RollResponse>
  override: (data: OverrideRollPayload) => Promise<RollResponse>
  dismissPending: () => Promise<void>
  reroll: (expectedPendingThreadId?: number) => Promise<RollResponse>
  setDie: (die: number) => Promise<void>
  reset: () => Promise<{ die: number; replayed: boolean }>
}

export interface ProtectedRollMutationApi {
  rate: (data: RatePayload) => Promise<RateResponsePayload>
  snooze: () => Promise<RollResponse>
  bootstrap: () => Promise<RollBootstrapResponse>
}

export interface RollBootstrapApi {
  get: (timezone?: string) => Promise<RollBootstrapResponse>
  switchPrerequisite: (request: import('../types/rollBootstrap').RollPrerequisiteSwitchRequest) => Promise<import('../types/rollBootstrap').RollPrerequisiteSwitchResponse>
}

export type SessionApi = ReturnType<typeof import('./api-sessions').createSessionApi>

export interface CacheEffectsApi {
  applyRatedThreadCache: (client: import('@tanstack/react-query').QueryClient, thread: RateResponsePayload) => Promise<void>
  invalidateCurrentSessionAfterSnooze: (client: import('@tanstack/react-query').QueryClient) => Promise<void>
}

/** Injectable dependencies for the Roll mutation hooks (snooze/rate). */
export interface RollMutationDeps {
  protectedApi?: ProtectedRollMutationApi
  bootstrapApi?: RollBootstrapApi
  cacheEffects?: CacheEffectsApi
}

/** The subset of `dependenciesApi` used by the Roll page's batch blocker load. */
export interface RollDependenciesApi {
  getBatchBlockingInfo: (threadIds: number[]) => Promise<import('../types').BatchBlockingInfoResponse>
}
