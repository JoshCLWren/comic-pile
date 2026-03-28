import { describe, expect, it } from 'vitest'
import { buildReadingOrderTimelineEntries } from '../utils/readingOrderTimeline'
import type { Dependency, Thread } from '../types'

function makeThread(overrides: Partial<Thread> = {}): Thread {
  return {
    id: overrides.id ?? 1,
    title: overrides.title ?? 'Planetary',
    format: overrides.format ?? 'Issues',
    issues_remaining: overrides.issues_remaining ?? 10,
    total_issues: overrides.total_issues ?? 27,
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
})
