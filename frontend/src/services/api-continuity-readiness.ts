import api from './api'

export type ContinuityReadinessNodeType = 'issue' | 'thread' | 'crossover'

export interface ContinuityBlocker {
  rule_id: number
  source_type: 'issue' | 'thread' | 'crossover'
  source_id: number
  source_label: string
  satisfaction_type: string
  satisfied: boolean
  causing_issue_ids: number[]
  causing_member_issue_ids: number[]
  note: string | null
}

export interface ContinuityReadinessResponse {
  node_type: ContinuityReadinessNodeType
  node_id: number
  is_readable: boolean
  evaluated_issue_id: number | null
  blockers: ContinuityBlocker[]
}

export const continuityReadinessApi = {
  evaluate: (
    nodeType: ContinuityReadinessNodeType,
    nodeId: number,
  ): Promise<ContinuityReadinessResponse> =>
    api.post<ContinuityReadinessResponse>('/v1/continuity/readiness', {
      node_type: nodeType,
      node_id: nodeId,
    }),
}
