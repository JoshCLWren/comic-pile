import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createIssuesApi } from '../services/api-issues'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()

const issuesApi = createIssuesApi(client)

beforeEach(() => {
  vi.clearAllMocks()
  client.get.mockResolvedValue({ issues: [] })
  client.post.mockResolvedValue({})
  client.put.mockResolvedValue(undefined)
  client.delete.mockResolvedValue(undefined)
})

describe('issuesApi', () => {
  it('lists with optional filters and creates with positioning options', async () => {
    await issuesApi.list(1)
    await issuesApi.list(1, { status: 'read', page_size: 10, page_token: 'next' })
    await issuesApi.create(1, '1-5')
    await issuesApi.create(1, '6-8', { insert_after_issue_id: 4 })
    await issuesApi.create(1, '9', { insert_after_issue_id: null })
    expect(client.get).toHaveBeenNthCalledWith(1, '/v2/threads/1/issues', { params: undefined })
    expect(client.get).toHaveBeenNthCalledWith(2, '/v2/threads/1/issues', { params: { status: 'read', page_size: 10, page_token: 'next' } })
    expect(client.post).toHaveBeenNthCalledWith(1, '/v2/threads/1/issues', { issue_range: '1-5' })
    expect(client.post).toHaveBeenNthCalledWith(2, '/v2/threads/1/issues', { issue_range: '6-8', insert_after_issue_id: 4 })
    expect(client.post).toHaveBeenNthCalledWith(3, '/v2/threads/1/issues', { issue_range: '9', append_to_end: true })
  })

  it('reads creator credits from the thread-scoped v2 projection, paginated or aggregated', async () => {
    client.get.mockResolvedValueOnce({
      thread_id: 1,
      issues: [{ issue_id: 4, creators: [{ name: 'Writer', roles: ['writer'] }] }],
      total_count: 2,
      page_size: 1,
      next_page_token: '1,4',
    })
    const page = await issuesApi.listCreators(1, { page_size: 1 })
    expect(client.get).toHaveBeenNthCalledWith(1, '/v2/threads/1/creatorCredits', {
      params: { page_size: 1 },
    })
    expect(page.next_page_token).toBe('1,4')

    const filtered = await issuesApi.listCreators(2, {
      status: 'read',
      page_size: 10,
      page_token: '3,9',
    })
    expect(client.get).toHaveBeenNthCalledWith(2, '/v2/threads/2/creatorCredits', {
      params: { status: 'read', page_size: 10, page_token: '3,9' },
    })
    expect(filtered.issues).toEqual([])

    client.get.mockReset()
    client.get
      .mockResolvedValueOnce({
        thread_id: 3,
        issues: [],
        total_count: 2,
        page_size: 100,
        next_page_token: '1,4',
      })
      .mockResolvedValueOnce({
        thread_id: 3,
        issues: [{ issue_id: 5, creators: [] }],
        total_count: 2,
        page_size: 100,
        next_page_token: null,
      })
    const all = await issuesApi.listCreators(3)
    expect(client.get).toHaveBeenNthCalledWith(1, '/v2/threads/3/creatorCredits', {
      params: { page_size: 100 },
    })
    expect(client.get).toHaveBeenNthCalledWith(2, '/v2/threads/3/creatorCredits', {
      params: { page_size: 100, page_token: '1,4' },
    })
    expect(all.issues).toHaveLength(1)
    expect(all.next_page_token).toBeNull()
    expect(all.total_count).toBe(2)
  })

  it('previews creates with every positioning and strategy option', async () => {
    await issuesApi.previewCreate(1, '1-5')
    await issuesApi.previewCreate(1, '6-8', { insert_after_issue_id: 4 })
    await issuesApi.previewCreate(1, '9', { insert_after_issue_id: null })
    await issuesApi.previewCreate(1, '10', { strategy: 'numeric_resort' })
    await issuesApi.create(1, '11', { insert_after_issue_id: 4, strategy: 'safe_default' })
    expect(client.post).toHaveBeenNthCalledWith(1, '/v2/threads/1/issues/preview', { issue_range: '1-5' })
    expect(client.post).toHaveBeenNthCalledWith(2, '/v2/threads/1/issues/preview', { issue_range: '6-8', insert_after_issue_id: 4 })
    expect(client.post).toHaveBeenNthCalledWith(3, '/v2/threads/1/issues/preview', { issue_range: '9', append_to_end: true })
    expect(client.post).toHaveBeenNthCalledWith(4, '/v2/threads/1/issues/preview', { issue_range: '10', strategy: 'numeric_resort' })
    expect(client.post).toHaveBeenNthCalledWith(5, '/v2/threads/1/issues', { issue_range: '11', insert_after_issue_id: 4, strategy: 'safe_default' })
  })

  it('calls issue mutations and migration endpoints', async () => {
    await issuesApi.get(2)
    await issuesApi.markRead(2)
    await issuesApi.markUnread(2)
    await issuesApi.move(2, null)
    await issuesApi.reorder(3, [1, 2])
    await issuesApi.delete(4)
    await issuesApi.migrateThread(5, 2, 10)
    expect(client.get).toHaveBeenCalledWith('/v2/issues/2')
    expect(client.post).toHaveBeenCalledWith('/v2/issues/2/read-markers')
    expect(client.delete).toHaveBeenCalledWith('/v2/issues/2/read-markers')
    expect(client.put).toHaveBeenCalledWith('/v2/issues/2/position', { after_issue_id: null })
    expect(client.put).toHaveBeenCalledWith('/v2/threads/3/issue-order', { issue_ids: [1, 2] })
    expect(client.delete).toHaveBeenCalledWith('/v2/issues/4')
    expect(client.post).toHaveBeenCalledWith('/v1/threads/5:migrateToIssues', { last_issue_read: 2, total_issues: 10 })
  })
})
