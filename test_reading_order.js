const { buildReadingOrderTimelineEntries } = require('./frontend/src/utils/readingOrderTimeline.ts');

// Mock data
const thread = {
  id: 1,
  title: 'Test Thread',
  format: 'Issues',
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
  created_at: '2024-01-01T00:00:00Z',
};

const dependencies = [
  {
    id: 1,
    target_issue_id: 1010,
    target_label: 'Test #10',
    source_label: 'Prereq #11',
    target_issue_thread_id: 1,
    source_issue_thread_id: 2,
    is_issue_level: true,
    created_at: '2024-01-01T00:00:00Z',
    source_thread_id: 2,
    target_thread_id: null,
    source_issue_id: 555,
  },
  {
    id: 2,
    target_issue_id: 1016,
    target_label: 'Test #16',
    source_label: 'Prereq #9',
    target_issue_thread_id: 1,
    source_issue_thread_id: 2,
    is_issue_level: true,
    created_at: '2024-01-01T00:00:00Z',
    source_thread_id: null,
    target_thread_id: null,
    source_issue_id: 555,
  }
];

console.log('Testing reading order timeline entries...');

const entries = buildReadingOrderTimelineEntries({ thread, dependencies });

console.log('Entries:', JSON.stringify(entries, null, 2));