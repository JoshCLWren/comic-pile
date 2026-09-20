import type { Dependency, FlowchartDependency, FlowchartNode } from '../types'

/**
 * Pure flowchart graph derived from thread dependencies.
 */
export interface FlowchartGraph {
  /** Thread-level edges followed by issue-level edges, in render order. */
  edges: FlowchartDependency[]
  /** Virtual nodes for issues referenced by issue-level dependencies. */
  issueNodes: FlowchartNode[]
  /** Thread IDs that should be loaded to give the graph context. */
  relatedThreadIds: Set<number>
}

/**
 * Build the full graph of threads and dependencies for the flowchart.
 *
 * Synthesizes virtual thread-level edges from issue-level deps so they
 * show as dashed connections in the flowchart. Extracted verbatim from
 * DependencyBuilder so public behavior is unchanged.
 *
 * @param allDeps - Combined blocking and blocked-by dependencies.
 * @param currentThreadId - Thread the builder was opened for.
 * @returns Edges, virtual issue nodes, and related thread IDs.
 */
export function buildFlowchartGraph(
  allDeps: Dependency[],
  currentThreadId: number,
): FlowchartGraph {
  const relatedThreadIds = new Set([currentThreadId])

  // Thread-level deps map directly to FlowchartDependency
  const threadDeps: FlowchartDependency[] = allDeps.flatMap((dep) =>
    dep.source_thread_id != null && dep.target_thread_id != null && !dep.is_issue_level
      ? [{
          id: String(dep.id),
          source_id: dep.source_thread_id,
          target_id: dep.target_thread_id,
          created_at: dep.created_at,
        }]
      : [],
  )

  // Collect related thread IDs from thread-level deps
  for (const dep of threadDeps) {
    relatedThreadIds.add(dep.source_id)
    relatedThreadIds.add(dep.target_id)
  }

  // Issue-level deps → issue nodes + direct edges between them
  const issueOnlyDeps = allDeps.filter(
    (dep) => dep.source_issue_id != null && dep.target_issue_id != null,
  )
  const issueNodeMap = new Map<number, FlowchartNode>()
  const issueEdges: FlowchartDependency[] = []

  for (const d of issueOnlyDeps) {
    if (!d.source_issue_thread_id || !d.target_issue_thread_id) continue

    // Use negative issue ID to avoid thread ID collisions
    const srcNodeId = -d.source_issue_id!
    if (!issueNodeMap.has(srcNodeId)) {
      issueNodeMap.set(srcNodeId, {
        id: srcNodeId,
        title: d.source_label ?? `Issue #${d.source_issue_id}`,
        x: 0, y: 0,
        isBlocked: false,
        isIssueNode: true,
        parentThreadId: d.source_issue_thread_id,
      })
    }

    const tgtNodeId = -d.target_issue_id!
    if (!issueNodeMap.has(tgtNodeId)) {
      issueNodeMap.set(tgtNodeId, {
        id: tgtNodeId,
        title: d.target_label ?? `Issue #${d.target_issue_id}`,
        x: 0, y: 0,
        isBlocked: false,
        isIssueNode: true,
        parentThreadId: d.target_issue_thread_id,
      })
    }

    issueEdges.push({
      id: d.id,
      source_id: srcNodeId,
      target_id: tgtNodeId,
      is_issue_level: true,
      source_parent_thread_id: d.source_issue_thread_id,
      target_parent_thread_id: d.target_issue_thread_id,
      created_at: d.created_at,
    })

    // Ensure parent threads are loaded for context
    relatedThreadIds.add(d.source_issue_thread_id)
    relatedThreadIds.add(d.target_issue_thread_id)
  }

  return {
    edges: [...threadDeps, ...issueEdges],
    issueNodes: Array.from(issueNodeMap.values()),
    relatedThreadIds,
  }
}
