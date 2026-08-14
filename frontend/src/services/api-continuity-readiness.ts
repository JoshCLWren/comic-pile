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

export type ContinuityChainNodeType = 'issue' | 'crossover'

export type ContinuityChainDiagnosticCode =
  | 'cycle_detected'
  | 'depth_limit_exceeded'
  | 'node_limit_exceeded'

export interface ContinuityChainNode {
  node_type: ContinuityChainNodeType
  node_id: number
  label: string
  is_readable: boolean
}

export interface ContinuityChainDiagnostic {
  code: ContinuityChainDiagnosticCode
  node_type: ContinuityChainNodeType
  node_id: number
  limit: number | null
}

export interface ContinuityChainResponse {
  node_type: ContinuityReadinessNodeType
  node_id: number
  evaluated_issue_id: number | null
  direct_blockers: ContinuityBlocker[]
  chains: ContinuityChainNode[][]
  readable_prerequisites: ContinuityChainNode[]
  diagnostics: ContinuityChainDiagnostic[]
}

interface ContinuityNodeRequest {
  node_type: ContinuityReadinessNodeType
  node_id: number
}

export const continuityReadinessApi = {
  evaluate: (
    nodeType: ContinuityReadinessNodeType,
    nodeId: number,
  ): Promise<ContinuityReadinessResponse> =>
    api.post<ContinuityReadinessResponse>('/v1/continuity/readiness', {
      node_type: nodeType,
      node_id: nodeId,
    } satisfies ContinuityNodeRequest),

  resolveChains: (
    nodeType: ContinuityReadinessNodeType,
    nodeId: number,
  ): Promise<ContinuityChainResponse> =>
    api.post<ContinuityChainResponse>('/v1/continuity/chains', {
      node_type: nodeType,
      node_id: nodeId,
    } satisfies ContinuityNodeRequest),
}
