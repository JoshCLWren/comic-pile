import { createIssueCardsApi, newDirectIssueKey, type IssueCard } from '../services/issueCardsApi'
import { createHttpClientStub } from './httpClientStub'
import type { components } from '../generated/openapi'
import { beforeEach, describe, expect, it } from 'vitest'

const client = createHttpClientStub()
const api = createIssueCardsApi(client)

const CARD = (issueId: number, extra?: Partial<IssueCard>): IssueCard => ({
  issue_id: issueId,
  thread_id: 7,
  thread_title: 'Hellboy in Hell',
  issue_number: '3',
  status: 'unread',
  read_at: null,
  rating: null,
  has_confirmed_identity: true,
  mapping_state: 'confirmed',
  comicvine_issue_id: '36956',
  cover_image_url: 'https://comicvine.gamespot.com/a/uploads/scale_medium/36956-hellboy-in-hell-3.jpg',
  ...extra,
})

beforeEach(() => {
  client.post.mockReset()
  client.patch.mockReset()
})

describe('issueCardsApi', () => {
  it('fetches one bounded batch for a visible set of ids', async () => {
    client.post.mockResolvedValue({ items: [CARD(11), CARD(12)] } as components['schemas']['IssueCardsResponse'])

    const cards = await api.fetchCards([11, 12])

    expect(cards).toHaveLength(2)
    expect(client.post).toHaveBeenCalledTimes(1)
    expect(client.post).toHaveBeenCalledWith('/v2/issues/cards', { issue_ids: [11, 12] })
  })

  it('chunks lists beyond the server bound instead of one request per row', async () => {
    client.post.mockResolvedValue({ items: [] } as components['schemas']['IssueCardsResponse'])
    const ids = Array.from({ length: 250 }, (_, index) => index + 1)

    const cards = await api.fetchCards(ids)

    expect(cards).toEqual([])
    expect(client.post).toHaveBeenCalledTimes(2)
    const firstCall = client.post.mock.calls[0][1] as components['schemas']['IssueCardsRequest']
    const secondCall = client.post.mock.calls[1][1] as components['schemas']['IssueCardsRequest']
    expect(firstCall.issue_ids).toHaveLength(200)
    expect(secondCall.issue_ids).toHaveLength(50)
  })

  it('writes a direct read with the exact native contract', async () => {
    client.patch.mockResolvedValue({})

    const key = newDirectIssueKey()
    await api.patchIssue(77, { status: 'read', rating: 4.5, idempotencyKey: key })

    expect(client.patch).toHaveBeenCalledTimes(1)
    expect(client.patch).toHaveBeenCalledWith(
      '/v2/issues/77',
      expect.objectContaining({
        idempotency_key: key,
        source: 'direct',
        status: 'read',
        rating: 4.5,
      }),
    )
  })

  it('omits status for a rating-only correction and rating for an unread correction', async () => {
    client.patch.mockResolvedValue({})

    await api.patchIssue(77, { rating: 4, idempotencyKey: newDirectIssueKey() })
    await api.patchIssue(77, { status: 'unread', idempotencyKey: newDirectIssueKey() })

    expect(client.patch.mock.calls[0][1]).toMatchObject({ source: 'direct', rating: 4 })
    expect(client.patch.mock.calls[0][1]).not.toHaveProperty('status')
    expect(client.patch.mock.calls[1][1]).toMatchObject({ source: 'direct', status: 'unread' })
    expect(client.patch.mock.calls[1][1]).not.toHaveProperty('rating')
  })

  it('generates server-valid idempotency keys', () => {
    const key = newDirectIssueKey()
    expect(key).toMatch(/^[A-Za-z0-9_-]{8,128}$/)
    expect(newDirectIssueKey()).not.toBe(key)
  })
})
