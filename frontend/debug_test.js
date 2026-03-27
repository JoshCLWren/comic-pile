import { buildReadingOrderTimelineEntries } from './src/utils/readingOrderTimeline'
import type { Dependency, Thread } from './src/types'

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

console.log('Debug: "creates spans and gates with correct statuses" test')

const thread = makeThread({ total_issues: 30, next_unread_issue_number: '10', next_unread_issue_id: 1010 })
const dependencies: Dependency[] = [
  makeDependency({ id: 1, target_issue_id: 1010, target_label: 'Planetary #10', source_label: 'Stormwatch #11' }),
  makeDependency({ id: 2, target_issue_id: 1016, target_label: 'Planetary #16', source_label: 'Authority #9' }),
]

console.log('Thread:', JSON.stringify(thread, null, 2))
console.log('Dependencies:', JSON.stringify(dependencies, null, 2))

const entries = buildReadingOrderTimelineEntries({ thread, dependencies })

console.log('Actual entries length:', entries.length)
console.log('Actual entries:')
entries.forEach((entry, index) => {
  console.log(`[${index}]:`, JSON.stringify(entry, null, 2))
})

console.log('\nExpected:')
console.log('[0]: { kind: "span" }')
console.log('[1]: { kind: "gate", gate: { status: "blocked" } }')
console.log('[2]: ? (expected to be missing)')
console.log('[3]: { kind: "span", span: { label: "Issues 17–30" } }')

// Check the specific expectations
console.log('\nChecking expectations:')
console.log(`Expected length: 4, Actual length: ${entries.length}`)

if (entries.length >= 1) {
  console.log(`Entry 0 kind: ${entries[0].kind} (expected: "span")`)
}
if (entries.length >= 2) {
  console.log(`Entry 1 kind: ${entries[1].kind} (expected: "gate")`)
  if (entries[1].kind === 'gate') {
    console.log(`Entry 1 status: ${entries[1].gate.status} (expected: "blocked")`)
  }
}
if (entries.length >= 4) {
  const lastEntry = entries[3]
  console.log(`Entry 3 kind: ${lastEntry.kind} (expected: "span")`)
  if (lastEntry.kind === 'span') {
    console.log(`Entry 3 label: "${lastEntry.span.label}" (expected: "Issues 17–30")`)
  }
}