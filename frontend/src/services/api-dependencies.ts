import api from './api'
import type { HttpClient } from './httpClient'
import type { IssueDependenciesResponse } from '../types'

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

export const issueDependenciesApi = createIssueDependenciesApi(api)
