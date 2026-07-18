import { describe, expect, it, vi } from 'vitest'
import { formatDate, formatDateTime, formatTime, formatTime24 } from '../utils/dateFormat'
import { parseIssueRange } from '../utils/issueParser'
import { getDependencyTooltip } from '../utils/dependencyHelpers'
import { layoutGraph } from '../utils/graphLayout'
import { reorderIssuesForDrop, moveIssueByStep, normalizeIssueOrder, applyIssueMutation, applyIssueMutations, getPendingIssueIds } from '../pages/QueuePage/issueUtils'
import { buildRatingThread, createExplosion, getProgressPercentage, mapSessionThreadToRatingThread } from '../pages/RollPage/utils'
import type { Issue, Thread, FlowchartDependency } from '../types'

const issue = (id: number, status: 'read' | 'unread' = 'unread'): Issue => ({
  id, thread_id: 1, issue_number: String(id), status, read_at: status === 'read' ? '2024-01-01' : null, created_at: '2024-01-01',
})

const thread = (id: number): Thread => ({
  id, title: `Thread ${id}`, format: 'Comics', issues_remaining: 2, total_issues: 4,
  next_unread_issue_id: null, queue_position: id, status: 'active',
  is_blocked: id === 2, blocking_reasons: [], collection_id: null, created_at: '2024-01-01', reading_progress: '50',
})

describe('date and issue utilities', () => {
  it('formats valid values and handles empty or invalid values', () => {
    expect(formatDate(null)).toBe('')
    expect(formatDate('not a date')).toBe('')
    expect(formatTime(undefined)).toBe('')
    expect(formatTime('not a date')).toBe('')
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('not a date')).toBe('—')
    expect(formatTime24(null)).toBe('N/A')
    expect(formatTime24('not a date')).toBe('N/A')
    expect(formatDate('2024-01-02')).toContain('Jan')
    expect(formatTime('2024-01-02T13:04:00Z')).toMatch(/\d:04/)
    expect(formatDateTime('2024-01-02T13:04:00Z')).toContain('Jan')
    expect(formatTime24('2024-01-02T13:04:00Z')).toMatch(/13:04|07:04/)
  })

  it('parses ranges, literals, duplicates, and rejects unsafe ranges', () => {
    expect(parseIssueRange('1-3, Annual 1, 3')).toBe(4)
    expect(parseIssueRange('  , ½ ,  ')).toBe(1)
    expect(parseIssueRange('5a-7b')).toBe(1)
    expect(parseIssueRange('0-0')).toBe(1)
    expect(() => parseIssueRange('')).toThrow('cannot be empty')
    expect(() => parseIssueRange('5-2')).toThrow('cannot exceed')
    expect(parseIssueRange('-1-2')).toBe(1)
    expect(() => parseIssueRange('1-10001')).toThrow('too large')
    expect(() => parseIssueRange('x'.repeat(101))).toThrow('too long')
  })
})

describe('dependency and graph utilities', () => {
  it('formats dependency tooltips for both directions', () => {
    expect(getDependencyTooltip(undefined)).toBeNull()
    expect(getDependencyTooltip({ issue_id: 1, incoming: [], outgoing: [] })).toBeNull()
    expect(getDependencyTooltip({
      issue_id: 1,
      incoming: [{ dependency_id: 1, source_issue_id: 1, source_thread_id: 1, source_thread_title: 'A', source_issue_number: '1' }],
      outgoing: [{ dependency_id: 2, source_issue_id: 2, source_thread_id: 2, source_thread_title: 'B', source_issue_number: '2' }],
    })).toBe('Blocked by:\n ← A #1\nBlocking:\n → B #2')
  })

  it('lays out empty, thread, issue, disconnected, and cyclic graphs', () => {
    expect(layoutGraph([], [], new Set())).toEqual({ nodes: [], edges: [], width: 0, height: 0 })
    const deps: FlowchartDependency[] = [{ id: 'd', source_id: 1, target_id: 2, created_at: 'now' }]
    const result = layoutGraph([thread(1), thread(2), thread(3)], deps, new Set([2]), [
      { id: -10, title: 'Issue', x: 0, y: 0, isBlocked: false, isIssueNode: true, parentThreadId: 1 },
    ])
    expect(result.nodes).toHaveLength(4)
    expect(result.edges).toHaveLength(1)
    expect(result.nodes.find((node) => node.id === 2)?.isBlocked).toBe(true)
    expect(result.width).toBeGreaterThan(0)
    expect(result.height).toBeGreaterThan(0)
    expect(layoutGraph([thread(1), thread(2)], [{ id: 'x', source_id: 1, target_id: 2, created_at: 'now' }, { id: 'y', source_id: 2, target_id: 1, created_at: 'now' }], new Set()).nodes).toHaveLength(2)
  })
})

describe('issue mutation utilities', () => {
  it('reorders, moves, normalizes, mutates, and tracks pending issues', () => {
    const issues = [issue(1), issue(2), issue(3)]
    expect(reorderIssuesForDrop(issues, 1, 3).map((x) => x.id)).toEqual([2, 3, 1])
    expect(reorderIssuesForDrop(issues, 8, 3)).toBe(issues)
    expect(moveIssueByStep(issues, 2, 'up').map((x) => x.id)).toEqual([2, 1, 3])
    expect(moveIssueByStep(issues, 2, 'down').map((x) => x.id)).toEqual([1, 3, 2])
    expect(moveIssueByStep(issues, 1, 'up')).toBe(issues)
    expect(normalizeIssueOrder(issues, [3, 3, 9])).toEqual([3, 1, 2])
    expect(applyIssueMutation(issues, { id: 1, type: 'toggle', issueId: 1, nextStatus: 'read' })[0]?.status).toBe('read')
    expect(applyIssueMutation(issues, { id: 2, type: 'delete', issueId: 2 })).toHaveLength(2)
    expect(applyIssueMutation(issues, { id: 3, type: 'reorder', issueIds: [3, 1] }).map((x) => x.id)).toEqual([3, 1, 2])
    expect(applyIssueMutations(issues, [{ id: 1, type: 'delete', issueId: 1 }])).toHaveLength(2)
    expect(getPendingIssueIds([{ id: 1, type: 'delete', issueId: 1 }, { id: 2, type: 'toggle', issueId: 2, nextStatus: 'read' }], 'delete')).toEqual(new Set([1]))
  })
})

describe('roll utilities', () => {
  it('maps metadata fallback branches and progress values', () => {
    const session = { ...thread(4), issue_id: 7, issue_number: '7', next_issue_id: 8, next_issue_number: '8', last_rolled_result: 5 }
    expect(mapSessionThreadToRatingThread(session).id).toBe(4)
    expect(buildRatingThread(3, 6, { title: 'Meta', id: 9, format: 'Manga', result: 4 })?.id).toBe(9)
    expect(buildRatingThread(null, null, null, session)?.title).toBe('Thread 4')
    expect(buildRatingThread(4, null, null, session)?.id).toBe(4)
    expect(buildRatingThread(9, null, null, session)).toBeNull()
    expect(getProgressPercentage(null)).toBe(0)
    expect(getProgressPercentage({ total_issues: 0, issues_remaining: 0 })).toBe(0)
    expect(getProgressPercentage({ total_issues: 4, issues_remaining: 1 })).toBe(75)
  })

  it('creates an explosion and cleans particles', () => {
    vi.useFakeTimers()
    const layer = document.createElement('div')
    layer.id = 'explosion-layer'
    document.body.appendChild(layer)
    const random = vi.spyOn(Math, 'random').mockReturnValue(0.5)
    createExplosion()
    expect(layer.children).toHaveLength(50)
    vi.advanceTimersByTime(1000)
    expect(layer.children).toHaveLength(0)
    random.mockRestore()
    vi.useRealTimers()
  })
})
