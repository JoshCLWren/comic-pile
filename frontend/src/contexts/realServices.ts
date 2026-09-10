import api, {
  threadsApi,
  rollApi,
  rateApi,
  sessionApi,
  queueApi,
  undoApi,
  dependenciesApi,
  comicVineApi,
  tasksApi,
  snoozeApi,
  skipApi,
  migrationApi,
  bugReportsApi,
  type Thread,
  type ThreadCreatePayload,
  type ThreadUpdatePayload,
  type ReactivateThreadPayload,
  type ThreadListResponse,
  type ThreadQueryParams,
  type RollResponse,
  type AnalyticsMetrics,
  type AuthTokens,
  type SessionCurrent,
  type SessionListResponse,
  type SessionDetails,
  type SessionSnapshotsResponse,
  type SessionSummary,
  type SetCurrentIssueResponse,
  type Dependency,
  type DependencyCreatePayload,
  type ThreadDependenciesResponse,
  type ConnectedDependenciesResponse,
  type IssueDependenciesResponse,
  type BlockingInfoResponse,
  type BatchBlockingInfoResponse,
  type BugReportResponse,
  type ComicVineSeriesSearchResponse,
  type ComicVineSeriesIssuesResponse,
  type ComicVineIssueIntelligence,
  type IssueIdentityResponse,
  type MetadataRefreshResponse,
  type MetadataCorrectionsResponse,
  type ComicVineImportIssuePayload,
  type ComicVineImportIssueResult,
  type CanonicalCorrection,
  type SessionModeResponse,
  type SessionModeUpdateRequest,
} from '../services/api'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import {
  setAccessToken,
  clearAccessToken,
  getAccessToken,
  refreshSession,
  isSessionRefreshRejected,
} from '../services/api'
import type { Services } from './ServiceContext'

export function createRealServices(): Services {
  return {
    threadsApi: {
      list: (params?: ThreadQueryParams, pageToken?: string | null): Promise<ThreadListResponse> =>
        threadsApi.list(params, pageToken),
      get: (id: number): Promise<Thread> => threadsApi.get(id),
      create: (data: ThreadCreatePayload): Promise<Thread> => threadsApi.create(data),
      update: (id: number, data: ThreadUpdatePayload): Promise<Thread> => threadsApi.update(id, data),
      delete: (id: number): Promise<void> => threadsApi.delete(id),
      reactivate: (data: ReactivateThreadPayload): Promise<Thread> => threadsApi.reactivate(data),
      listStale: (days = 30): Promise<Thread[]> => threadsApi.listStale(days),
      setPending: (id: number): Promise<RollResponse> => threadsApi.setPending(id),
      setCurrentIssue: (id: number, issueNumber: string): Promise<SetCurrentIssueResponse> =>
        threadsApi.setCurrentIssue(id, issueNumber),
    },
    rollApi: {
      roll: (): Promise<RollResponse> => rollApi.roll(),
      override: (data: { thread_id: number }): Promise<RollResponse> => rollApi.override(data),
      dismissPending: (): Promise<void> => rollApi.dismissPending(),
      skip: (): Promise<RollResponse> => rollApi.skip(),
      reroll: (): Promise<RollResponse> => rollApi.reroll(),
      setDie: (die: number): Promise<void> => rollApi.setDie(die),
      clearManualDie: (): Promise<void> => rollApi.clearManualDie(),
    },
    rateApi: {
      rate: (data: {
        thread_id: number
        rating: number
        issues_read?: number
        finish_session?: boolean
        issue_number?: string
      }): Promise<Thread> => rateApi.rate(data),
    },
    sessionApi: {
      list: (params?: Record<string, unknown>, pageToken?: string | null): Promise<SessionListResponse> =>
        sessionApi.list(params, pageToken),
      get: (id: number): Promise<SessionSummary> => sessionApi.get(id),
      getCurrent: (): Promise<SessionCurrent> => sessionApi.getCurrent(),
      getDetails: (id: number | string): Promise<SessionDetails> => sessionApi.getDetails(id),
      getSnapshots: (id: number | string): Promise<SessionSnapshotsResponse> =>
        sessionApi.getSnapshots(id),
      restoreSessionStart: (id: number | string): Promise<void> => sessionApi.restoreSessionStart(id),
      updateMode: (data: SessionModeUpdateRequest): Promise<SessionModeResponse> =>
        sessionApi.updateMode(data),
    },
    queueApi: {
      moveToPosition: (id: number, position: number): Promise<void> => queueApi.moveToPosition(id, position),
      moveToFront: (id: number): Promise<void> => queueApi.moveToFront(id),
      moveToBack: (id: number): Promise<void> => queueApi.moveToBack(id),
      shuffle: (): Promise<void> => queueApi.shuffle(),
    },
    undoApi: {
      undo: (sessionId: number | string, snapshotId: number | string): Promise<void> =>
        undoApi.undo(sessionId, snapshotId),
      listSnapshots: (sessionId: number | string): Promise<SessionSnapshotsResponse> =>
        undoApi.listSnapshots(sessionId),
    },
    dependenciesApi: {
      listBlockedThreadIds: (): Promise<number[]> => dependenciesApi.listBlockedThreadIds(),
      listThreadDependencies: (threadId: number): Promise<ThreadDependenciesResponse> =>
        dependenciesApi.listThreadDependencies(threadId),
      getIssueDependencies: (issueId: number): Promise<IssueDependenciesResponse> =>
        dependenciesApi.getIssueDependencies(issueId),
      getBlockingInfo: (threadId: number): Promise<BlockingInfoResponse> =>
        dependenciesApi.getBlockingInfo(threadId),
      getBatchBlockingInfo: (threadIds: number[]): Promise<BatchBlockingInfoResponse> =>
        dependenciesApi.getBatchBlockingInfo(threadIds),
      getConnectedThreads: (threadId: number): Promise<ConnectedDependenciesResponse> =>
        dependenciesApi.getConnectedThreads(threadId),
      createDependency: (data: DependencyCreatePayload): Promise<Dependency> =>
        dependenciesApi.createDependency(data),
      deleteDependency: (dependencyId: number): Promise<void> =>
        dependenciesApi.deleteDependency(dependencyId),
      updateDependency: (dependencyId: number, note: string | null): Promise<Dependency> =>
        dependenciesApi.updateDependency(dependencyId, note),
    },
    comicVineApi: {
      getIssueIntelligence: (issueId: number): Promise<ComicVineIssueIntelligence | null> =>
        comicVineApi.getIssueIntelligence(issueId),
      importIssue: (payload: ComicVineImportIssuePayload): Promise<ComicVineImportIssueResult> =>
        comicVineApi.importIssue(payload),
      searchSeries: (query: string, limit = 10): Promise<ComicVineSeriesSearchResponse> =>
        comicVineApi.searchSeries(query, limit),
      getSeriesIssues: (volumeId: number, seriesName = ''): Promise<ComicVineSeriesIssuesResponse> =>
        comicVineApi.getSeriesIssues(volumeId, seriesName),
      getIssueIdentity: (issueId: number): Promise<IssueIdentityResponse> =>
        comicVineApi.getIssueIdentity(issueId),
      confirmIdentity: (issueId: number, comicvineIssueId: number): Promise<IssueIdentityResponse> =>
        comicVineApi.confirmIdentity(issueId, comicvineIssueId),
      replaceIdentity: (issueId: number, comicvineIssueId: number, reason?: string): Promise<IssueIdentityResponse> =>
        comicVineApi.replaceIdentity(issueId, comicvineIssueId, reason),
      refreshMetadata: (issueId: number): Promise<MetadataRefreshResponse> =>
        comicVineApi.refreshMetadata(issueId),
      applyCorrection: (issueId: number, fieldName: string, canonicalValue: string, reason?: string): Promise<MetadataCorrectionsResponse> =>
        comicVineApi.applyCorrection(issueId, fieldName, canonicalValue, reason),
      listCorrections: (issueId: number): Promise<MetadataCorrectionsResponse> =>
        comicVineApi.listCorrections(issueId),
      revertCorrection: (issueId: number, correctionId: number): Promise<MetadataCorrectionsResponse> =>
        comicVineApi.revertCorrection(issueId, correctionId),
    },
    tasksApi: {
      getMetrics: (): Promise<AnalyticsMetrics> => tasksApi.getMetrics(),
    },
    snoozeApi: {
      snooze: (): Promise<void> => snoozeApi.snooze(),
      unsnooze: (threadId: number): Promise<void> => snoozeApi.unsnooze(threadId),
    },
    skipApi: {
      skip: (): Promise<RollResponse> => skipApi.skip(),
      unskip: (threadId: number): Promise<void> => skipApi.unskip(threadId),
    },
    migrationApi: {
      migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }): Promise<Thread> =>
        migrationApi.migrateThread(threadId, data),
    },
    bugReportsApi: {
      create: (data: { title: string; description: string; diagnostics?: unknown }): Promise<BugReportResponse> =>
        bugReportsApi.create(data),
    },
    protectedRollMutationApi: {
      rate: (data: {
        thread_id: number
        rating: number
        issues_read?: number
        finish_session?: boolean
        issue_number?: string
      }): Promise<Thread> => protectedRollMutationApi.rate(data),
      snooze: (): Promise<void> => protectedRollMutationApi.snooze(),
      bootstrap: (): Promise<void> => protectedRollMutationApi.bootstrap(),
    },
    rollBootstrapApi: {
      get: (): Promise<unknown> => rollBootstrapApi.get(),
      switchPrerequisite: (data: { node_type: 'issue' | 'thread'; node_id: number }): Promise<unknown> =>
        rollBootstrapApi.switchPrerequisite(data),
    },
    setAccessToken,
    clearAccessToken,
    getAccessToken,
    refreshSession,
    isSessionRefreshRejected,
  }
}