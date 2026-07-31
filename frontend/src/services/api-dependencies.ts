import api from './api'
import type { IssueDependenciesResponse } from '../types'

export interface ThreadIssueDependenciesResponse {
  thread_id: number
  issues: IssueDependenciesResponse[]
}

export const issueDependenciesApi = {
  listForThread: (threadId: number): Promise<ThreadIssueDependenciesResponse> =>
    api.get<ThreadIssueDependenciesResponse>(`/v1/threads/${threadId}/issue-dependencies`),
}
