import api from './api'

export type ContinuityPlanNodeType = 'issue' | 'crossover' | 'thread'

export type ContinuityPlanOrderingMode = 'strict_sequential' | 'informational'

export interface ContinuityPlanLane {
  id: string
  name: string
  order: number
}

export interface ConvergenceGateTarget {
  node_type: ContinuityPlanNodeType
  node_id: string
}

export interface ContinuityPlanNode {
  id: string
  node_type: ContinuityPlanNodeType
  ref_id: number
  lane_id: string
  position: number
  label?: string | null
  is_checkpoint?: boolean
  convergence_gate?: ConvergenceGateTarget[]
}

export interface ContinuityPlanWrite {
  name: string
  ordering_mode: ContinuityPlanOrderingMode
  lanes: ContinuityPlanLane[]
  nodes: ContinuityPlanNode[]
}

export interface ContinuityPlan extends ContinuityPlanWrite {
  id: number
  user_id: number
  created_at: string
  updated_at: string
}

export interface ContinuityPlanListItem {
  id: number
  name: string
  ordering_mode: ContinuityPlanOrderingMode
  lane_count: number
  step_count: number
  updated_at: string
}


export const continuityPlansApi = {
  list: (): Promise<ContinuityPlanListItem[]> =>
    api.get<ContinuityPlanListItem[]>('/v1/continuity-plans/'),
  create: (payload: ContinuityPlanWrite) =>
    api.post<ContinuityPlan, ContinuityPlanWrite>('/v1/continuity-plans/', payload),
  get: (planId: number) =>
    api.get<ContinuityPlan>(`/v1/continuity-plans/${planId}`),
  update: (planId: number, payload: ContinuityPlanWrite) =>
    api.put<ContinuityPlan, ContinuityPlanWrite>(`/v1/continuity-plans/${planId}`, payload),
  delete: (planId: number) =>
    api.delete<void>(`/v1/continuity-plans/${planId}`),
}
