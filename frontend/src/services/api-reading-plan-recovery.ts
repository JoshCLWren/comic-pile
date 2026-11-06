import { defaultHttpClient, type HttpClient } from './httpClient'

import type { components } from '../generated/openapi'

export type RecoveryStep = components['schemas']['RecoveryStep']
export type RecoveryCandidate = components['schemas']['RecoveryCandidate']
export type PlanRecoveryPreview = components['schemas']['PlanRecoveryPreview']
export type PlanRelinkRequest = components['schemas']['PlanRelinkRequest']
export type PlanRelinkResult = components['schemas']['PlanRelinkResult']

/** Repair is owner-scoped and opt-in: no name-based automatic matching. */
export function createReadingPlanRecoveryApi(client: HttpClient) {
  return {
    preview: (planId: number) =>
      client.get<PlanRecoveryPreview>(`/v2/continuity-plans/${planId}/recovery`),
    relink: (planId: number, request: PlanRelinkRequest) =>
      client.post<PlanRelinkResult, PlanRelinkRequest>(
        `/v2/continuity-plans/${planId}/recovery`,
        request,
      ),
  }
}

export const readingPlanRecoveryApi = createReadingPlanRecoveryApi(defaultHttpClient())
