import { describe, expect, it } from 'vitest'
import { getTopologicalPath } from '../utils/topologicalSort'
import type { Thread, FlowchartDependency } from '../types'

function makeThread(id: number, title: string = `Thread ${id}`): Thread {
  return {
    id,
    title,
    format: 'Comics',
    issues_remaining: 1,
    total_issues: null,
    next_unread_issue_id: null,
    reading_progress: null,
    queue_position: id,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    collection_id: null,
    created_at: '2024-01-01T00:00:00Z',
  }
}

function makeDep(
  source: number,
  target: number,
  isIssueLevel = false,
  sourceParentId?: number,
  targetParentId?: number
): FlowchartDependency {
  return {
    id: Math.random() * 1000000,
    source_id: source,
    target_id: target,
    is_issue_level: isIssueLevel,
    source_parent_thread_id: sourceParentId,
    target_parent_thread_id: targetParentId,
    created_at: '2024-01-01T00:00:00Z',
  }
}

describe('getTopologicalPath', () => {
  it('returns threads in topological order', () => {
    const threads = [makeThread(1), makeThread(2), makeThread(3)]
    const deps = [
      makeDep(1, 2), // 1 blocks 2
      makeDep(2, 3), // 2 blocks 3
    ]
    const result = getTopologicalPath(threads, deps)
    expect(result.map((t) => t.id)).toEqual([1, 2, 3])
  })

  it('handles threads with no dependencies', () => {
    const threads = [makeThread(1), makeThread(2), makeThread(3)]
    const deps: FlowchartDependency[] = []
    const result = getTopologicalPath(threads, deps)
    expect(result).toHaveLength(3)
    expect(result.map((t) => t.id).sort()).toEqual([1, 2, 3])
  })

  it('handles issue-level dependencies with parent thread IDs', () => {
    const threads = [makeThread(1), makeThread(2), makeThread(3)]
    const deps = [
      // Issue 10 in thread 1 blocks issue 20 in thread 2
      makeDep(-10, -20, true, 1, 2),
      makeDep(2, 3), // Thread 2 blocks thread 3
    ]
    const result = getTopologicalPath(threads, deps)
    expect(result.map((t) => t.id)).toEqual([1, 2, 3])
  })

  it('ignores issue-level dependencies without parent thread IDs', () => {
    const threads = [makeThread(1), makeThread(2)]
    const deps = [
      makeDep(-10, -20, true), // Missing parent thread IDs
    ]
    const result = getTopologicalPath(threads, deps)
    // Both threads have no dependencies, order depends on input order
    expect(result).toHaveLength(2)
    expect(result.map((t) => t.id).sort()).toEqual([1, 2])
  })

  it('handles cycles by including remaining threads', () => {
    const threads = [makeThread(1), makeThread(2), makeThread(3)]
    const deps = [
      makeDep(1, 2), // 1 blocks 2
      makeDep(2, 1), // 2 blocks 1 (cycle)
      makeDep(2, 3), // 2 blocks 3
    ]
    const result = getTopologicalPath(threads, deps)
    expect(result).toHaveLength(3)
  })

  it('deduplicates parallel edges', () => {
    const threads = [makeThread(1), makeThread(2)]
    const deps = [
      makeDep(1, 2),
      makeDep(1, 2), // Duplicate
    ]
    const result = getTopologicalPath(threads, deps)
    expect(result.map((t) => t.id)).toEqual([1, 2])
  })

  it('ignores self-loops', () => {
    const threads = [makeThread(1), makeThread(2)]
    const deps = [
      makeDep(1, 1), // Self-loop
      makeDep(1, 2),
    ]
    const result = getTopologicalPath(threads, deps)
    expect(result.map((t) => t.id)).toEqual([1, 2])
  })

  it('skips dependencies for unknown threads', () => {
    const threads = [makeThread(1), makeThread(2)]
    const deps = [
      makeDep(1, 99), // 99 doesn't exist
      makeDep(1, 2),
    ]
    const result = getTopologicalPath(threads, deps)
    expect(result.map((t) => t.id)).toEqual([1, 2])
  })

  it('handles complex dependency graph', () => {
    const threads = [makeThread(1), makeThread(2), makeThread(3), makeThread(4), makeThread(5)]
    const deps = [
      makeDep(1, 2),
      makeDep(1, 3),
      makeDep(2, 4),
      makeDep(3, 4),
      makeDep(4, 5),
    ]
    const result = getTopologicalPath(threads, deps)
    const ids = result.map((t) => t.id)
    // 1 must come before 2 and 3
    expect(ids.indexOf(1)).toBeLessThan(ids.indexOf(2))
    expect(ids.indexOf(1)).toBeLessThan(ids.indexOf(3))
    // 2 and 3 must come before 4
    expect(ids.indexOf(2)).toBeLessThan(ids.indexOf(4))
    expect(ids.indexOf(3)).toBeLessThan(ids.indexOf(4))
    // 4 must come before 5
    expect(ids.indexOf(4)).toBeLessThan(ids.indexOf(5))
  })
})