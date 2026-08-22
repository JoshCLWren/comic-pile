import api from './api'
import type { ContinuityBlocker, UnreadIssueDetail } from './api-continuity-readiness'

export type ContinuityPlanNodeType = 'issue' | 'crossover' | 'thread'

export type ContinuityPlanOrderingMode = 'strict_sequential' | 'informational'

export interface ContinuityPlanLane {
  id: string
  name: string
  order: number
}

export interface ContinuityPlanNode {
  id: string
  node_type: ContinuityPlanNodeType
  ref_id: number
  lane_id: string
  position: number
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

export type PlanReadinessDiagnosticCode =
  | 'dangling_plan_reference'
  | 'plan_cycle_detected'
  | 'cycle_detected'
  | 'depth_limit_exceeded'
  | 'node_limit_exceeded'

export interface ContinuityPlanReadinessDiagnostic {
  code: PlanReadinessDiagnosticCode
  node_type: ContinuityPlanNodeType
  node_id: number
  limit?: number | null
}

export interface ContinuityPlanChainNode {
  node_type: 'issue' | 'crossover'
  node_id: number
  label: string
  is_readable: boolean
}

export interface ContinuityPlanNodeReadiness {
  node_id: string
  node_type: ContinuityPlanNodeType
  ref_id: number
  lane_id: string
  position: number
  label: string
  is_readable: boolean
  is_complete: boolean
  evaluated_issue_id?: number | null
  blockers: ContinuityBlocker[]
  diagnostics: ContinuityPlanReadinessDiagnostic[]
  chains: ContinuityPlanChainNode[][]
  readable_prerequisites: ContinuityPlanChainNode[]
}

export interface ContinuityPlanReadinessSummary {
  total: number
  readable: number
  blocked: number
  complete: number
  unavailable: number
}

export interface ContinuityPlanReadinessResponse {
  plan_id: number
  plan_name: string
  ordering_mode: ContinuityPlanOrderingMode
  lanes: ContinuityPlanLane[]
  nodes: ContinuityPlanNodeReadiness[]
  plan_diagnostics: ContinuityPlanReadinessDiagnostic[]
  summary: ContinuityPlanReadinessSummary
  generated_at: string
}

export type { ContinuityBlocker, UnreadIssueDetail }

export const continuityPlansApi = {
  create: (payload: ContinuityPlanWrite) =>
    api.post<ContinuityPlan, ContinuityPlanWrite>('/v1/continuity-plans/', payload),
  get: (planId: number) =>
    api.get<ContinuityPlan>(`/v1/continuity-plans/${planId}`),
  update: (planId: number, payload: ContinuityPlanWrite) =>
    api.put<ContinuityPlan, ContinuityPlanWrite>(`/v1/continuity-plans/${planId}`, payload),
  readiness: (planId: number): Promise<ContinuityPlanReadinessResponse> =>
    api.get<ContinuityPlanReadinessResponse>(`/v1/continuity-plans/${planId}/readiness`),
}
