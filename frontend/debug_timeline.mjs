import { buildReadingOrderTimelineEntries } from './src/utils/readingOrderTimeline.js'

const thread = {
  id: 1,
  title: 'Test Thread',
  format: 'Comics',
  issues_remaining: 10,
  total_issues: 30,
  next_unread_issue_id: 1010,
  next_unread_issue_number: '10',
  reading_progress: null,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  collection_id: null,
  notes: null,
  created_at: '2024-01-01T00:00:00Z'
}

const dependencies = [
  {
    id: 1,
    target_issue_thread_id: 1,
    target_issue_id: 1010,
    target_label: 'Test Thread #10',
    source_label: 'Prereq #11',
    source_issue_thread_id: 2,
    is_issue_level: true,
    source_thread_id: null,
    target_thread_id: null,
    source_issue_id: 555,
    created_at: '2024-01-01T00:00:00Z'
  },
  {
    id: 2,
    target_issue_thread_id: 1,
    target_issue_id: 1016,
    target_label: 'Test Thread #16',
    source_label: 'Prereq #9',
    source_issue_thread_id: 3,
    is_issue_level: true,
    source_thread_id: null,
    target_thread_id: null,
    source_issue_id: 556,
    created_at: '2024-01-01T00:00:00Z'
  }
]

const result = buildReadingOrderTimelineEntries({ thread, dependencies })
console.log('Result entries:', result.length)
result.forEach((entry, index) => {
  if (entry.kind === 'span') {
    console.log(`${index}: SPAN - ${entry.span.label}`)
  } else {
    console.log(`${index}: GATE - Issue ${entry.gate.issueNumberText} (${entry.gate.status})`)
  }
})