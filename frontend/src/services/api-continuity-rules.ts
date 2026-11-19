import api from './api'

export type ContinuityNodeType = 'issue' | 'crossover'
export type ContinuitySatisfactionType =
  | 'item_read'
  | 'all_members_read'
  | 'checkpoint'
  | 'selected_members_read'
  | 'converged'

export interface ContinuityRuleCreate {
  source_type: ContinuityNodeType
  source_id: number
  target_type: ContinuityNodeType
  target_id: number
  satisfaction_type: ContinuitySatisfactionType
  note?: string | null
}

export interface ContinuityRuleResponse {
  id: number
  user_id: number
  source_type: ContinuityNodeType
  source_id: number
  target_type: ContinuityNodeType
  target_id: number
  satisfaction_type: ContinuitySatisfactionType
  checkpoint_issue_id: number | null
  convergence_targets: Array<{ type: ContinuityNodeType; id: number }>
  selected_member_issue_ids: number[]
  note: string | null
  created_at: string
  updated_at: string
}

export const continuityRulesApi = {
  list: async (): Promise<ContinuityRuleResponse[]> => {
    return api.get<ContinuityRuleResponse[]>('/v1/continuity-rules/')
  },

  create: async (payload: ContinuityRuleCreate): Promise<ContinuityRuleResponse> => {
    return api.post<ContinuityRuleResponse>('/v1/continuity-rules/', payload)
  },

  delete: async (ruleId: number): Promise<void> => {
    await api.delete(`/v1/continuity-rules/${ruleId}`)
  },
}
