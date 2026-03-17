import type { Thread, FlowchartDependency } from '../types'

export function getTopologicalPath(
  threads: Thread[],
  dependencies: FlowchartDependency[],
  _startThreadId?: number
): Thread[] {
  // Build adjacency list
  const adj = new Map<number, number[]>()
  const inDegree = new Map<number, number>()
  
  threads.forEach(t => {
    adj.set(t.id, [])
    inDegree.set(t.id, 0)
  })

  // We only care about thread-level relationships for the high-level timeline, 
  // or we can aggregate issue-level ones.
  dependencies.forEach(dep => {
    // Map issue-level dependencies to thread-level
    let sourceId = dep.source_id
    let targetId = dep.target_id
    
    // If either ID is negative (issue node), map it to its owning thread
    if (sourceId < 0) {
      const sourceThread = threads.find(t => t.id === Math.abs(sourceId))
      if (sourceThread) sourceId = sourceThread.id
      else return // Skip if we can't find the owning thread
    }
    if (targetId < 0) {
      const targetThread = threads.find(t => t.id === Math.abs(targetId))
      if (targetThread) targetId = targetThread.id
      else return // Skip if we can't find the owning thread
    }
    
    // Skip if both map to the same thread (self-loop)
    if (sourceId === targetId) return
    
    if (adj.has(sourceId) && adj.has(targetId)) {
      adj.get(sourceId)!.push(targetId)
      inDegree.set(targetId, (inDegree.get(targetId) || 0) + 1)
    }
  })

  // Standard topological sort (Kahn's algorithm)
  const queue: number[] = []
  
  // If a startThreadId is provided, we might want to just find the path from there, 
  // but for a general view, we start with all 0 in-degree nodes.
  threads.forEach(t => {
    if (inDegree.get(t.id) === 0) {
      queue.push(t.id)
    }
  })

  const sorted: number[] = []
  
  while (queue.length > 0) {
    // For a better reading order, we could sort the queue by thread title or queue_position
    const current = queue.shift()!
    sorted.push(current)

    const neighbors = adj.get(current) || []
    for (const neighbor of neighbors) {
      const deg = inDegree.get(neighbor)! - 1
      inDegree.set(neighbor, deg)
      if (deg === 0) {
        queue.push(neighbor)
      }
    }
  }

  // Handle cycles (nodes left in graph with inDegree > 0)
  threads.forEach(t => {
    if ((inDegree.get(t.id) || 0) > 0 && !sorted.includes(t.id)) {
      sorted.push(t.id)
    }
  })

  return sorted
    .map(id => threads.find(t => t.id === id))
    .filter((t): t is Thread => t !== undefined)
}
