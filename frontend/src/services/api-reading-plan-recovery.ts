import { defaultHttpClient, type HttpClient } from './httpClient'

export interface RecoveryStep {
  issue_id: number
  label: string
}

export interface RecoveryCandidate {
  list_id: number
  name: string
  mode: 'strict' | 'loose'
  list_updated_at: string
  steps: RecoveryStep[]
  added_steps: RecoveryStep[]
  removed_steps: RecoveryStep[]
  order_changed: boolean
}

export interface PlanRecoveryPreview {
  plan_id: number
  plan_name: string
  plan_updated_at: string
  status: 'orphaned' | 'linked' | 'ambiguous'
  linked_list_id: number | null
  retained_steps: RecoveryStep[]
  candidates: RecoveryCandidate[]
}

export interface PlanRelinkRequest {
  list_id: number
  expected_plan_updated_at: string
  expected_list_updated_at: string
  confirm: true
}

export interface PlanRelinkResult {
  plan_id: number
  list_id: number
  status: 'relinked' | 'already_linked'
}

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
