import { defaultHttpClient, type HttpClient } from './httpClient'
import type { components } from '../generated/openapi'

/** Canonical v2 is Rust-owned and contains no retired historical associations. */
export type ReadingBoundaryExplanation = components['schemas']['ReadingBoundaryExplanationV2']
export type BoundaryEditorTarget = components['schemas']['BoundaryEditorTarget']
export type BoundaryIssue = components['schemas']['BoundaryIssue']
type Batch = components['schemas']['ReadingBoundaryBatchResponseV2']

/** Read canonical explanations in bounded batches, never one request per Queue row. */
export function createReadingBoundariesApi(client: HttpClient) {
  return {
    async batch(threadIds: number[]): Promise<Batch> {
      const pages: Promise<Batch>[] = []
      for (let offset = 0; offset < threadIds.length; offset += 200) {
        pages.push(client.post<Batch, { thread_ids: number[] }>(
          '/v2/reading-boundaries', { thread_ids: threadIds.slice(offset, offset + 200) },
        ))
      }
      const responses = await Promise.all(pages)
      // A rollout can change the authority between concurrent page requests.
      // Preserve every successful projection but conservatively select the
      // legacy authority for the combined batch; a later discovery can recover
      // the canonical evaluator after the deployment settles. Missing fields
      // from an older function revision also take the safe legacy path.
      const evaluator = responses.length > 0 &&
        responses.every((page) => page.evaluator === 'enabled')
        ? 'enabled'
        : 'unavailable'
      return {
        threads: Object.assign({}, ...responses.map((page) => page.threads)),
        evaluator,
      }
    },
  }
}

export const readingBoundariesApi = createReadingBoundariesApi(defaultHttpClient())
