import { beforeEach, describe, expect, it } from 'vitest'
import { createIssueCardsApi, newDirectIssueKey } from '../services/issueCardsApi'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const api = createIssueCardsApi(client)
beforeEach(() => { client.post.mockReset(); client.patch.mockReset() })

describe('bounded exact-issue card transport', () => {
  it('deduplicates valid owned identifiers and avoids empty network requests', async () => {
    await expect(api.fetchCards([0, -1, 1.5, Number.NaN])).resolves.toEqual([])
    expect(client.post).not.toHaveBeenCalled()
    client.post.mockResolvedValue({ items: [] })
    await api.fetchCards([75, 75, 95, 0])
    expect(client.post).toHaveBeenCalledExactlyOnceWith('/v2/issues/cards', { issue_ids: [75, 95] })
  })

  it('loads a 401-issue list in three bounded batches without rewriting provider URLs', async () => {
    const ids = Array.from({ length: 401 }, (_, i) => i + 1)
    const first = { issue_id: 1, cover_image_url: 'https://comicvine.gamespot.com/a.jpg?original=1' }
    client.post.mockResolvedValueOnce({ items: [first] }).mockResolvedValueOnce({ items: [] }).mockResolvedValueOnce({ items: [{ issue_id: 401 }] })
    await expect(api.fetchCards(ids)).resolves.toEqual([first, { issue_id: 401 }])
    expect(client.post.mock.calls.map((call) => call[1])).toEqual([
      { issue_ids: ids.slice(0, 200) }, { issue_ids: ids.slice(200, 400) }, { issue_ids: [401] },
    ])
  })

  it('reports failed batches without returning a misleading partial list', async () => {
    client.post.mockRejectedValueOnce(new Error('offline'))
    await expect(api.fetchCards([75])).rejects.toThrow('offline')
  })

  it('sends only the chosen correction fields and preserves the retry key', async () => {
    await api.patchIssue(75, { rating: 4, idempotencyKey: 'correction-key' })
    expect(client.patch).toHaveBeenLastCalledWith('/v2/issues/75', { rating: 4, source: 'direct', idempotency_key: 'correction-key' })
    await api.patchIssue(75, { status: 'unread', rating: null, idempotencyKey: 'unread-key' })
    expect(client.patch).toHaveBeenLastCalledWith('/v2/issues/75', { status: 'unread', source: 'direct', idempotency_key: 'unread-key' })
    await api.patchIssue(75, { status: null, idempotencyKey: 'unchanged-key' })
    expect(client.patch).toHaveBeenLastCalledWith('/v2/issues/75', { source: 'direct', idempotency_key: 'unchanged-key' })
  })

  it('generates distinct bounded server-compatible intent keys', () => {
    const keys = Array.from({ length: 20 }, () => newDirectIssueKey())
    expect(new Set(keys).size).toBe(keys.length)
    for (const key of keys) expect(key).toMatch(/^direct-[a-f0-9]{32}$/)
  })
})
