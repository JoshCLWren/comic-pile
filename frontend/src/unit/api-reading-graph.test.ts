import { describe, expect, it } from 'vitest'

import { createReadingGraphApi } from '../services/api-reading-graph'
import type { ReadingGraphPreview, ReadingGraphPreviewRequest } from '../services/api-reading-graph'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const readingGraphApi = createReadingGraphApi(client)

const request: ReadingGraphPreviewRequest = {
  included_positions: [1, 2],
  overlap_choices: [{ overlap_id: 'bprd|other', choice: 'protect_order' }],
}

// SAFETY: the preview fixture only supplies fields the transport test reads
const preview = {
  source_list_id: 42,
  content_hash: 'hash-42',
  revision_sha: 'abcdef1234567890',
  series: [],
  overlaps: [],
  issues: [],
  rollable_issue_ids: [1],
  waiting_issue_ids: [2],
  cycle_errors: [],
} as ReadingGraphPreview

describe('readingGraphApi.preview (#5714)', () => {
  it('posts to the v2 AIP-136 custom method with the source selection intact', async () => {
    client.post.mockReset()
    client.post.mockResolvedValueOnce(preview)

    const result = await readingGraphApi.preview(42, request)

    expect(client.post).toHaveBeenCalledTimes(1)
    expect(client.post).toHaveBeenCalledWith('/v2/cblSources/42:previewReadingGraph', request)
    expect(result).toBe(preview)
  })

  it('never calls the retired v1 reading-graph-preview path', async () => {
    client.post.mockReset()
    client.post.mockResolvedValueOnce(preview)

    await readingGraphApi.preview(42, request)

    const calledUrl = String(client.post.mock.calls[0]?.[0])
    expect(calledUrl).not.toContain('/v1/issue-identity/cbl/')
    expect(calledUrl).not.toContain('reading-graph-preview')
  })
})
