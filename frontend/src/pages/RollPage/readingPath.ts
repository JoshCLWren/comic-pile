import type { ReaderContextEdge } from '../../types'

/**
 * Reader-first orientation helpers for Reading Context continuity edges
 * (issue #1916).
 *
 * These functions are presentational only: they group and order the already
 * authoritative reader-context payload relative to the active rolled issue.
 * Readiness itself is never re-evaluated here; the verdict comes from the
 * server's continuity readiness API.
 */

export interface PathStep {
  /** Owned issue identifier used for stable keys and navigation. */
  issueId: number
  /** Human-readable comic identity, never a bare internal id. */
  label: string
  /** Thread identifier for deep-linking, when resolvable. */
  threadId: number | null
  /** Owned read status ("read"/"unread") or null when unresolvable. */
  status: string | null
  /** Explanations contributed by the edges that produced this step. */
  explanations: string[]
}

/**
 * Groups local-chain edges by their relationship to the current issue.
 *
 * Args:
 *   edges: One-hop dependency/continuity edges from the reader-context payload.
 *   currentIssueId: The active rolled issue's identifier.
 *
 * Returns:
 *   Edges whose target is the current issue (`intoCurrent`, prerequisites),
 *   edges whose source is the current issue (`fromCurrent`, downstream
 *   unlocks), and edges touching neither endpoint (`later`, future context).
 *   Degenerate self-loops on the current issue are ignored.
 */
export function classifyEdgesRelativeToCurrent(
  edges: ReaderContextEdge[],
  currentIssueId: number,
): { intoCurrent: ReaderContextEdge[]; fromCurrent: ReaderContextEdge[]; later: ReaderContextEdge[] } {
  const intoCurrent: ReaderContextEdge[] = []
  const fromCurrent: ReaderContextEdge[] = []
  const later: ReaderContextEdge[] = []
  for (const edge of edges) {
    const touchesSource = edge.source_issue_id === currentIssueId
    const touchesTarget = edge.target_issue_id === currentIssueId
    if (touchesSource && touchesTarget) {
      continue
    }
    if (touchesTarget) {
      intoCurrent.push(edge)
    } else if (touchesSource) {
      fromCurrent.push(edge)
    } else {
      later.push(edge)
    }
  }
  return { intoCurrent, fromCurrent, later }
}

function edgeSortKey(edge: ReaderContextEdge): (string | number)[] {
  return [edge.kind, edge.id]
}

function stepLabel(edge: ReaderContextEdge, position: 'source' | 'target'): string {
  const raw = position === 'source' ? edge.source_label : edge.target_label
  return raw ?? 'a missing issue'
}

function makeStep(edge: ReaderContextEdge, position: 'source' | 'target'): PathStep {
  return {
    issueId: position === 'source' ? edge.source_issue_id : edge.target_issue_id,
    label: stepLabel(edge, position),
    threadId: position === 'source' ? edge.source_thread_id : edge.target_thread_id,
    status: position === 'source' ? (edge.source_status ?? null) : (edge.target_status ?? null),
    explanations: [],
  }
}

/**
 * Builds truthful prerequisite lanes leading into the current issue.
 *
 * Each lane is ordered earliest-first and ends at the issue immediately
 * before the current one. Parallel prerequisites become separate lanes so
 * nothing is flattened into an invented linear order. Duplicate edges
 * between the same pair of issues collapse into one step, cycles terminate,
 * and traversal stays bounded by the payload's own edge cap.
 *
 * Args:
 *   edges: All local-chain edges; prerequisite edges are selected internally.
 *   currentIssueId: The active rolled issue's identifier.
 *
 * Returns:
 *   Deterministically ordered lanes of prerequisite steps.
 */
export function buildPrerequisiteLanes(
  edges: ReaderContextEdge[],
  currentIssueId: number,
): PathStep[][] {
  const incoming = new Map<number, ReaderContextEdge[]>()
  for (const edge of [...edges].sort((a, b) => compareKeys(edgeSortKey(a), edgeSortKey(b)))) {
    if (edge.source_issue_id === edge.target_issue_id) continue
    const bucket = incoming.get(edge.target_issue_id)
    if (bucket) {
      bucket.push(edge)
    } else {
      incoming.set(edge.target_issue_id, [edge])
    }
  }

  const visited = new Set<number>([currentIssueId])
  const lanes: PathStep[][] = []

  const makeLaneStep = (edge: ReaderContextEdge): PathStep => {
    const step = makeStep(edge, 'source')
    const bucket = incoming.get(edge.target_issue_id) ?? []
    step.explanations.push(...collectExplanations(bucket, edge.source_issue_id))
    return step
  }

  const walk = (firstEdge: ReaderContextEdge, prefix: PathStep[] = []) => {
    if (visited.has(firstEdge.source_issue_id)) return
    visited.add(firstEdge.source_issue_id)

    const steps: PathStep[] = [...prefix, makeLaneStep(firstEdge)]
    let cursor = firstEdge.source_issue_id

    while (true) {
      const candidates = (incoming.get(cursor) ?? []).filter(
        (candidate) => !visited.has(candidate.source_issue_id),
      )
      if (candidates.length === 0) break
      for (const fork of candidates.slice(1)) {
        walk(fork, [...steps])
      }
      const nextEdge = candidates[0]
      visited.add(nextEdge.source_issue_id)
      steps.push(makeLaneStep(nextEdge))
      cursor = nextEdge.source_issue_id
    }

    lanes.push([...steps].reverse())
  }

  for (const edge of incoming.get(currentIssueId) ?? []) {
    walk(edge)
  }
  return lanes
}

function collectExplanations(bucket: ReaderContextEdge[], sourceIssueId: number): string[] {
  const copies: string[] = []
  for (const edge of bucket) {
    if (edge.source_issue_id !== sourceIssueId) continue
    const copy = edge.explanation ?? edge.note
    if (copy && !copies.includes(copy)) copies.push(copy)
  }
  return copies
}

function compareKeys(a: (string | number)[], b: (string | number)[]): number {
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] < b[index]) return -1
    if (a[index] > b[index]) return 1
  }
  return a.length - b.length
}
