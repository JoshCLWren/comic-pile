import type { Thread, FlowchartDependency } from '../types'

export function getTopologicalPath(
  threads: Thread[],
  dependencies: FlowchartDependency[],
): Thread[] {
  const threadById = new Map<number, Thread>(threads.map((t) => [t.id, t]))
  
  const adj = new Map<number, Set<number>>()
  const inDegree = new Map<number, number>()
  
  threads.forEach(t => {
    adj.set(t.id, new Set())
    inDegree.set(t.id, 0)
  })

  dependencies.forEach(dep => {
    let sourceId = dep.source_id
    let targetId = dep.target_id
    
    // If either ID is negative (issue node), use parent thread ID from the dependency
    if (sourceId < 0) {
      if (dep.source_parent_thread_id != null) {
        sourceId = dep.source_parent_thread_id
      } else {
        return
      }
    }
    if (targetId < 0) {
      if (dep.target_parent_thread_id != null) {
        targetId = dep.target_parent_thread_id
      } else {
        return
      }
    }
    
    if (sourceId === targetId) return
    
    if (adj.has(sourceId) && adj.has(targetId)) {
      const neighbors = adj.get(sourceId)!
      if (!neighbors.has(targetId)) {
        neighbors.add(targetId)
        inDegree.set(targetId, (inDegree.get(targetId) || 0) + 1)
      }
    }
  })

  // Standard topological sort (Kahn's algorithm)
  const queue: number[] = []
  
  threads.forEach(t => {
    if (inDegree.get(t.id) === 0) {
      queue.push(t.id)
    }
  })

  const sorted: number[] = []
  const sortedSet = new Set<number>()
  
  while (queue.length > 0) {
    // For a better reading order, we could sort the queue by thread title or queue_position
    const current = queue.shift()!
    sorted.push(current)
    sortedSet.add(current)

    const neighbors = adj.get(current)
    if (neighbors) {
      for (const neighbor of neighbors) {
        const deg = inDegree.get(neighbor)! - 1
        inDegree.set(neighbor, deg)
        if (deg === 0) {
          queue.push(neighbor)
        }
      }
    }
  }

  // Handle cycles (nodes left in graph with inDegree > 0)
  threads.forEach(t => {
    if ((inDegree.get(t.id) || 0) > 0 && !sortedSet.has(t.id)) {
      sorted.push(t.id)
      sortedSet.add(t.id)
    }
  })

  return sorted
    .map(id => threadById.get(id))
    .filter((t): t is Thread => t !== undefined)
}
