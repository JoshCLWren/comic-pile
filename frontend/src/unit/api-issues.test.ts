import { beforeEach, expect, it } from 'vitest'

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

it('migrates a thread through scoped v2 issue resources', async () => {
  const issues = Array.from({ length: 12 }, (_, index) => ({
    id: index + 100,
    issue_number: String(index + 1),
  }))
  client.post.mockResolvedValueOnce({ issues, next_page_token: null })
  client.get.mockResolvedValueOnce({ id: 42, total_issues: 12 })

  const thread = await issuesApi.migrateThread(42, 7, 12)

  expect(client.post).toHaveBeenNthCalledWith(1, '/v2/threads/42/issues', {
    issue_range: '1-12',
  })
  expect(client.post).toHaveBeenNthCalledWith(2, '/v2/issue-read-markers', {
    issue_ids: issues.slice(0, 7).map((issue) => issue.id),
  })
  expect(client.get).toHaveBeenCalledWith('/v1/threads/42')
  expect(thread).toEqual({ id: 42, total_issues: 12 })
})

it('chunks bulk read markers at 100 issues without per-issue requests', async () => {
  const issues = Array.from({ length: 205 }, (_, index) => ({ id: index + 1 }))
  client.post.mockResolvedValueOnce({ issues, next_page_token: null })

  await issuesApi.migrateThread(9, 205, 205)

  expect(client.post).toHaveBeenCalledTimes(4)
  expect(client.post).toHaveBeenNthCalledWith(2, '/v2/issue-read-markers', {
    issue_ids: issues.slice(0, 100).map((issue) => issue.id),
  })
  expect(client.post).toHaveBeenNthCalledWith(3, '/v2/issue-read-markers', {
    issue_ids: issues.slice(100, 200).map((issue) => issue.id),
  })
  expect(client.post).toHaveBeenNthCalledWith(4, '/v2/issue-read-markers', {
    issue_ids: issues.slice(200, 205).map((issue) => issue.id),
  })
})

it('rejects unbounded migration input before making any request', async () => {
  await expect(issuesApi.migrateThread(42, 2, 10_001)).rejects.toThrow(/Invalid migration values/)
  await expect(issuesApi.migrateThread(42, -1, 10)).rejects.toThrow(/Invalid migration values/)
  await expect(issuesApi.migrateThread(42, 11, 10)).rejects.toThrow(/Invalid migration values/)
  expect(client.post).not.toHaveBeenCalled()
  expect(client.get).not.toHaveBeenCalled()
})

it('propagates an ownership denial without later progress writes', async () => {
  const denial = new Error('Thread not found')
  client.post.mockRejectedValueOnce(denial)

  await expect(issuesApi.migrateThread(42, 5, 10)).rejects.toBe(denial)

  expect(client.post).toHaveBeenCalledTimes(1)
  expect(client.get).not.toHaveBeenCalled()
})
