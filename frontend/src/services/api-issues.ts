import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  Issue,
  IssueListResponse,
  ManualCreatorCredit,
  ReaderContextResponse,
  Thread,
} from '../types'

export type { IssueListResponse }

/** One creator credit returned by the bulk thread-creators read. */
export type ThreadIssueCreatorCredit = ManualCreatorCredit & {
  creator_id?: number | null
}

/** Query parameters accepted by the thread creator-credit projection (#5706). */
export interface ThreadIssueCreditsParams {
  page_size?: number
  page_token?: string
}

/** Response of GET /v2/threads/{threadId}/creatorCredits (#5706). */
export interface ThreadIssueCreatorsResponse {
  thread_id: number
  issues: { issue_id: number; creators: ThreadIssueCreatorCredit[] }[]
  /** Total confirmed-mapping issue rows (including rows without stored credits), independent of the page. */
  total_count?: number
  /** Size of this page (1-100, default 100). */
  page_size?: number
  /** Continuation cursor, or null when the projection is exhausted. */
  next_page_token?: string | null
}

export interface IssueReadOperationItem {
  issue_id: number
  thread_id: number
  issue_number: string
  previous_status: string
}

export interface IssueReadOperationResponse {
  id: number
  operation_type: 'bulk_mark_read' | 'bulk_mark_unread'
  created_at: string
  undone_at?: string | null
  items: IssueReadOperationItem[]
}

export interface IssueReadOperationUndoResponse {
  operation: IssueReadOperationResponse
  undone_issue_ids: number[]
  skipped_issue_ids: number[]
}

export interface SetCurrentIssueResponse {
  thread_id: number
  title: string
  issues_remaining: number
  queue_position: number
  issue_id: number | null
  issue_number: string | null
  next_issue_id: number | null
  next_issue_number: string | null
  total_issues: number | null
  reading_progress: string | null
}

interface CreateIssuesPayload {
  issue_range: string
  insert_after_issue_id?: number
  append_to_end?: boolean
  strategy?: 'safe_default' | 'numeric_resort'
  expected_issue_ids?: number[]
  accepted_alias_numbers?: string[]
}

/** Options shared by the create and preview create calls (#4654). */
export interface IssueCreateOptions {
  insert_after_issue_id?: number | null
  strategy?: 'safe_default' | 'numeric_resort'
  expected_issue_ids?: number[]
  accepted_alias_numbers?: string[]
}

/** A source-preserving alternative to creating a physical duplicate. */
export interface IssueEditAliasOffer {
  requested_issue_number: string
  existing_issue_id: number
  existing_issue_number: string
  series_title: string
  evidence: string
}

export interface IssuePreviewItem {
  issue_id: number | null
  issue_number: string
  position: number
  is_new: boolean
  /** Human-readable series title so two issues sharing a number stay distinct. */
  series_title?: string
  /** Names of the source reading lists this issue belongs to. */
  source_lists?: string[]
  is_read?: boolean
  is_mapped?: boolean
  has_rating?: boolean
  /** Affected Queue/Roll frontier label, e.g. the current unread issue. */
  frontier_label?: string | null
  /** Human-readable description of this row's order effect. */
  effect?: string
  /** Whether a second physical issue with the same number exists. */
  is_duplicate?: boolean
}

export interface IssueEditPreviewOutcome {
  strategy: 'safe_default' | 'numeric_resort'
  can_commit: boolean
  preserves_existing_relative_order: boolean
  before: IssuePreviewItem[]
  after: IssuePreviewItem[]
  added_issue_numbers: string[]
  graph: {
    status: string
    cycles: Array<{ message: string; edges: Array<{ source: { issue_id: number; issue_number: string; series_title: string }; target: { issue_id: number; issue_number: string; series_title: string }; origin: string; list_name?: string | null }> }>
  }
  conflict_message: string | null
}

export interface IssueEditPreviewResponse {
  thread_id: number
  thread_title: string
  requested_strategy: 'safe_default' | 'numeric_resort'
  default_outcome: IssueEditPreviewOutcome
  numeric_resort_outcome: IssueEditPreviewOutcome | null
  alias_offers?: IssueEditAliasOffer[]
  expected_issue_ids?: number[]
}

/** Query parameters accepted by the thread issue list endpoint. */
export interface IssueListParams {
  status?: 'unread' | 'read'
  page_size?: number
  page_token?: string
}

/**
 * Issue tracking API service
 * Provides methods for managing comic issues within threads
 */
export function createIssuesApi(client: HttpClient) {
  return {
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
      params?: IssueListParams
    ): Promise<IssueListResponse> => {
      return client.get(`/v2/threads/${threadId}/issues`, { params })
    },

    /**
     * List stored ComicVine creator credits for mapped issues in a thread
     * (#3461, moved to the canonical v2 projection in #5706). One bounded
     * request covers a page of issue rows; unmapped issues are omitted.
     * @param threadId - The thread ID whose issue credits are listed
     * @param params - Optional page size and continuation token
     * @returns Per-issue creator credits with pagination fields
     */
    listCreators: async (
      threadId: number,
      params?: ThreadIssueCreditsParams
    ): Promise<ThreadIssueCreatorsResponse> => {
      return client.get(`/v2/threads/${threadId}/creatorCredits`, { params })
    },

    /**
     * Create issues from a range format (e.g., "1-25" or "1, 3, 5-7")
     * @param threadId - The thread ID to create issues for
     * @param issueRange - Issue range string to parse and create
     * @param options - Optional insert positioning options
     * @returns List of created issues
     */
    create: async (
      threadId: number,
      issueRange: string,
      options?: IssueCreateOptions
    ): Promise<IssueListResponse> => {
      const payload: CreateIssuesPayload = {
        issue_range: issueRange,
      }

      if (options && 'insert_after_issue_id' in options) {
        if (options.insert_after_issue_id === null) {
          // Explicit "At the end" is distinct from an omitted natural anchor.
          payload.append_to_end = true
        } else {
          payload.insert_after_issue_id = options.insert_after_issue_id
        }
      }
      if (options?.strategy) payload.strategy = options.strategy
      if (options?.expected_issue_ids) payload.expected_issue_ids = options.expected_issue_ids
      if (options?.accepted_alias_numbers) {
        payload.accepted_alias_numbers = options.accepted_alias_numbers
      }

      return client.post(`/v2/threads/${threadId}/issues`, payload)
    },

    previewCreate: async (
      threadId: number,
      issueRange: string,
      options?: IssueCreateOptions
    ): Promise<IssueEditPreviewResponse> => {
      const payload: CreateIssuesPayload = { issue_range: issueRange }
      if (options && 'insert_after_issue_id' in options) {
        if (options.insert_after_issue_id === null) payload.append_to_end = true
        else payload.insert_after_issue_id = options.insert_after_issue_id
      }
      if (options?.strategy) payload.strategy = options.strategy
      if (options?.expected_issue_ids) payload.expected_issue_ids = options.expected_issue_ids
      if (options?.accepted_alias_numbers) {
        payload.accepted_alias_numbers = options.accepted_alias_numbers
      }
      return client.post(`/v2/threads/${threadId}/issues/preview`, payload)
    },

    /**
     * Preview a delete before the queued mutation is accepted (#4654). The
     * server projects the series without the issue inside a rolled-back
     * savepoint, so no row is changed by the preview.
     */
    previewDelete: async (
      threadId: number,
      issueId: number,
    ): Promise<IssueEditPreviewResponse> =>
      client.post(`/v2/threads/${threadId}/issues/structure-preview`, {
        operation: 'delete',
        issue_id: issueId,
      }),

    /**
     * Preview a reorder before the queued mutation is accepted (#4654).
     * `issueIds` must list every issue in the series exactly once.
     */
    previewReorder: async (
      threadId: number,
      issueIds: number[],
    ): Promise<IssueEditPreviewResponse> =>
      client.post(`/v2/threads/${threadId}/issues/structure-preview`, {
        operation: 'reorder',
        issue_ids: issueIds,
      }),

    /**
     * Get a single issue by ID
     * @param issueId - The issue ID to retrieve
     * @returns The issue details
     */
    get: async (issueId: number): Promise<Issue> => {
      return client.get(`/v2/issues/${issueId}`)
    },

    /**
     * Mark an issue as read
     * Updates thread's next_unread_issue_id and reading progress
     * @param issueId - The issue ID to mark as read
     */
    markRead: async (issueId: number): Promise<void> => {
      await client.post(`/v2/issues/${issueId}/read-markers`)
    },

    /**
     * Mark an issue as unread
     * Reactivates thread if it was completed
     * @param issueId - The issue ID to mark as unread
     */
    markUnread: async (issueId: number): Promise<void> => {
      await client.delete(`/v2/issues/${issueId}/read-markers`)
    },

    bulkMarkRead: async (issueIds: number[]): Promise<IssueReadOperationResponse> => {
      return client.post(`/v2/issue-read-markers`, { issue_ids: issueIds })
    },

    bulkMarkUnread: async (issueIds: number[]): Promise<IssueReadOperationResponse> => {
      return client.post(`/v2/issue-read-marker-removals`, { issue_ids: issueIds })
    },

    getReadOperation: async (operationId: number): Promise<IssueReadOperationResponse> => {
      return client.get(`/v2/issue-read-operations/${operationId}`)
    },

    undoReadOperation: async (operationId: number): Promise<IssueReadOperationUndoResponse> => {
      return client.post(`/v2/issue-read-operations/${operationId}/undo`)
    },

    /**
     * Move an issue to a new position within its thread
     * @param issueId - The issue ID to move
     * @param afterIssueId - Move after this issue ID, or null to move to the top
     */
    move: async (issueId: number, afterIssueId: number | null): Promise<void> => {
      await client.put<void, { after_issue_id: number | null }>(`/v2/issues/${issueId}/position`, {
        after_issue_id: afterIssueId,
      })
    },

    /**
     * Rewrite the full issue order for a thread
     * @param threadId - The thread whose issues should be reordered
     * @param issueIds - Full ordered list of issue IDs
     */
    reorder: async (threadId: number, issueIds: number[]): Promise<void> => {
      await client.put<void, { issue_ids: number[] }>(`/v2/threads/${threadId}/issue-order`, {
        issue_ids: issueIds,
      })
    },

    /**
     * Delete a single issue from its thread
     * @param issueId - The issue ID to delete
     */
    delete: async (issueId: number): Promise<void> => {
      await client.delete<void>(`/v2/issues/${issueId}`)
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
      return client.post(`/v1/threads/${threadId}:migrateToIssues`, {
        last_issue_read: lastIssueRead,
        total_issues: totalIssues,
      })
    },

  /**
   * Atomically set the current issue for an active thread
   * Marks all issues before the target as read, sets target as unread,
   * and updates the session's pending issue.
   * @param threadId - The thread to correct
   * @param issueNumber - The target issue number to set as current
   * @returns Response with corrected thread and issue info
   */
    setCurrentIssue: async (threadId: number, issueNumber: string): Promise<SetCurrentIssueResponse> => {
      return client.post(`/v1/threads/${threadId}:setCurrentIssue`, {
        issue_number: issueNumber,
      })
    },

    /**
     * Get reader-context for an issue
     * Returns bounded series history, exact crossover context, and local reading neighborhood
     * @param issueId - The issue ID to get reader-context for
     * @returns Reader-context response with series, crossovers, and local_chain data
     */
    getReaderContext: async (issueId: number, config?: { signal?: AbortSignal }): Promise<ReaderContextResponse> => {
      return client.get(`/v2/issues/${issueId}/reader-context`, config)
    },
  }
}

export const issuesApi = createIssuesApi(defaultHttpClient())
