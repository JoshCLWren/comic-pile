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

describe('remaining pure branches', () => {
  it('orders dependency graphs including issue parents, unknown nodes, and cycles', () => {
    const threads = [thread(1), thread(2), thread(3)]
    expect(getTopologicalPath(threads, [
      { id: 'issue-parent', source_id: -1, target_id: 2, source_parent_thread_id: 1, created_at: 'now' },
      { id: 'target-parent', source_id: 2, target_id: -2, target_parent_thread_id: 3, created_at: 'now' },
      { id: 'ignored', source_id: -3, target_id: 1, created_at: 'now' },
      { id: 'self', source_id: 1, target_id: 1, created_at: 'now' },
      { id: 'unknown', source_id: 99, target_id: 1, created_at: 'now' },
    ])).toHaveLength(3)
    expect(getTopologicalPath(threads.slice(0, 2), [
      { id: 'cycle-a', source_id: 1, target_id: 2, created_at: 'now' },
      { id: 'cycle-b', source_id: 2, target_id: 1, created_at: 'now' },
    ])).toHaveLength(2)
  })

  it('normalizes dice configuration values and builds the d10 geometry', () => {
    expect(DEFAULT_DICE_RENDER_CONFIG.global.tileSize).toBe(256)
    const config = getDiceRenderConfigForSides(10, {
      global: {
        ...DEFAULT_DICE_RENDER_CONFIG.global,
        tileSize: Number.NaN, uvInset: 2, fontScale: -1, d10AutoCenter: true,
        textColor: '', fontWeight: 'normal',
      },
      perSides: { 10: { tileSize: 512, d10TopOffsetX: 9 } },
    })
    expect(config.tileSize).toBe(512)
    expect(config.uvInset).toBe(0.25)
    expect(config.fontScale).toBe(0.1)
    expect(config.d10AutoCenter).toBe(true)
    expect(config.d10TopOffsetX).toBe(0.5)
    expect(config.textColor).toBe(DEFAULT_DICE_RENDER_CONFIG.global.textColor)
    const defaults = getDiceRenderConfigForSides(20, {
      global: { ...DEFAULT_DICE_RENDER_CONFIG.global, d10AutoCenter: false },
    })
    expect(defaults.d10AutoCenter).toBe(false)
    const geometry = buildD10Faces()
    expect(geometry.faces).toHaveLength(10)
    expect(geometry.faceNumbers).toEqual([1, 10, 2, 9, 3, 8, 4, 7, 5, 6])
  })

  it('falls back when dice configuration values are non-finite or non-boolean', () => {
    // L53 `if (!Number.isFinite(numeric))` — tileSize NaN with no side override (sides=20)
    const nanConfig = getDiceRenderConfigForSides(20, {
      global: { ...DEFAULT_DICE_RENDER_CONFIG.global, tileSize: Number.NaN },
    })
    expect(nanConfig.tileSize).toBe(DEFAULT_DICE_RENDER_CONFIG.global.tileSize)
    // L68 `typeof value === 'boolean' ? value : fallback` — non-boolean d10AutoCenter
    const boolConfig = getDiceRenderConfigForSides(6, {
      global: { ...DEFAULT_DICE_RENDER_CONFIG.global, d10AutoCenter: 'yes' as never },
    })
    expect(boolConfig.d10AutoCenter).toBe(false)
  })

  it('formats API errors for axios-like, native, and unknown failures', () => {
    expect(getApiErrorDetail({ response: { status: 422, data: { detail: 'invalid' } } })).toBe('invalid')
    expect(getApiErrorStatus({ response: { status: 422 } })).toBe(422)
    expect(getApiErrorStatus({ response: {} })).toBeNull()
    expect(getApiErrorDetail(new Error('Failed to fetch'))).toContain('Network error')
    expect(getApiErrorDetail(new Error('ordinary'))).toBe('ordinary')
    expect(getApiErrorDetail(null)).toBe('Unknown error')
  })
})

describe('nullish operand branches', () => {
  it('returns Unknown error for Axios errors with a nullish message and no detail', () => {
    // L27 `error.message ?? ''` and L30 `error.message ?? 'Unknown error'`
    expect(getApiErrorDetail({ isAxiosError: true, response: { status: 502, data: {} }, message: undefined })).toBe('Unknown error')
    expect(getApiErrorDetail({ isAxiosError: true, response: {}, message: undefined } as never)).toBe('Unknown error')
  })

  it('rejects oversized cumulative ranges and oversized dashed literals', () => {
    // L70 `if (result.length + rangeSize > MAX_ISSUES)`
    expect(() => parseIssueRange('1-5000,2-6000')).toThrow('Total issues would exceed')
    // L78 `if (trimmedPart.length > MAX_LITERAL_LENGTH)` inside the dashed-literal branch
    expect(() => parseIssueRange('A-' + 'x'.repeat(100))).toThrow('too long')
  })

  it('skips a negative target id without a parent thread id in topological sort', () => {
    // L32 `} else { return }` branch when target_id < 0 and no target_parent_thread_id
    const threads = [thread(1), thread(2)]
    const result = getTopologicalPath(threads, [
      { id: 'orphan-target', source_id: 1, target_id: -7, is_issue_level: true, created_at: 'now' },
      { id: 'real', source_id: 1, target_id: 2, created_at: 'now' },
    ])
    expect(result.map((t) => t.id)).toEqual([1, 2])
  })

  it('returns early when moving an issue id that is not present', () => {
    // L35 `if (issueIndex === -1)` in moveIssueByStep
    const issues = [issue(1), issue(2)]
    expect(moveIssueByStep(issues, 99, 'up')).toBe(issues)
  })

  it('updates a node layer to a deeper candidate when reached via a longer path', () => {
    // L97 `existingLayer === undefined || candidateLayer > existingLayer` — candidateLayer > existingLayer arm
    const deep = layoutGraph([thread(1), thread(2), thread(3)], [
      { id: 'first', source_id: 1, target_id: 3, created_at: 'now' },
      { id: 'second', source_id: 1, target_id: 2, created_at: 'now' },
      { id: 'deeper', source_id: 2, target_id: 3, created_at: 'now' },
    ], new Set())
    const node3 = deep.nodes.find((n) => n.id === 3)
    const node2 = deep.nodes.find((n) => n.id === 2)
    expect(node2).toBeDefined()
    expect(node3).toBeDefined()
    expect(node3!.y).toBeGreaterThan(node2!.y)
  })

  it('parses non-numeric issue strings and open-ended spans with null ends', () => {
    // L54 `Number.isNaN(parsed) ? null : parsed` — the null arm
    expect(issueStringToNumber('.')).toBeNull()
    // L271 `end ?? 'open'` — open-ended thread with no gates
    const openThread: Thread = { ...thread(1), total_issues: null }
    const entries = buildReadingOrderTimelineEntries({ thread: openThread, dependencies: [] })
    const span = entries.find((e) => e.kind === 'span')
    expect(span?.kind === 'span' && span.span.id).toBe('span-1-open')
    expect(span?.kind === 'span' && span.span.isOpenEnded).toBe(true)
  })

  it('falls back through nullish rating-thread metadata operands', () => {
    // L31 `metadata.id ?? metadata.thread_id ?? Number(threadId)` — both metadata ids nullish
    expect(buildRatingThread(7, null, { title: 'Meta', id: undefined, thread_id: undefined } as never)?.id).toBe(7)
    // L33 `metadata.format ?? sessionThread?.format ?? ''` — metadata.format and sessionThread both nullish
    expect(buildRatingThread(7, null, { title: 'Meta', format: undefined } as never)?.format).toBe('')
    // L61 `issues_remaining || 0` — issues_remaining falsy (0)
    expect(getProgressPercentage({ total_issues: 4, issues_remaining: 0 })).toBe(100)
    // L67 `if (!layer) return` — explosion layer absent
    document.getElementById('explosion-layer')?.remove()
    expect(() => createExplosion()).not.toThrow()
  })
})
