import { buildReadingOrderTimelineEntries } from './frontend/src/utils/readingOrderTimeline'
import type { Dependency, Thread } from './frontend/src/types'

// Test edge cases
function testEdgeCases() {
  console.log('Testing edge cases for reading order timeline...')
  
  // Edge case 1: Thread with no total_issues
  const threadNoTotal: Thread = {
    id: 1,
    title: 'Test Thread',
    format: 'Issues',
    issues_remaining: 5,
    total_issues: null,
    next_unread_issue_id: 1001,
    next_unread_issue_number: '5',
    reading_progress: null,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    collection_id: null,
    notes: null,
    created_at: '2024-01-01T00:00:00Z'
  }
  
  const dependencies: Dependency[] = [
    {
      id: 1,
      source_thread_id: null,
      target_thread_id: null,
      source_issue_id: 555,
      target_issue_id: 1001,
      is_issue_level: true,
      created_at: '2024-01-01T00:00:00Z',
      source_label: 'Prerequisite #1',
      target_label: 'Test Thread #5',
      source_issue_thread_id: 2,
      target_issue_thread_id: 1
    }
  ]
  
  const result = buildReadingOrderTimelineEntries({ thread: threadNoTotal, dependencies })
  console.log('Edge case 1 - No total_issues:', result)
  
  // Edge case 2: Thread with zero-indexed issues
  const threadZeroIndexed: Thread = {
    ...threadNoTotal,
    total_issues: 10,
    next_unread_issue_number: '0'
  }
  
  const depsZeroIndexed: Dependency[] = [
    {
      id: 1,
      source_thread_id: null,
      target_thread_id: null,
      source_issue_id: 555,
      target_issue_id: 1000,
      is_issue_level: true,
      created_at: '2024-01-01T00:00:00Z',
      source_label: 'Prerequisite #1',
      target_label: 'Test Thread #0',
      source_issue_thread_id: 2,
      target_issue_thread_id: 1
    }
  ]
  
  const result2 = buildReadingOrderTimelineEntries({ thread: threadZeroIndexed, dependencies: depsZeroIndexed })
  console.log('Edge case 2 - Zero-indexed:', result2)
  
  // Edge case 3: Multiple gates with same issue number
  const depsSameIssue: Dependency[] = [
    {
      id: 1,
      source_thread_id: null,
      target_thread_id: null,
      source_issue_id: 555,
      target_issue_id: 1005,
      is_issue_level: true,
      created_at: '2024-01-01T00:00:00Z',
      source_label: 'Prerequisite #1',
      target_label: 'Test Thread #5',
      source_issue_thread_id: 2,
      target_issue_thread_id: 1
    },
    {
      id: 2,
      source_thread_id: null,
      target_thread_id: null,
      source_issue_id: 556,
      target_issue_id: 1005,
      is_issue_level: true,
      created_at: '2024-01-01T00:00:00Z',
      source_label: 'Prerequisite #2',
      target_label: 'Test Thread #5',
      source_issue_thread_id: 3,
      target_issue_thread_id: 1
    }
  ]
  
  const result3 = buildReadingOrderTimelineEntries({ thread: threadZeroIndexed, dependencies: depsSameIssue })
  console.log('Edge case 3 - Same issue multiple gates:', result3)
}

testEdgeCases()