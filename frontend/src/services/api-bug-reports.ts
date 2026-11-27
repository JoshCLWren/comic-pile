import { defaultHttpClient, type HttpClient } from './httpClient'
import type { BugReportV2Response } from '../types'

/**
 * Build the bug reports service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every bug report request.
 * @returns The bug reports API bound to `client`.
 */
export function createBugReportsApi(client: HttpClient) {
  return {
    // Canonical AIP-133 Create (#5718): no trailing slash and no `:submit`
    // custom-method alias. The response carries the stable resource name/id.
    create: (data: { title: string; description: string; diagnostics?: unknown }) =>
      client.post<BugReportV2Response>('/v2/bugReports', data),
  }
}

export const bugReportsApi = createBugReportsApi(defaultHttpClient())
