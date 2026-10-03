import { defaultHttpClient, type HttpClient } from './httpClient'
import type { BugReportResponse } from '../types'

/**
 * Build the bug reports service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every bug report request.
 * @returns The bug reports API bound to `client`.
 */
export function createBugReportsApi(client: HttpClient) {
  return {
    create: (data: { title: string; description: string; diagnostics?: unknown }) =>
      client.post<BugReportResponse>('/v1/bug-reports/', data),
  }
}

export const bugReportsApi = createBugReportsApi(defaultHttpClient())