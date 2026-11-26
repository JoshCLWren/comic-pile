import type { IssueListResponse } from '../../types'
import type { IssueCreateOptions, IssueEditPreviewResponse } from '../../services/api-issues'
import type { ThreadIssueDependenciesResponse } from '../../services/api-dependencies'

/** The issue-API surface IssueToggleList consumes, injectable for tests. */
export interface IssueToggleListApi {
  list: (
    threadId: number,
    params?: { status?: 'unread' | 'read'; page_size?: number; page_token?: string },
  ) => Promise<IssueListResponse>
  create: (
    threadId: number,
    issueRange: string,
    options?: IssueCreateOptions,
  ) => Promise<IssueListResponse>
  previewCreate: (
    threadId: number,
    issueRange: string,
    options?: IssueCreateOptions,
  ) => Promise<IssueEditPreviewResponse>
  /** Optional structural preview seams; the production API supplies both. */
  previewDelete?: (threadId: number, issueId: number) => Promise<IssueEditPreviewResponse>
  previewReorder?: (threadId: number, issueIds: number[]) => Promise<IssueEditPreviewResponse>
  markRead: (issueId: number) => Promise<void>
  markUnread: (issueId: number) => Promise<void>
  delete: (issueId: number) => Promise<void>
  reorder: (threadId: number, issueIds: number[]) => Promise<void>
}

/** The dependency-API surface IssueToggleList consumes, injectable for tests. */
export interface IssueToggleListDependenciesApi {
  listForThread: (threadId: number) => Promise<ThreadIssueDependenciesResponse>
}

/** Imperative handle for deferred (draft) mode. */
export interface IssueToggleListHandle {
  /** Flush queued mutations to the server. Resolves when complete. */
  flush: () => Promise<void>
  /** Whether any mutations are queued. */
  hasPendingMutations: () => boolean
  /**
   * Whether the last committed edit produced an undo point. The Edit Series
   * dialog stays open after Save when this is true so the Undo affordance is
   * not unmounted with the dialog (#4654).
   */
  hasUndoPoint: () => boolean
}
