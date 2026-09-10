import { createContext, useContext, type ReactNode } from 'react'
import type {
  Thread,
  ThreadCreatePayload,
  ThreadUpdatePayload,
  ReactivateThreadPayload,
  ThreadListResponse,
  ThreadQueryParams,
  RollResponse,
  AnalyticsMetrics,
  AuthTokens,
  SessionCurrent,
  SessionListResponse,
  SessionDetails,
  SessionSnapshotsResponse,
  SessionSummary,
  SetCurrentIssueResponse,
  Dependency,
  DependencyCreatePayload,
  ThreadDependenciesResponse,
  ConnectedDependenciesResponse,
  IssueDependenciesResponse,
  BlockingInfoResponse,
  BatchBlockingInfoResponse,
  BugReportResponse,
  ComicVineSeriesSearchResponse,
  ComicVineSeriesIssuesResponse,
  ComicVineIssueIntelligence,
  IssueIdentityResponse,
  MetadataRefreshResponse,
  MetadataCorrectionsResponse,
  ComicVineImportIssuePayload,
  ComicVineImportIssueResult,
  CanonicalCorrection,
  SessionModeResponse,
  SessionModeUpdateRequest,
} from '../types'

export interface ThreadsApi {
  list: (params?: ThreadQueryParams, pageToken?: string | null) => Promise<ThreadListResponse>
  get: (id: number) => Promise<Thread>
  create: (data: ThreadCreatePayload) => Promise<Thread>
  update: (id: number, data: ThreadUpdatePayload) => Promise<Thread>
  delete: (id: number) => Promise<void>
  reactivate: (data: ReactivateThreadPayload) => Promise<Thread>
  listStale: (days?: number) => Promise<Thread[]>
  setPending: (id: number) => Promise<RollResponse>
  setCurrentIssue: (id: number, issueNumber: string) => Promise<SetCurrentIssueResponse>
}

export interface RollApi {
  roll: () => Promise<RollResponse>
  override: (data: { thread_id: number }) => Promise<RollResponse>
  dismissPending: () => Promise<void>
  skip: () => Promise<RollResponse>
  reroll: () => Promise<RollResponse>
  setDie: (die: number) => Promise<void>
  clearManualDie: () => Promise<void>
}

export interface RateApi {
  rate: (data: {
    thread_id: number
    rating: number
    issues_read?: number
    finish_session?: boolean
    issue_number?: string
  }) => Promise<Thread>
}

export interface SessionApi {
  list: (params?: Record<string, unknown>, pageToken?: string | null) => Promise<SessionListResponse>
  get: (id: number) => Promise<SessionSummary>
  getCurrent: () => Promise<SessionCurrent>
  getDetails: (id: number | string) => Promise<SessionDetails>
  getSnapshots: (id: number | string) => Promise<SessionSnapshotsResponse>
  restoreSessionStart: (id: number | string) => Promise<void>
  updateMode: (data: SessionModeUpdateRequest) => Promise<SessionModeResponse>
}

export interface QueueApi {
  moveToPosition: (id: number, position: number) => Promise<void>
  moveToFront: (id: number) => Promise<void>
  moveToBack: (id: number) => Promise<void>
  shuffle: () => Promise<void>
}

export interface UndoApi {
  undo: (sessionId: number | string, snapshotId: number | string) => Promise<void>
  listSnapshots: (sessionId: number | string) => Promise<SessionSnapshotsResponse>
}

export interface DependenciesApi {
  listBlockedThreadIds: () => Promise<number[]>
  listThreadDependencies: (threadId: number) => Promise<ThreadDependenciesResponse>
  getIssueDependencies: (issueId: number) => Promise<IssueDependenciesResponse>
  getBlockingInfo: (threadId: number) => Promise<BlockingInfoResponse>
  getBatchBlockingInfo: (threadIds: number[]) => Promise<BatchBlockingInfoResponse>
  getConnectedThreads: (threadId: number) => Promise<ConnectedDependenciesResponse>
  createDependency: (data: DependencyCreatePayload) => Promise<Dependency>
  deleteDependency: (dependencyId: number) => Promise<void>
  updateDependency: (dependencyId: number, note: string | null) => Promise<Dependency>
}

export interface ComicVineApi {
  getIssueIntelligence: (issueId: number) => Promise<ComicVineIssueIntelligence | null>
  importIssue: (payload: ComicVineImportIssuePayload) => Promise<ComicVineImportIssueResult>
  searchSeries: (query: string, limit?: number) => Promise<ComicVineSeriesSearchResponse>
  getSeriesIssues: (volumeId: number, seriesName?: string) => Promise<ComicVineSeriesIssuesResponse>
  getIssueIdentity: (issueId: number) => Promise<IssueIdentityResponse>
  confirmIdentity: (issueId: number, comicvineIssueId: number) => Promise<IssueIdentityResponse>
  replaceIdentity: (issueId: number, comicvineIssueId: number, reason?: string) => Promise<IssueIdentityResponse>
  refreshMetadata: (issueId: number) => Promise<MetadataRefreshResponse>
  applyCorrection: (issueId: number, fieldName: string, canonicalValue: string, reason?: string) => Promise<MetadataCorrectionsResponse>
  listCorrections: (issueId: number) => Promise<MetadataCorrectionsResponse>
  revertCorrection: (issueId: number, correctionId: number) => Promise<MetadataCorrectionsResponse>
}

export interface TasksApi {
  getMetrics: () => Promise<AnalyticsMetrics>
}

export interface SnoozeApi {
  snooze: () => Promise<void>
  unsnooze: (threadId: number) => Promise<void>
}

export interface SkipApi {
  skip: () => Promise<RollResponse>
  unskip: (threadId: number) => Promise<void>
}

export interface MigrationApi {
  migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }) => Promise<Thread>
}

export interface BugReportsApi {
  create: (data: { title: string; description: string; diagnostics?: unknown }) => Promise<BugReportResponse>
}

export interface ProtectedRollMutationApi {
  rate: (data: { thread_id: number; rating: number; issues_read?: number; finish_session?: boolean; issue_number?: string }) => Promise<Thread>
  snooze: () => Promise<void>
  bootstrap: () => Promise<void>
}

export interface RollBootstrapApi {
  get: () => Promise<unknown>
  switchPrerequisite: (data: { node_type: 'issue' | 'thread'; node_id: number }) => Promise<unknown>
}

export interface Services {
  threadsApi: ThreadsApi
  rollApi: RollApi
  rateApi: RateApi
  sessionApi: SessionApi
  queueApi: QueueApi
  undoApi: UndoApi
  dependenciesApi: DependenciesApi
  comicVineApi: ComicVineApi
  tasksApi: TasksApi
  snoozeApi: SnoozeApi
  skipApi: SkipApi
  migrationApi: MigrationApi
  bugReportsApi: BugReportsApi
  protectedRollMutationApi: ProtectedRollMutationApi
  rollBootstrapApi: RollBootstrapApi
  setAccessToken: (token: string | null) => void
  clearAccessToken: () => void
  getAccessToken: () => string | null
  refreshSession: (options?: { skipAuthRedirect?: boolean }) => Promise<string>
  isSessionRefreshRejected: () => boolean
}

export const ServiceContext = createContext<Services | undefined>(undefined)

export function useServices(): Services {
  const context = useContext(ServiceContext)
  if (!context) {
    throw new Error('useServices must be used within a ServiceProvider')
  }
  return context
}

interface ServiceProviderProps {
  children: ReactNode
  services?: Partial<Services>
}

export function ServiceProvider({ children, services }: ServiceProviderProps) {
  const defaultServices = createDefaultServices()
  const mergedServices = { ...defaultServices, ...services }
  return (
    <ServiceContext.Provider value={mergedServices}>{children}</ServiceContext.Provider>
  )
}

function createDefaultServices(): Services {
  // These will be replaced by the actual implementation
  // This is just a placeholder to satisfy TypeScript
  const createUnimplemented = <T extends (...args: unknown[]) => Promise<unknown>>(
    name: string
  ): T => {
    return (() => {
      throw new Error(`${name} not implemented - ServiceProvider must provide real services`)
    }) as T
  }

  return {
    threadsApi: {
      list: createUnimplemented('threadsApi.list'),
      get: createUnimplemented('threadsApi.get'),
      create: createUnimplemented('threadsApi.create'),
      update: createUnimplemented('threadsApi.update'),
      delete: createUnimplemented('threadsApi.delete'),
      reactivate: createUnimplemented('threadsApi.reactivate'),
      listStale: createUnimplemented('threadsApi.listStale'),
      setPending: createUnimplemented('threadsApi.setPending'),
      setCurrentIssue: createUnimplemented('threadsApi.setCurrentIssue'),
    },
    rollApi: {
      roll: createUnimplemented('rollApi.roll'),
      override: createUnimplemented('rollApi.override'),
      dismissPending: createUnimplemented('rollApi.dismissPending'),
      skip: createUnimplemented('rollApi.skip'),
      reroll: createUnimplemented('rollApi.reroll'),
      setDie: createUnimplemented('rollApi.setDie'),
      clearManualDie: createUnimplemented('rollApi.clearManualDie'),
    },
    rateApi: {
      rate: createUnimplemented('rateApi.rate'),
    },
    sessionApi: {
      list: createUnimplemented('sessionApi.list'),
      get: createUnimplemented('sessionApi.get'),
      getCurrent: createUnimplemented('sessionApi.getCurrent'),
      getDetails: createUnimplemented('sessionApi.getDetails'),
      getSnapshots: createUnimplemented('sessionApi.getSnapshots'),
      restoreSessionStart: createUnimplemented('sessionApi.restoreSessionStart'),
      updateMode: createUnimplemented('sessionApi.updateMode'),
    },
    queueApi: {
      moveToPosition: createUnimplemented('queueApi.moveToPosition'),
      moveToFront: createUnimplemented('queueApi.moveToFront'),
      moveToBack: createUnimplemented('queueApi.moveToBack'),
      shuffle: createUnimplemented('queueApi.shuffle'),
    },
    undoApi: {
      undo: createUnimplemented('undoApi.undo'),
      listSnapshots: createUnimplemented('undoApi.listSnapshots'),
    },
    dependenciesApi: {
      listBlockedThreadIds: createUnimplemented('dependenciesApi.listBlockedThreadIds'),
      listThreadDependencies: createUnimplemented('dependenciesApi.listThreadDependencies'),
      getIssueDependencies: createUnimplemented('dependenciesApi.getIssueDependencies'),
      getBlockingInfo: createUnimplemented('dependenciesApi.getBlockingInfo'),
      getBatchBlockingInfo: createUnimplemented('dependenciesApi.getBatchBlockingInfo'),
      getConnectedThreads: createUnimplemented('dependenciesApi.getConnectedThreads'),
      createDependency: createUnimplemented('dependenciesApi.createDependency'),
      deleteDependency: createUnimplemented('dependenciesApi.deleteDependency'),
      updateDependency: createUnimplemented('dependenciesApi.updateDependency'),
    },
    comicVineApi: {
      getIssueIntelligence: createUnimplemented('comicVineApi.getIssueIntelligence'),
      importIssue: createUnimplemented('comicVineApi.importIssue'),
      searchSeries: createUnimplemented('comicVineApi.searchSeries'),
      getSeriesIssues: createUnimplemented('comicVineApi.getSeriesIssues'),
      getIssueIdentity: createUnimplemented('comicVineApi.getIssueIdentity'),
      confirmIdentity: createUnimplemented('comicVineApi.confirmIdentity'),
      replaceIdentity: createUnimplemented('comicVineApi.replaceIdentity'),
      refreshMetadata: createUnimplemented('comicVineApi.refreshMetadata'),
      applyCorrection: createUnimplemented('comicVineApi.applyCorrection'),
      listCorrections: createUnimplemented('comicVineApi.listCorrections'),
      revertCorrection: createUnimplemented('comicVineApi.revertCorrection'),
    },
    tasksApi: {
      getMetrics: createUnimplemented('tasksApi.getMetrics'),
    },
    snoozeApi: {
      snooze: createUnimplemented('snoozeApi.snooze'),
      unsnooze: createUnimplemented('snoozeApi.unsnooze'),
    },
    skipApi: {
      skip: createUnimplemented('skipApi.skip'),
      unskip: createUnimplemented('skipApi.unskip'),
    },
    migrationApi: {
      migrateThread: createUnimplemented('migrationApi.migrateThread'),
    },
    bugReportsApi: {
      create: createUnimplemented('bugReportsApi.create'),
    },
    protectedRollMutationApi: {
      rate: createUnimplemented('protectedRollMutationApi.rate'),
      snooze: createUnimplemented('protectedRollMutationApi.snooze'),
      bootstrap: createUnimplemented('protectedRollMutationApi.bootstrap'),
    },
    rollBootstrapApi: {
      get: createUnimplemented('rollBootstrapApi.get'),
      switchPrerequisite: createUnimplemented('rollBootstrapApi.switchPrerequisite'),
    },
    setAccessToken: createUnimplemented('setAccessToken'),
    clearAccessToken: createUnimplemented('clearAccessToken'),
    getAccessToken: createUnimplemented('getAccessToken'),
    refreshSession: createUnimplemented('refreshSession'),
    isSessionRefreshRejected: createUnimplemented('isSessionRefreshRejected'),
  }
}