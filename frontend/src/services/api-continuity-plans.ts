import { defaultHttpClient, type HttpClient } from './httpClient'

export type ContinuityPlanNodeType = 'issue' | 'crossover' | 'thread'

export type ContinuityPlanOrderingMode = 'strict_sequential' | 'informational'

/** Reader-facing label for a plan's ordering mode. */
export function readingPlanModeLabel(
  mode: ContinuityPlanOrderingMode | string,
): 'Strict' | 'Informational' {
  return mode === 'strict_sequential' ? 'Strict' : 'Informational'
}

export type ContinuityPlanInferredGateKind = 'thread_entry' | 'reading_order'

export interface ExplicitReaderOrderMigrationContract {
  kind: 'explicit_reader_order'
  classification_family_keys: string[]
  selected_dependency_ids: number[]
  issue_ids: number[]
  edges: Array<[number, number]>
  issue_fingerprint: string
  edge_fingerprint: string
}

export interface ContinuityPlanLane {
  id: string
  name: string
  order: number
  inferred_gate_kind?: ContinuityPlanInferredGateKind | null
  migration_contract?: ExplicitReaderOrderMigrationContract | null
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
  source_paths?: string[] | null
  source_cbl_placements?: Array<{ source_path: string; position: number }> | null
  source_role?: 'core' | 'context/prelude' | 'epilogue' | 'unknown' | null
  source_confidence?: 'high' | 'medium' | 'low' | null
  source_explanation?: string | null
  source_story_arc_ids?: string[] | null
  source_target_story_arc_id?: string | null
  reader_role?: 'required/core' | 'recommended' | 'optional' | 'context/prelude' | 'aftermath/epilogue' | 'skipped/excluded' | null
  reader_optional?: boolean | null
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
  source_paths: string[]
  updated_at: string
}

export type ReadingPlanIssueAvailability = 'read' | 'available' | 'blocked' | 'later'

export interface ReadingPlanBlocker {
  issue_id: number
  thread_id: number
  thread_title: string
  issue_number: string
  explanation: string
}

export interface ReadingPlanReaderIssue {
  occurrence_id: string
  issue_id: number
  lane_id: string
  display_position: number
  label?: string | null
  reader_role?: string | null
  reader_optional?: boolean | null
  is_checkpoint?: boolean
  issue_number: string
  thread_id: number
  thread_title: string
  status: string
  availability: ReadingPlanIssueAvailability
  blockers: ReadingPlanBlocker[]
  source_paths: string[]
}

export interface ReadingPlanReaderLane {
  id: string
  name: string
  order: number
  issues: ReadingPlanReaderIssue[]
}

export interface ReadingPlanSourceSnapshot {
  id: number
  raw_source_path: string
  repository: string | null
  source_path: string | null
  revision_sha: string | null
  content_hash: string | null
  adopted_at: string | null
  recorded_at: string
}

export interface ReadingPlanReaderView {
  plan_id: number
  name: string
  ordering_mode: ContinuityPlanOrderingMode
  progress: { total_issues: number; read_issues: number }
  available_now: ReadingPlanReaderIssue[]
  blocked_next: ReadingPlanReaderIssue[]
  lanes: ReadingPlanReaderLane[]
  sources: ReadingPlanSourceSnapshot[]
}


/**
 * Build the continuity-plan service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every continuity-plan request.
 * @returns The continuity plans API bound to `client`.
 */
export function createContinuityPlansApi(client: HttpClient) {
  return {
    list: (): Promise<ContinuityPlanListItem[]> =>
      client.get<ContinuityPlanListItem[]>('/v1/continuity-plans/'),
    create: (payload: ContinuityPlanWrite) =>
      client.post<ContinuityPlan, ContinuityPlanWrite>('/v1/continuity-plans/', payload),
    get: (planId: number) =>
      client.get<ContinuityPlan>(`/v1/continuity-plans/${planId}`),
    getReader: (planId: number) =>
      client.get<ReadingPlanReaderView>(`/v1/continuity-plans/${planId}/reader`),
    update: (planId: number, payload: ContinuityPlanWrite) =>
      client.put<ContinuityPlan, ContinuityPlanWrite>(`/v1/continuity-plans/${planId}`, payload),
    delete: (planId: number) =>
      client.delete<void>(`/v1/continuity-plans/${planId}`),
  }
}

export const continuityPlansApi = createContinuityPlansApi(defaultHttpClient())
