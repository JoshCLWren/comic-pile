import type { Dependency, FlowchartDependency, FlowchartNode, Thread } from '../types'

export interface FlowchartData {
  threads: Thread[]
  dependencies: FlowchartDependency[]
  issueNodes: FlowchartNode[]
  blockedIds: Set<number>
}

export interface ThreadDependenciesData {
  blocking: Dependency[]
  blocked_by: Dependency[]
}

function makeFlowchartNodeFromDependency(
  dep: Dependency,
  labelKey: 'source_label' | 'target_label',
): FlowchartNode | null {
  const issueId = labelKey === 'source_label' ? dep.source_issue_id : dep.target_issue_id
  const threadId = labelKey === 'source_label' ? dep.source_issue_thread_id : dep.target_issue_thread_id
  const label = dep[labelKey]
  
  if (issueId == null || threadId == null) return null
  
  return {
    id: -issueId,
    title: label ?? `Issue #${issueId}`,
    x: 0,
    y: 0,
    isBlocked: false,
    isIssueNode: true,
    parentThreadId: threadId,
  }
}

export function buildFlowchartEdgesFromDependencies(
  dependencies: Dependency[],
): FlowchartDependency[] {
  return dependencies
    .filter((dep) => 
      dep.source_thread_id != null && 
      dep.target_thread_id != null && 
      !dep.is_issue_level
    )
    .map((dep) => ({
      id: String(dep.id),
      source_id: dep.source_thread_id,
      target_id: dep.target_thread_id,
      created_at: dep.created_at,
    }))
}

export function buildFlowchartEdgesFromIssueDependencies(
  dependencies: Dependency[],
): FlowchartDependency[] {
  return dependencies
    .filter((dep) => 
      dep.source_issue_id != null && 
      dep.target_issue_id != null
    )
    .map((dep) => ({
      id: dep.id,
      source_id: -dep.source_issue_id!,
      target_id: -dep.target_issue_id!,
      is_issue_level: true,
      source_parent_thread_id: dep.source_issue_thread_id,
      target_parent_thread_id: dep.target_issue_thread_id,
      created_at: dep.created_at,
    }))
}

export function buildIssueNodesFromDependencies(
  dependencies: Dependency[],
): Map<number, FlowchartNode> {
  const nodeMap = new Map<number, FlowchartNode>()
  
  for (const dep of dependencies) {
    if (dep.source_issue_id != null && dep.source_issue_thread_id != null) {
      const nodeId = -dep.source_issue_id
      if (!nodeMap.has(nodeId)) {
        nodeMap.set(nodeId, {
          id: nodeId,
          title: dep.source_label ?? `Issue #${dep.source_issue_id}`,
          x: 0,
          y: 0,
          isBlocked: false,
          isIssueNode: true,
          parentThreadId: dep.source_issue_thread_id,
        })
      }
    }
    
    if (dep.target_issue_id != null && dep.target_issue_thread_id != null) {
      const nodeId = -dep.target_issue_id
      if (!nodeMap.has(nodeId)) {
        nodeMap.set(nodeId, {
          id: nodeId,
          title: dep.target_label ?? `Issue #${dep.target_issue_id}`,
          x: 0,
          y: 0,
          isBlocked: false,
          isIssueNode: true,
          parentThreadId: dep.target_issue_thread_id,
        })
      }
    }
  }
  
  return nodeMap
}

export function extractRelatedThreadIds(
  threadDeps: FlowchartDependency[],
  issueEdges: FlowchartDependency[],
  currentThreadId: number,
): Set<number> {
  const relatedIds = new Set<number>([currentThreadId])
  
  for (const dep of threadDeps) {
    relatedIds.add(dep.source_id)
    relatedIds.add(dep.target_id)
  }
  
  for (const edge of issueEdges) {
    if (edge.source_parent_thread_id != null) {
      relatedIds.add(edge.source_parent_thread_id)
    }
    if (edge.target_parent_thread_id != null) {
      relatedIds.add(edge.target_parent_thread_id)
    }
  }
  
  return relatedIds
}

export function adaptThreadForFlowchart(
  thread: Thread,
): Thread {
  return {
    ...thread,
    total_issues: thread.total_issues ?? 0,
  }
}

export function mapThreadIdsToNodes(
  threads: Thread[],
  blockedIds: Set<number>,
): Map<number, Thread> {
  return new Map(threads.map((t) => [t.id, t]))
}

export function filterThreadsByIds(
  threads: Thread[],
  ids: Set<number>,
): Thread[] {
  return threads.filter((t) => ids.has(t.id))
}

export function adaptThreadDependenciesForFlowchart(
  depsData: ThreadDependenciesData,
  blockedIds: number[],
): {
  threadDeps: FlowchartDependency[]
  issueEdges: FlowchartDependency[]
  allBlockedIds: Set<number>
} {
  const allBlockedIds = new Set(blockedIds)
  const threadDeps = buildFlowchartEdgesFromDependencies([...depsData.blocking, ...depsData.blocked_by])
  const issueEdges = buildFlowchartEdgesFromIssueDependencies([...depsData.blocking, ...depsData.blocked_by])
  
  return { threadDeps, issueEdges, allBlockedIds }
}