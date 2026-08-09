import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('../services/api', () => ({
  default: apiMock,
}))

import { issuesApi } from '../services/api-issues'

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.delete.mockReset()
  apiMock.post.mockResolvedValue({})
})

it('uses the canonical thread route when migrating a thread to issue tracking', async () => {
  await issuesApi.migrateThread(42, 7, 12)

  expect(apiMock.post).toHaveBeenCalledWith('/v1/threads/42:migrateToIssues', {
    last_issue_read: 7,
    total_issues: 12,
  })
})
