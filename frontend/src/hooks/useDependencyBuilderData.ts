import type { FormEvent } from 'react'
import type { Dependency, FlowchartDependency, FlowchartNode, Issue, IssueListResponse, Thread, ThreadDependenciesResponse, ThreadListResponse } from '../types'

export interface DependencyBuilderDependenciesApi {
  listThreadDependencies: (threadId: number) => Promise<ThreadDependenciesResponse>
  listBlockedThreadIds: () => Promise<number[]>
  createDependency: (payload: {
    sourceType?: 'thread' | 'issue'
    sourceId: number
    targetType?: 'thread' | 'issue'
    targetId: number
  }) => Promise<Dependency>
  deleteDependency: (dependencyId: number) => Promise<void>
  updateDependency: (dependencyId: number, note: string | null) => Promise<Dependency>
}

export interface DependencyBuilderThreadsApi {
  list: (
    params?: { search?: string },
    pageToken?: string | null,
  ) => Promise<ThreadListResponse>
}

export interface DependencyBuilderIssuesApi {
  list: (
    threadId: number,
    params?: IssueListParams,
  ) => Promise<IssueListResponse>
  migrateThread: (
    threadId: number,
    lastIssueRead: number,
    totalIssues: number,
  ) => Promise<Thread>
}

export interface IssueListParams {
  status?: 'unread' | 'read'
  page_size?: number
  page_token?: string
}

export interface DependencyBuilderState {
  searchQuery: string
  setSearchQuery: (query: string) => void
  searchResults: Thread[]
  selectedThreadId: number | null
  setSelectedThreadId: (id: number | null) => void
  isSearching: boolean
  isSaving: boolean
  setIsSaving: (saving: boolean) => void
  error: string
  setError: (error: string) => void
  dependencies: ThreadDependenciesResponse
  isLoadingDeps: boolean
  showReadingOrder: boolean
  setShowReadingOrder: (show: boolean) => void
  readingView: 'timeline' | 'graph'
  setReadingView: (view: 'timeline' | 'graph') => void
  isGraphLoading: boolean
  setIsGraphLoading: (loading: boolean) => void
  flowchartThreads: Thread[]
  setFlowchartThreads: (threads: Thread[]) => void
  flowchartDependencies: FlowchartDependency[]
  setFlowchartDependencies: (deps: FlowchartDependency[]) => void
  flowchartIssueNodes: FlowchartNode[]
  setFlowchartIssueNodes: (nodes: FlowchartNode[]) => void
  blockedIds: Set<number>
  setBlockedIds: (ids: Set<number>) => void
  sourceIssueId: number | null
  setSourceIssueId: (id: number | null) => void
  targetIssueId: number | null
  setTargetIssueId: (id: number | null) => void
  sourceIssues: Issue[]
  setSourceIssues: (issues: Issue[]) => void
  targetIssues: Issue[]
  setTargetIssues: (issues: Issue[]) => void
  isLoadingSourceIssues: boolean
  setIsLoadingSourceIssues: (loading: boolean) => void
  isLoadingTargetIssues: boolean
  setIsLoadingTargetIssues: (loading: boolean) => void
  showInlineMigration: boolean
  setShowInlineMigration: (show: boolean) => void
  migrationLastRead: string
  setMigrationLastRead: (value: string) => void
  migrationTotal: string
  setMigrationTotal: (value: string) => void
  isMigrating: boolean
  setIsMigrating: (migrating: boolean) => void
  pendingDeletion: PendingDeletionState | null
  setPendingDeletion: (state: PendingDeletionState | null) => void
  editingNoteId: number | null
  setEditingNoteId: (id: number | null) => void
  noteText: string
  setNoteText: (text: string) => void
  isSavingNote: boolean
  setIsSavingNote: (saving: boolean) => void
}

export interface PendingDeletionState {
  dependencyId: number
  dependencyData: Dependency
  timeoutId: ReturnType<typeof setTimeout>
  toastId: string
}

export interface DependencyBuilderApiHandlers {
  loadDependencies: () => Promise<void>
  loadFlowchartData: (threadId: number) => Promise<void>
  fetchAllUnreadIssues: (issuesService: DependencyBuilderIssuesApi, threadId: number) => Promise<Issue[]>
  handleInlineMigration: (e: FormEvent, selectedThreadId: number | null, lastRead: string, total: string, issuesService: DependencyBuilderIssuesApi) => Promise<void>
  handleCreateDependency: (thread: Thread | null, selectedThreadId: number | null, sourceIssueId: number | null, targetIssueId: number | null, dependenciesService: DependencyBuilderDependenciesApi, threadsService: DependencyBuilderThreadsApi, issuesService: DependencyBuilderIssuesApi) => Promise<void>
  handleDeleteDependency: (dependencyId: number, dependencies: ThreadDependenciesResponse, dependenciesService: DependencyBuilderDependenciesApi, onChanged?: () => void) => void
  handleSaveNote: (dependencyId: number, noteText: string, dependenciesService: DependencyBuilderDependenciesApi, dependencies: ThreadDependenciesResponse, setDependencies: (deps: ThreadDependenciesResponse) => void) => Promise<void>
}

export function fetchAllUnreadIssues(
  issuesService: DependencyBuilderIssuesApi,
  threadId: number,
): Promise<Issue[]> {
  const allIssues: Issue[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  return (async () => {
    while (true) {
      const params: IssueListParams = {
        status: 'unread',
        page_size: 100,
      }
      if (nextPageToken) {
        params.page_token = nextPageToken
      }
      const data = await issuesService.list(threadId, params)
      allIssues.push(...data.issues)

      if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
        return allIssues
      }

      seenPageTokens.add(data.next_page_token)
      nextPageToken = data.next_page_token
    }
  })()
}