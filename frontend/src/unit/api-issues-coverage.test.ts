import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createIssuesApi } from '../services/api-issues'

const client = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}

const issuesApi = createIssuesApi(client)

beforeEach(() => {
  vi.clearAllMocks()
  client.get.mockResolvedValue({ issues: [] })
  client.post.mockResolvedValue({})
  client.delete.mockResolvedValue(undefined)
})

describe('issuesApi', () => {
  it('lists with optional filters and creates with positioning options', async () => {
    await issuesApi.list(1)
    await issuesApi.list(1, { status: 'read', page_size: 10, page_token: 'next' })
    await issuesApi.create(1, '1-5')
    await issuesApi.create(1, '6-8', { insert_after_issue_id: 4 })
    await issuesApi.create(1, '9', { insert_after_issue_id: null })
    expect(client.get).toHaveBeenNthCalledWith(1, '/v1/threads/1/issues', { params: undefined })
    expect(client.get).toHaveBeenNthCalledWith(2, '/v1/threads/1/issues', { params: { status: 'read', page_size: 10, page_token: 'next' } })
    expect(client.post).toHaveBeenNthCalledWith(1, '/v1/threads/1/issues', { issue_range: '1-5' })
    expect(client.post).toHaveBeenNthCalledWith(2, '/v1/threads/1/issues', { issue_range: '6-8', insert_after_issue_id: 4 })
    expect(client.post).toHaveBeenNthCalledWith(3, '/v1/threads/1/issues', { issue_range: '9', insert_after_issue_id: null })
  })

  it('calls issue mutations and migration endpoints', async () => {
    await issuesApi.get(2)
    await issuesApi.markRead(2)
    await issuesApi.markUnread(2)
    await issuesApi.move(2, null)
    await issuesApi.reorder(3, [1, 2])
    await issuesApi.delete(4)
    await issuesApi.migrateThread(5, 2, 10)
    expect(client.get).toHaveBeenCalledWith('/v1/issues/2')
    expect(client.post).toHaveBeenCalledWith('/v1/issues/2:markRead')
    expect(client.post).toHaveBeenCalledWith('/v1/issues/2:markUnread')
    expect(client.post).toHaveBeenCalledWith('/v1/issues/2:move', { after_issue_id: null })
    expect(client.post).toHaveBeenCalledWith('/v1/threads/3/issues:reorder', { issue_ids: [1, 2] })
    expect(client.delete).toHaveBeenCalledWith('/v1/issues/4')
    expect(client.post).toHaveBeenCalledWith('/v1/threads/5:migrateToIssues', { last_issue_read: 2, total_issues: 10 })
  })
})
