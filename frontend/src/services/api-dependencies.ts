import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  Dependency,
  DependencyCreatePayload,
  ThreadDependenciesResponse,
  IssueDependenciesResponse,
  ConnectedDependenciesResponse,
  BlockingInfoResponse,
  BatchBlockingInfoResponse,
} from '../types'

export interface ThreadIssueDependenciesResponse {
  thread_id: number
  issues: IssueDependenciesResponse[]
}

/**
 * Build the issue-dependency service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every dependency request.
 * @returns The issue dependencies API bound to `client`.
 */
export function createIssueDependenciesApi(client: HttpClient) {
  return {
    listForThread: (threadId: number): Promise<ThreadIssueDependenciesResponse> =>
      client.get<ThreadIssueDependenciesResponse>(`/v1/threads/${threadId}/issue-dependencies`),
  }
}

/**
 * Build the thread-dependency service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every dependency request.
 * @returns The thread dependencies API bound to `client`.
 */
export function createDependenciesApi(client: HttpClient) {
  return {
    listBlockedThreadIds: () => client.get<number[]>('/v1/dependencies/blocked'),
    listThreadDependencies: (threadId: number) =>
      client.get<ThreadDependenciesResponse>(`/v1/threads/${threadId}/dependencies`),
    getIssueDependencies: (issueId: number) =>
      client.get<IssueDependenciesResponse>(`/v1/issues/${issueId}/dependencies`),
    getBlockingInfo: (threadId: number) =>
      client.post<BlockingInfoResponse>(`/v1/threads/${threadId}:getBlockingInfo`),
    getBatchBlockingInfo: (threadIds: number[]) =>
      client.post<BatchBlockingInfoResponse>('/v1/threads:getBlockingInfo', { thread_ids: threadIds }),
    getConnectedThreads: (threadId: number) =>
      client.get<ConnectedDependenciesResponse>(`/v1/threads/${threadId}/connected`),
    createDependency: ({ sourceType = 'thread', sourceId, targetType = 'thread', targetId }: DependencyCreatePayload) =>
      client.post<Dependency, { source_type: 'thread' | 'issue'; source_id: number; target_type: 'thread' | 'issue'; target_id: number }>('/v1/dependencies/', {
        source_type: sourceType,
        source_id: sourceId,
        target_type: targetType,
        target_id: targetId,
      }),
    deleteDependency: (dependencyId: number) => client.delete<void>(`/v1/dependencies/${dependencyId}`),
    updateDependency: (dependencyId: number, note: string | null) =>
      client.patch<Dependency, { note: string | null }>(`/v1/dependencies/${dependencyId}`, { note }),
  }
}

export const issueDependenciesApi = createIssueDependenciesApi(defaultHttpClient())
export const dependenciesApi = createDependenciesApi(defaultHttpClient())
