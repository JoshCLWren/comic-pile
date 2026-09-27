import { beforeEach, expect, it, vi } from 'vitest'

import { createIssuesApi } from '../services/api-issues'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const issuesApi = createIssuesApi(client)

beforeEach(() => {
  client.get.mockReset()
  client.post.mockReset()
  client.delete.mockReset()
  client.post.mockResolvedValue({})
})

it('uses the canonical thread route when migrating a thread to issue tracking', async () => {
  await issuesApi.migrateThread(42, 7, 12)

  expect(client.post).toHaveBeenCalledWith('/v1/threads/42:migrateToIssues', {
    last_issue_read: 7,
    total_issues: 12,
  })
})
