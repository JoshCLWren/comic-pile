import api from './api'
import type { Issue, IssueListResponse, Thread } from '../types'

/**
 * Issue tracking API service
 * Provides methods for managing comic issues within threads
 */
export const issuesApi = {
  /**
   * List issues for a thread with optional status filter and pagination
   * @param threadId - The thread ID to list issues for
   * @param params - Optional query parameters
   * @param params.status - Filter by status ('unread' | 'read')
   * @param params.page_size - Number of issues per page (default: 50)
   * @param params.page_token - Pagination token for next page
   * @returns Paginated list of issues
   */
  list: async (
    threadId: number,
    params?: { status?: 'unread' | 'read'; page_size?: number; page_token?: string }
  ): Promise<IssueListResponse> => {
    return api.get(`/v1/threads/${threadId}/issues`, { params })
  },

  /**
   * Create issues from a range format (e.g., "1-25" or "1, 3, 5-7")
   * @param threadId - The thread ID to create issues for
   * @param issueRange - Issue range string to parse and create
   * @returns List of created issues
   */
  create: async (threadId: number, issueRange: string): Promise<IssueListResponse> => {
    return api.post(`/v1/threads/${threadId}/issues`, { issue_range: issueRange })
  },

  /**
   * Get a single issue by ID
   * @param issueId - The issue ID to retrieve
   * @returns The issue details
   */
  get: async (issueId: number): Promise<Issue> => {
    return api.get(`/v1/issues/${issueId}`)
  },

  /**
   * Mark an issue as read
   * Updates thread's next_unread_issue_id and reading progress
   * @param issueId - The issue ID to mark as read
   */
  markRead: async (issueId: number): Promise<void> => {
    await api.post(`/v1/issues/${issueId}:markRead`)
  },

  /**
   * Mark an issue as unread
   * Reactivates thread if it was completed
   * @param issueId - The issue ID to mark as unread
   */
  markUnread: async (issueId: number): Promise<void> => {
    await api.post(`/v1/issues/${issueId}:markUnread`)
  },

  /**
   * Migrate a thread to use issue tracking
   * Converts thread from simple format to issue-based tracking
   * @param threadId - The thread ID to migrate
   * @param lastIssueRead - The number of the last issue read
   * @param totalIssues - Total number of issues in the series
   * @returns The updated thread object
   */
  migrateThread: async (threadId: number, lastIssueRead: number, totalIssues: number): Promise<Thread> => {
    return api.post(`/v1/threads/${threadId}:migrateToIssues`, {
      last_issue_read: lastIssueRead,
      total_issues: totalIssues,
    })
  },
}
