import api from './api'

export type ContinuityPlanNodeType = 'issue' | 'crossover'

export interface ContinuityPlanNode {
  id: string
  node_type: ContinuityPlanNodeType
  ref_id: number
  lane_id: string
  position: number
}

export interface ContinuityPlanWrite {
  name: string
  ordering_mode: 'strict_sequential'
  lanes: Array<{ id: string; name: string; order: number }>
  nodes: ContinuityPlanNode[]
}

export interface ContinuityPlan extends ContinuityPlanWrite {
  id: number
  user_id: number
  created_at: string
  updated_at: string
}

export const continuityPlansApi = {
  create: (payload: ContinuityPlanWrite) =>
    api.post<ContinuityPlan, ContinuityPlanWrite>('/v1/continuity-plans/', payload),
  get: (planId: number) =>
    api.get<ContinuityPlan>(`/v1/continuity-plans/${planId}`),
  update: (planId: number, payload: ContinuityPlanWrite) =>
    api.put<ContinuityPlan, ContinuityPlanWrite>(`/v1/continuity-plans/${planId}`, payload),
}
