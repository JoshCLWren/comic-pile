import { describe, expect, it, vi } from 'vitest'
import { fetchAllUnreadIssues } from '../hooks/useDependencyBuilderData'
import type { DependencyBuilderIssuesApi } from '../hooks/useDependencyBuilderData'
import { buildFlowchartGraph } from '../utils/dependencyFlowchartAdapter'
import type { Dependency, Issue } from '../types'

function makeThreadDep(id: number, sourceThreadId: number | null, targetThreadId: number | null): Dependency {
  return {
    id,
    source_thread_id: sourceThreadId,
    target_thread_id: targetThreadId,
    source_issue_id: null,
    target_issue_id: null,
    is_issue_level: false,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function makeIssueDep(
  id: number,
  sourceIssueId: number | null,
  targetIssueId: number | null,
  sourceThreadId?: number | null,
  targetThreadId?: number | null,
): Dependency {
  return {
    id,
    source_thread_id: null,
    target_thread_id: null,
    source_issue_id: sourceIssueId,
    target_issue_id: targetIssueId,
    is_issue_level: true,
    created_at: '2026-01-01T00:00:00Z',
    source_label: sourceIssueId == null ? null : `Source #${sourceIssueId}`,
    target_label: targetIssueId == null ? null : `Target #${targetIssueId}`,
    source_issue_thread_id: sourceThreadId,
    target_issue_thread_id: targetThreadId,
  }
}

function makeIssue(id: number): Issue {
  return {
    id,
    thread_id: 7,
    issue_number: String(id),
    status: 'unread',
    read_at: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('buildFlowchartGraph', () => {
  it('maps thread-level deps to string-id edges and collects related threads', () => {
    const graph = buildFlowchartGraph([makeThreadDep(4, 1, 2)], 1)

    expect(graph.edges).toEqual([
      { id: '4', source_id: 1, target_id: 2, created_at: '2026-01-01T00:00:00Z' },
    ])
    expect(graph.issueNodes).toEqual([])
    expect(graph.relatedThreadIds).toEqual(new Set([1, 2]))
  })

  it('skips issue-level and null-thread deps when building thread edges', () => {
    const issueFlagged: Dependency = { ...makeThreadDep(5, 1, 3), is_issue_level: true }
    const graph = buildFlowchartGraph(
      [issueFlagged, makeThreadDep(6, null, 3), makeThreadDep(7, 1, 2)],
      9,
    )

    expect(graph.edges).toEqual([
      { id: '7', source_id: 1, target_id: 2, created_at: '2026-01-01T00:00:00Z' },
    ])
    expect(graph.relatedThreadIds).toEqual(new Set([9, 1, 2]))
  })

  it('builds negative-id issue nodes with parent context and renders thread edges first', () => {
    const graph = buildFlowchartGraph(
      [makeThreadDep(4, 1, 2), makeIssueDep(8, 11, 12, 1, 2)],
      1,
    )

    expect(graph.edges[0]).toMatchObject({ id: '4', source_id: 1, target_id: 2 })
    expect(graph.edges[1]).toMatchObject({
      id: 8,
      source_id: -11,
      target_id: -12,
      is_issue_level: true,
      source_parent_thread_id: 1,
      target_parent_thread_id: 2,
    })
    expect(graph.issueNodes).toEqual([
      {
        id: -11,
        title: 'Source #11',
        x: 0,
        y: 0,
        isBlocked: false,
        isIssueNode: true,
        parentThreadId: 1,
      },
      {
        id: -12,
        title: 'Target #12',
        x: 0,
        y: 0,
        isBlocked: false,
        isIssueNode: true,
        parentThreadId: 2,
      },
    ])
    expect(graph.relatedThreadIds).toEqual(new Set([1, 2]))
  })

  it('skips issue deps that lack parent thread context', () => {
    const graph = buildFlowchartGraph(
      [makeIssueDep(8, 11, 12, 1, null), makeIssueDep(9, 13, 14, 1, 2)],
      1,
    )

    expect(graph.edges).toHaveLength(1)
    expect(graph.edges[0]).toMatchObject({ id: 9 })
    expect(graph.issueNodes.map((node) => node.id)).toEqual([-13, -14])
  })
})

describe('fetchAllUnreadIssues', () => {
  function mockIssuesService(pages: { issues: Issue[]; next_page_token: string | null }[]): DependencyBuilderIssuesApi {
    return {
      list: vi.fn()
        .mockResolvedValueOnce({ issues: pages[0].issues, total_count: 1, page_size: 100, next_page_token: pages[0].next_page_token })
        .mockResolvedValueOnce(pages.length > 1
          ? { issues: pages[1].issues, total_count: 1, page_size: 100, next_page_token: pages[1].next_page_token }
          : { issues: [], total_count: 0, page_size: 100, next_page_token: null }),
      migrateThread: vi.fn(),
    }
  }

  it('follows pagination tokens across pages', async () => {
    const service = mockIssuesService([
      { issues: [makeIssue(1)], next_page_token: 'token-1' },
      { issues: [makeIssue(2)], next_page_token: null },
    ])

    await expect(fetchAllUnreadIssues(service, 7)).resolves.toEqual([makeIssue(1), makeIssue(2)])
    expect(service.list).toHaveBeenCalledTimes(2)
    expect(service.list).toHaveBeenNthCalledWith(1, 7, { status: 'unread', page_size: 100 })
    expect(service.list).toHaveBeenNthCalledWith(2, 7, { status: 'unread', page_size: 100, page_token: 'token-1' })
  })

  it('stops when the API repeats a page token', async () => {
    const service: DependencyBuilderIssuesApi = {
      list: vi.fn().mockResolvedValue({
        issues: [makeIssue(1)],
        total_count: 1,
        page_size: 100,
        next_page_token: 'stuck',
      }),
      migrateThread: vi.fn(),
    }

    await expect(fetchAllUnreadIssues(service, 7)).resolves.toEqual([makeIssue(1), makeIssue(1)])
    expect(service.list).toHaveBeenCalledTimes(2)
  })
})
