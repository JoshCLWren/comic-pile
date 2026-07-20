import { describe, expect, it } from 'vitest'
import { buildReadingOrderTimelineEntries, extractIssueNumber, issueStringToNumber } from '../utils/readingOrderTimeline'
import type { Dependency, Thread } from '../types'

function makeThread(overrides: Partial<Thread> = {}): Thread {
  return {
    id: overrides.id ?? 1,
    title: overrides.title ?? 'Planetary',
    format: overrides.format ?? 'Issues',
    issues_remaining: overrides.issues_remaining ?? 10,
    total_issues: overrides.total_issues !== undefined ? overrides.total_issues : 27,
    next_unread_issue_id: overrides.next_unread_issue_id ?? 1010,
    next_unread_issue_number: overrides.next_unread_issue_number ?? '10',
    reading_progress: overrides.reading_progress ?? null,
    queue_position: overrides.queue_position ?? 1,
    status: overrides.status ?? 'active',
    is_blocked: overrides.is_blocked ?? false,
    blocking_reasons: overrides.blocking_reasons ?? [],
    collection_id: overrides.collection_id ?? null,
    notes: overrides.notes ?? null,
    created_at: overrides.created_at ?? '2024-01-01T00:00:00Z',
  }
}

function makeDependency(overrides: Partial<Dependency>): Dependency {
  return {
    id: overrides.id ?? 1,
    source_thread_id: overrides.source_thread_id ?? 2,
    target_thread_id: overrides.target_thread_id ?? null,
    source_issue_id: overrides.source_issue_id ?? 555,
    target_issue_id: overrides.target_issue_id ?? 1001,
    is_issue_level: true,
    created_at: overrides.created_at ?? '2024-01-01T00:00:00Z',
    source_label: overrides.source_label ?? 'Stormwatch #11',
    target_label: overrides.target_label ?? 'Planetary #10',
    source_issue_thread_id: overrides.source_issue_thread_id ?? 2,
    target_issue_thread_id: overrides.target_issue_thread_id ?? 1,
  }
}

describe('buildReadingOrderTimelineEntries', () => {
  it('parses issue labels and numeric fallbacks', () => {
    expect(extractIssueNumber(null)).toBeNull()
    expect(extractIssueNumber('Annual')).toBeNull()
    expect(extractIssueNumber('Series # 12')).toBe('12')
    expect(extractIssueNumber('Series #')).toBeNull()
    expect(issueStringToNumber(undefined)).toBeNull()
    expect(issueStringToNumber('Annual 1.5')).toBe(1.5)
    expect(issueStringToNumber('Annual')).toBeNull()
  })
  it('creates spans and gates with correct statuses', () => {
    const thread = makeThread({ total_issues: 30, next_unread_issue_number: '10', next_unread_issue_id: 1010 })
    const dependencies: Dependency[] = [
      makeDependency({ id: 1, target_issue_id: 1010, target_label: 'Planetary #10', source_label: 'Stormwatch #11' }),
      makeDependency({ id: 2, target_issue_id: 1016, target_label: 'Planetary #16', source_label: 'Authority #9' }),
    ]

    const entries = buildReadingOrderTimelineEntries({ thread, dependencies })

    expect(entries).toHaveLength(4)
    expect(entries[0].kind).toBe('span')
    expect(entries[1].kind).toBe('gate')
    expect(entries[1].kind === 'gate' && entries[1].gate.status).toBe('blocked')
    expect(entries[1].kind === 'gate' && entries[1].gate.isCurrent).toBe(true)
    expect(entries[2].kind).toBe('gate')
    expect(entries[2].kind === 'gate' && entries[2].gate.status).toBe('dormant')
    expect(entries[2].kind === 'gate' && entries[2].gate.isCurrent).toBe(false)
    expect(entries[3].kind === 'span' && entries[3].span.label).toBe('Issues 17–30')
  })

  it('returns a single span when no gates exist', () => {
    const thread = makeThread({ total_issues: 12, next_unread_issue_number: '3', next_unread_issue_id: 1003 })
    const entries = buildReadingOrderTimelineEntries({ thread, dependencies: [] })
    expect(entries).toHaveLength(1)
    expect(entries[0].kind).toBe('span')
    expect(entries[0].kind === 'span' && entries[0].span.label).toBe('Issues 1–12')
  })

  it('marks gates as satisfied once the thread is complete', () => {
    const thread = makeThread({ issues_remaining: 0, next_unread_issue_number: null, next_unread_issue_id: null })
    const entries = buildReadingOrderTimelineEntries({
      thread,
      dependencies: [makeDependency({ id: 42, target_issue_id: 1005, target_label: 'Planetary #5' })],
    })
    expect(entries[1].kind === 'gate' && entries[1].gate.status).toBe('satisfied')
  })

  it('marks earlier gates satisfied and uses id matching when labels are unavailable', () => {
    const earlier = buildReadingOrderTimelineEntries({
      thread: makeThread({ total_issues: 20, next_unread_issue_number: '10', next_unread_issue_id: 1010 }),
      dependencies: [makeDependency({ target_issue_id: 1005, target_label: 'Planetary #5' })],
    })
    expect(earlier.find((entry) => entry.kind === 'gate')?.kind === 'gate' && earlier.find((entry) => entry.kind === 'gate')?.gate.status).toBe('satisfied')

    const idMatched = buildReadingOrderTimelineEntries({
      thread: makeThread({ total_issues: null, next_unread_issue_number: 'Special', next_unread_issue_id: 1005 }),
      dependencies: [makeDependency({ target_issue_id: 1005, target_label: 'Special' })],
    })
    expect(idMatched.find((entry) => entry.kind === 'gate')?.kind === 'gate' && idMatched.find((entry) => entry.kind === 'gate')?.gate.status).toBe('blocked')
  })

  it('groups multiple gates at the same issue', () => {
    const thread = makeThread({ total_issues: 10, next_unread_issue_number: '6', next_unread_issue_id: 1006 })
    const dependencies: Dependency[] = [
      makeDependency({ id: 1, target_issue_id: 1006, target_label: 'Planetary #6', source_label: 'Stormwatch #11' }),
      makeDependency({ id: 2, target_issue_id: 1006, target_label: 'Planetary #6', source_label: 'Authority #9' }),
    ]

    const entries = buildReadingOrderTimelineEntries({ thread, dependencies })
    // Should have: span (1-5), one grouped gate for #6, span (7-10)
    expect(entries).toHaveLength(3)
    expect(entries[0].kind).toBe('span')
    expect(entries[0].kind === 'span' && entries[0].span.label).toBe('Issues 1–5')
    expect(entries[1].kind).toBe('gate')
    const gate = entries[1].kind === 'gate' ? entries[1].gate : null
    expect(gate).not.toBeNull()
    if (gate) {
      expect(gate.targetIssueId).toBe(1006)
      expect(gate.prerequisiteLabels).toHaveLength(2)
      expect(gate.prerequisiteLabels).toContain('Stormwatch #11')
      expect(gate.prerequisiteLabels).toContain('Authority #9')
      expect(gate.status).toBe('blocked')
    }
    expect(entries[2].kind).toBe('span')
    expect(entries[2].kind === 'span' && entries[2].span.label).toBe('Issues 7–10')
  })

  it('renders an open-ended span when total_issues is null and no gates exist', () => {
    const thread = makeThread({
      total_issues: null,
      next_unread_issue_number: '5',
      next_unread_issue_id: 1005,
    })
    const entries = buildReadingOrderTimelineEntries({ thread, dependencies: [] })
    expect(entries).toHaveLength(1)
    expect(entries[0].kind).toBe('span')
    const span = entries[0].kind === 'span' ? entries[0].span : null
    expect(span).not.toBeNull()
    if (span) {
      expect(span.label).toBe('Issues 1+')
      expect(span.isOpenEnded).toBe(true)
    }
  })

  it('renders an open-ended trailing span when total_issues is null and gates exist', () => {
    const thread = makeThread({
      total_issues: null,
      next_unread_issue_number: '5',
      next_unread_issue_id: 1005,
    })
    const dependencies: Dependency[] = [
      makeDependency({ id: 1, target_issue_id: 1005, target_label: 'Planetary #5', source_label: 'Stormwatch #11' }),
    ]
    const entries = buildReadingOrderTimelineEntries({ thread, dependencies })
    // span before the gate (1–4), gate at #5, then an open-ended span from #6 onward
    expect(entries).toHaveLength(3)
    expect(entries[0].kind).toBe('span')
    expect(entries[0].kind === 'span' && entries[0].span.label).toBe('Issues 1–4')
    expect(entries[1].kind).toBe('gate')
    expect(entries[2].kind).toBe('span')
    const span = entries[2].kind === 'span' ? entries[2].span : null
    expect(span).not.toBeNull()
    if (span) {
      expect(span.label).toBe('Issues 6+')
      expect(span.isOpenEnded).toBe(true)
    }
  })

  it('handles a zero-indexed next_unread_issue_number', () => {
    const thread = makeThread({
      total_issues: 10,
      next_unread_issue_number: '0',
      next_unread_issue_id: 1000,
    })
    const dependencies: Dependency[] = [
      makeDependency({ id: 1, target_issue_id: 1000, target_label: 'Planetary #0', source_label: 'Stormwatch #11' }),
    ]
    const entries = buildReadingOrderTimelineEntries({ thread, dependencies })
    // gate at #0 is the first gate; no span before it (0 is not > 1), then span 1–10
    expect(entries.length).toBeGreaterThanOrEqual(1)
    const gate = entries.find((e) => e.kind === 'gate')
    expect(gate).toBeDefined()
    expect(gate?.kind === 'gate' && gate.gate.issueNumberValue).toBe(0)
  })

  it('handles non-numeric labels, id fallbacks, and dormant gates', () => {
    const thread = makeThread({ total_issues: 3, next_unread_issue_number: null, next_unread_issue_id: 999 })
    const entries = buildReadingOrderTimelineEntries({
      thread,
      dependencies: [
        makeDependency({ id: 1, target_issue_id: 20, target_label: 'Special', source_label: null }),
        makeDependency({ id: 2, target_issue_id: 21, target_label: 'Special', source_label: 'Other' }),
        makeDependency({ id: 3, target_issue_thread_id: 88, target_issue_id: 22, target_label: 'Other #2', source_label: 'Ignored' }),
      ],
    })
    const gates = entries.filter((entry) => entry.kind === 'gate')
    expect(gates).toHaveLength(2)
    expect(gates.every((entry) => entry.kind === 'gate' && entry.gate.status === 'dormant')).toBe(true)
    expect(gates[0]?.kind === 'gate' && gates[0].gate.prerequisiteLabels).toEqual(['Stormwatch #11'])
  })

  it('uses safe labels when dependency metadata is absent', () => {
    const thread = makeThread({ total_issues: 4, next_unread_issue_number: null, next_unread_issue_id: null })
    const dependency = {
      ...makeDependency({ target_issue_id: 20 }),
      source_label: 'Source',
      target_label: null,
    }
    const entries = buildReadingOrderTimelineEntries({ thread, dependencies: [dependency] })
    const gate = entries.find((entry) => entry.kind === 'gate')
    expect(gate?.kind === 'gate' && gate.gate.targetLabel).toBe('Issue gate')
    expect(gate?.kind === 'gate' && gate.gate.prerequisiteLabels).toEqual(['Source'])
  })

  it('uses fallback issue ids to identify the current gate', () => {
    const thread = makeThread({ total_issues: null, next_unread_issue_number: 'Special', next_unread_issue_id: 44 })
    const entries = buildReadingOrderTimelineEntries({
      thread,
      dependencies: [makeDependency({ target_issue_id: 44, target_label: 'Special', source_label: 'Source' })],
    })
    const gate = entries.find((entry) => entry.kind === 'gate')
    expect(gate?.kind === 'gate' && gate.gate.status).toBe('blocked')
  })

  it('orders labelled, unnumbered, and equal gates deterministically', () => {
    const thread = makeThread({ total_issues: 2, next_unread_issue_number: '1', next_unread_issue_id: 999 })
    const dependencies = [
      makeDependency({ id: 1, target_issue_id: 1, target_label: 'Target #1', source_label: 'A' }),
      makeDependency({ id: 2, target_issue_id: 2, target_label: 'Target', source_label: 'B' }),
      makeDependency({ id: 3, target_issue_id: 3, target_label: 'Target', source_label: 'C' }),
      makeDependency({ id: 4, target_issue_id: 4, target_label: 'Target #1', source_label: 'D' }),
    ]
    const entries = buildReadingOrderTimelineEntries({ thread, dependencies })
    expect(entries.filter((entry) => entry.kind === 'gate')).toHaveLength(4)
  })

  it('handles filtered dependencies, current spans, and a trailing span with no remaining issues', () => {
    const thread = makeThread({ total_issues: 1, next_unread_issue_number: '1', next_unread_issue_id: 10 })
    const ignored = makeDependency({ target_issue_thread_id: 99 })
    const missingSource = { ...makeDependency({ target_issue_id: 10 }), source_label: undefined }
    const entries = buildReadingOrderTimelineEntries({
      thread,
      dependencies: [ignored, missingSource, makeDependency({ target_issue_id: 10, target_label: 'Issue #1' })],
    })
    expect(entries).toHaveLength(1)
    expect(entries[0].kind).toBe('gate')
    expect(entries[0].kind === 'gate' && entries[0].gate.isCurrent).toBe(true)
  })
})
