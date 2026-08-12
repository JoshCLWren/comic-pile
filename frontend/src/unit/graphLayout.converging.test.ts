import { describe, expect, it } from 'vitest'
import type { FlowchartDependency, Thread } from '../types'
import { layoutGraph } from '../utils/graphLayout'

function thread(id: number): Thread {
  return {
    id,
    title: `Thread ${id}`,
    format: 'Comics',
    issues_remaining: 1,
    total_issues: 1,
    next_unread_issue_id: null,
    reading_progress: null,
    queue_position: id,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-08-12T00:00:00Z',
  }
}

describe('layoutGraph converging dependencies', () => {
  it('keeps an equal existing layer when two same-depth parents converge', () => {
    const dependencies: FlowchartDependency[] = [
      { id: 'left-parent', source_id: 1, target_id: 3, created_at: 'now' },
      { id: 'right-parent', source_id: 2, target_id: 3, created_at: 'now' },
    ]

    const layout = layoutGraph(
      [thread(1), thread(2), thread(3)],
      dependencies,
      new Set(),
    )

    const leftParent = layout.nodes.find((node) => node.id === 1)
    const rightParent = layout.nodes.find((node) => node.id === 2)
    const child = layout.nodes.find((node) => node.id === 3)

    expect(leftParent).toBeDefined()
    expect(rightParent).toBeDefined()
    expect(child).toBeDefined()
    expect(rightParent!.y).toBe(leftParent!.y)
    expect(child!.y).toBeGreaterThan(leftParent!.y)
  })
})
