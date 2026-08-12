import { afterEach, describe, expect, it, vi } from 'vitest'
import { formatDate, formatDateTime, formatTime, formatTime24 } from '../utils/dateFormat'
import { parseIssueRange } from '../utils/issueParser'
import { getDependencyTooltip } from '../utils/dependencyHelpers'
import { layoutGraph } from '../utils/graphLayout'
import { reorderIssuesForDrop, moveIssueByStep, normalizeIssueOrder, applyIssueMutation, applyIssueMutations, getPendingIssueIds } from '../pages/QueuePage/issueUtils'
import { buildRatingThread, createExplosion, getProgressPercentage, mapSessionThreadToRatingThread } from '../pages/RollPage/utils'
import { getTopologicalPath } from '../utils/topologicalSort'
import { buildD10Faces } from '../components/d10Geometry'
import { DEFAULT_DICE_RENDER_CONFIG, getDiceRenderConfigForSides } from '../components/diceRenderConfig'
import { getApiErrorDetail, getApiErrorStatus } from '../utils/apiError'
import { buildReadingOrderTimelineEntries, issueStringToNumber } from '../utils/readingOrderTimeline'

afterEach(() => vi.useRealTimers())
import type { Dependency, Issue, Thread, FlowchartDependency } from '../types'

const issue = (id: number, status: 'read' | 'unread' = 'unread'): Issue => ({
  id, thread_id: 1, issue_number: String(id), status, read_at: status === 'read' ? '2024-01-01' : null, created_at: '2024-01-01',
})

const thread = (id: number): Thread => ({
  id, title: `Thread ${id}`, format: 'Comics', issues_remaining: 2, total_issues: 4,
  next_unread_issue_id: null, queue_position: id, status: 'active',
  is_blocked: id === 2, blocking_reasons: [], created_at: '2024-01-01', reading_progress: '50',
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
    expect(formatTime24('2024-01-02T13:04:00Z')).toBe(
      new Date('2024-01-02T13:04:00Z').toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }),
    )
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
    expect(parseIssueRange('1-2,1-2')).toBe(2)
    expect(() => parseIssueRange('0-9999,10000')).toThrow('Cannot create more')
    expect(() => parseIssueRange('2-1')).toThrow('cannot exceed')
    expect(parseIssueRange('Annual-2024')).toBe(1)
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
    const issueGraph = layoutGraph([thread(1)], [{ id: 'issue-edge', source_id: -10, target_id: 1, is_issue_level: true, created_at: 'now' }], new Set([1]), [
      { id: -10, title: null, x: 0, y: 0, isBlocked: false, isIssueNode: true, parentThreadId: 1 } as never,
    ])
    expect(issueGraph.edges[0]?.isIssueLevel).toBe(true)
    expect(issueGraph.edges[0]?.isBlocking).toBe(true)
    const incomplete = layoutGraph([thread(1)], [
      { id: 'missing-source', source_id: 99, target_id: 1, created_at: 'now' },
      { id: 'missing-target', source_id: 1, target_id: 99, created_at: 'now' },
    ], new Set())
    expect(incomplete.edges).toHaveLength(0)
    const issueOnly = layoutGraph([], [], new Set(), [
      { id: -1, title: 'Issue', x: 0, y: 0, isBlocked: true, isIssueNode: true },
    ])
    expect(issueOnly.nodes[0]?.isIssueNode).toBe(true)
    const converging = layoutGraph(
      [thread(1), thread(2), thread(3)],
      [
        { id: 'left-parent', source_id: 1, target_id: 3, created_at: 'now' },
        { id: 'right-parent', source_id: 2, target_id: 3, created_at: 'now' },
      ],
      new Set(),
    )
    const parentY = converging.nodes.find((node) => node.id === 1)?.y
    expect(converging.nodes.find((node) => node.id === 2)?.y).toBe(parentY)
    expect(converging.nodes.find((node) => node.id === 3)?.y).toBeGreaterThan(parentY ?? 0)
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
    expect(getProgressPercentage({ ...session, total_issues: 0, issues_remaining: 0 })).toBe(0)
    expect(getProgressPercentage({ ...session, total_issues: 4, issues_remaining: 0 })).toBe(100)
    expect(getProgressPercentage({ ...session, total_issues: 4, issues_remaining: 2 })).toBe(50)
    expect(getProgressPercentage({ ...session, total_issues: null, issues_remaining: 2 })).toBe(0)
    const explosion = createExplosion(10)
    expect(explosion).toHaveLength(10)
    expect(explosion.every((particle) => Number.isFinite(particle.x))).toBe(true)
  })
})

describe('topology utility', () => {
  it('returns every thread even when a cycle remains', () => {
    const result = getTopologicalPath(
      [thread(1), thread(2), thread(3)],
      [
        { id: 'a', source_id: 1, target_id: 2, created_at: 'now' },
        { id: 'b', source_id: 2, target_id: 1, created_at: 'now' },
      ],
    )
    expect(result).toHaveLength(3)
  })
})

describe('dice geometry and config', () => {
  it('builds geometry and rejects unsupported dice', () => {
    expect(buildD10Faces()).toHaveLength(10)
    expect(getDiceRenderConfigForSides(4)).toBe(DEFAULT_DICE_RENDER_CONFIG[4])
    expect(() => getDiceRenderConfigForSides(3)).toThrow('Unsupported die sides')
  })
})

describe('api error utilities', () => {
  it('handles axios-like and unknown error values', () => {
    expect(getApiErrorStatus({ response: { status: 409 } })).toBe(409)
    expect(getApiErrorStatus({})).toBeUndefined()
    expect(getApiErrorDetail({ response: { data: { detail: 'Nope' } } })).toBe('Nope')
    expect(getApiErrorDetail({ response: { data: { detail: { message: 'Nested' } } } })).toBe('Nested')
    expect(getApiErrorDetail({ response: { data: { detail: ['a', 'b'] } } })).toBe('a, b')
    expect(getApiErrorDetail(new Error('Boom'))).toBe('Boom')
    expect(getApiErrorDetail(null)).toBe('Unknown error')
  })
})

describe('reading order utilities', () => {
  it('parses numeric issue strings and builds timeline entries', () => {
    expect(issueStringToNumber('12')).toBe(12)
    expect(issueStringToNumber('12.5')).toBe(12.5)
    expect(issueStringToNumber('Annual')).toBeNull()
    const dependencies: Dependency[] = []
    const entries = buildReadingOrderTimelineEntries([thread(1), thread(2)], dependencies)
    expect(entries.length).toBeGreaterThan(0)
  })
})
