import axios from 'axios'
import type {
  ContinuityPlanNode,
  ContinuityPlanNodeType,
  ContinuityPlanOrderingMode,
} from '../../services/api-continuity-plans'
import { isObject, isString } from '../../utils/runtimeChecks'

export const LAST_PLAN_KEY = 'comic-pile:last-continuity-plan'
export const DEFAULT_LANE_ID = 'main'
export const DEFAULT_LANE_NAME = 'Reading order'
export const DEFAULT_PLAN_NAME = 'My reading plan'

/** Planner node with editor display fields layered over the persisted plan node. */
export interface PlannerNode extends ContinuityPlanNode {
  label: string
  is_checkpoint?: boolean
  convergence_gate?: Array<{ node_type: ContinuityPlanNodeType; node_id: string }>
}

/** Editable reading lane. */
export interface PlannerLane {
  id: string
  name: string
  order: number
}

interface ConflictDetail {
  code?: string
  source_node_id?: string
  target_node_id?: string
}

/** Human-readable message for a load/save failure. */
export function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (isString(detail) && detail.trim()) return detail
  }
  return error instanceof Error && error.message ? error.message : fallback
}

/** Human-readable message for a plan save conflict, naming the involved steps when known. */
export function getConflictMessage(error: unknown, nodes: PlannerNode[]): string {
  if (!axios.isAxiosError(error)) {
    return error instanceof Error && error.message ? error.message : 'Unable to save this continuity plan.'
  }

  const detail = error.response?.data?.detail
  if (isString(detail) && detail.trim()) {
    return detail
  }

  if (detail && isObject(detail) && 'code' in detail) {
    // SAFETY: 'code' in detail narrows the object to the ConflictDetail discriminated shape before access.
    const conflict = detail as ConflictDetail
    if (conflict.code === 'plan_rule_conflict' || conflict.code === 'continuity_cycle') {
      const sourceId = conflict.source_node_id
      const targetId = conflict.target_node_id

      if (sourceId !== undefined && targetId !== undefined) {
        const sourceNode = nodes.find((node) => node.id === sourceId)
        const targetNode = nodes.find((node) => node.id === targetId)

        if (sourceNode && targetNode) {
          if (conflict.code === 'plan_rule_conflict') {
            return `You already require "${sourceNode.label}" before "${targetNode.label}". Change the sequence to resolve this conflict.`
          }
          return `This order would create a continuity cycle: "${sourceNode.label}" → "${targetNode.label}". Change the sequence to resolve this cycle.`
        }
      }

      if (conflict.code === 'plan_rule_conflict') {
        return 'This order conflicts with an existing continuity rule. Change the sequence and try again.'
      }
      return 'This order would create a continuity cycle. Change the sequence and try again.'
    }
  }

  return error instanceof Error && error.message ? error.message : 'Unable to save this continuity plan.'
}

/** Reassign contiguous 0-based positions per lane while preserving order. */
export function normalizePositions(nodeList: PlannerNode[]): PlannerNode[] {
  const byLane: Record<string, PlannerNode[]> = {}
  for (const node of nodeList) {
    ;(byLane[node.lane_id] ??= []).push(node)
  }
  const out: PlannerNode[] = []
  for (const laneId of Object.keys(byLane)) {
    const sorted = [...byLane[laneId]].sort((a, b) => a.position - b.position)
    sorted.forEach((node, index) => out.push({ ...node, position: index }))
  }
  return out
}

/** Build the save payload from editor draft state. */
export function buildPayload(
  name: string,
  lanes: PlannerLane[],
  nodeList: PlannerNode[],
  orderingMode: ContinuityPlanOrderingMode,
) {
  const normalized = normalizePositions(nodeList)
  const orderedLanes = [...lanes].sort((a, b) => a.order - b.order)
  return {
    name: name.trim(),
    ordering_mode: orderingMode,
    lanes: orderedLanes.map((lane) => ({ id: lane.id, name: lane.name, order: lane.order })),
    nodes: normalized.map((node) => ({
      id: node.id,
      node_type: node.node_type,
      ref_id: node.ref_id,
      lane_id: node.lane_id,
      position: node.position,
      label: node.label ?? null,
      is_checkpoint: node.is_checkpoint ?? false,
      convergence_gate: node.convergence_gate ?? [],
      source_role: node.source_role ?? null,
      source_confidence: node.source_confidence ?? null,
      source_explanation: node.source_explanation ?? null,
      source_paths: node.source_paths ?? null,
      source_cbl_placements: node.source_cbl_placements ?? null,
      source_story_arc_ids: node.source_story_arc_ids ?? null,
      source_target_story_arc_id: node.source_target_story_arc_id ?? null,
      reader_role: node.reader_role ?? null,
      reader_optional: node.reader_optional ?? null,
    })),
  }
}

/** Count nodes assigned to a lane. */
export function laneNodeCount(nodes: PlannerNode[], laneId: string): number {
  return nodes.filter((node) => node.lane_id === laneId).length
}
