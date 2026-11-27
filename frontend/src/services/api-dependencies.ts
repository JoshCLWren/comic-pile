import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  Dependency,
  DependencyCreatePayload,
  ThreadDependenciesResponse,
  IssueDependenciesResponse,
  ConnectedDependenciesResponse,
  BatchEligibilityResponse,
  ThreadEligibilityResponse,
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
      client.get<ThreadIssueDependenciesResponse>(`/v2/threads/${threadId}/issueDependencies`),
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
    listBlockedThreadIds: () => client.get<number[]>('/v2/dependencies/blocked'),
    listThreadDependencies: (threadId: number) =>
      client.get<ThreadDependenciesResponse>(`/v2/threads/${threadId}/dependencies`),
    getIssueDependencies: (issueId: number) =>
      client.get<IssueDependenciesResponse>(`/v2/issues/${issueId}/dependencies`),
    getThreadEligibility: (threadId: number) =>
      client.get<ThreadEligibilityResponse>(`/v2/threads/${threadId}/eligibility`),
    explainEligibility: (threadIds: number[]) =>
      client.post<BatchEligibilityResponse>('/v2/threads:explainEligibility', { thread_ids: threadIds }),
    getConnectedThreads: (threadId: number) =>
      client.get<ConnectedDependenciesResponse>(`/v2/threads/${threadId}/connections`),
    createDependency: ({ sourceType = 'thread', sourceId, targetType = 'thread', targetId }: DependencyCreatePayload) =>
      client.post<Dependency, { source_type: 'thread' | 'issue'; source_id: number; target_type: 'thread' | 'issue'; target_id: number }>('/v2/dependencies/', {
        source_type: sourceType,
        source_id: sourceId,
        target_type: targetType,
        target_id: targetId,
      }),
    deleteDependency: (dependencyId: number) => client.delete<void>(`/v2/dependencies/${dependencyId}`),
    updateDependency: (dependencyId: number, note: string | null) =>
      client.patch<Dependency, { note: string | null }>(`/v2/dependencies/${dependencyId}`, { note }),
  }
}

export const issueDependenciesApi = createIssueDependenciesApi(defaultHttpClient())
export const dependenciesApi = createDependenciesApi(defaultHttpClient())
