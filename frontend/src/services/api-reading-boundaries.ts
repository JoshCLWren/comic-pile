import { defaultHttpClient, type HttpClient } from './httpClient'
import type { components } from '../generated/openapi'

export type ReadingBoundaryExplanation = components['schemas']['ReadingBoundaryExplanation']
export type BoundaryEditorTarget = components['schemas']['BoundaryEditorTarget']
export type BoundaryIssue = components['schemas']['BoundaryIssue']
type Batch = components['schemas']['ReadingBoundaryBatchResponse']

/** Read canonical explanations in bounded batches, never one request per Queue row. */
export function createReadingBoundariesApi(client: HttpClient) {
  return {
    async batch(threadIds: number[]): Promise<Batch> {
      const pages: Promise<Batch>[] = []
      for (let offset = 0; offset < threadIds.length; offset += 200) {
        pages.push(client.post<Batch, { thread_ids: number[] }>(
          '/v1/reading-boundaries', { thread_ids: threadIds.slice(offset, offset + 200) },
        ))
      }
      const responses = await Promise.all(pages)
      return { threads: Object.assign({}, ...responses.map((page) => page.threads)) }
    },
  }
}

export const readingBoundariesApi = createReadingBoundariesApi(defaultHttpClient())
