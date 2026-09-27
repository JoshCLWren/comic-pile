import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createDependencyGroupsApi } from '../services/api-dependency-groups'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const dependencyGroupsApi = createDependencyGroupsApi(client)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('dependencyGroupsApi', () => {
  it('uses the ownership-scoped group collection routes', async () => {
    client.get.mockResolvedValueOnce([])
    client.post.mockResolvedValueOnce({ id: 1, name: 'Cosmic', memberships: [] })

    await dependencyGroupsApi.list()
    await dependencyGroupsApi.create('Cosmic')

    expect(client.get).toHaveBeenCalledWith('/v1/reading-order-groups/')
    expect(client.post).toHaveBeenCalledWith(
      '/v1/reading-order-groups/',
      { name: 'Cosmic' },
    )
  })

  it('loads group details', async () => {
    const group = {
      id: 3,
      name: 'Infinity',
      created_at: '2026-01-01T00:00:00Z',
      memberships: [],
    }
    client.get.mockResolvedValueOnce(group)

    await expect(dependencyGroupsApi.get(3)).resolves.toEqual(group)

    expect(client.get).toHaveBeenCalledWith(
      '/v1/reading-order-groups/3',
    )
  })

  it('supports group rename and deletion', async () => {
    client.patch.mockResolvedValue({ id: 3, name: 'Infinity', memberships: [] })
    client.delete.mockResolvedValue(undefined)

    await dependencyGroupsApi.rename(3, 'Infinity')
    await dependencyGroupsApi.delete(3)

    expect(client.patch).toHaveBeenCalledWith(
      '/v1/reading-order-groups/3',
      { name: 'Infinity' },
    )
    expect(client.delete).toHaveBeenCalledWith('/v1/reading-order-groups/3')
  })

  it('loads compact group names for the Roll view', async () => {
    client.get.mockResolvedValue([{ id: 7, name: 'Annihilation' }])

    await expect(dependencyGroupsApi.listForThread(42)).resolves.toEqual([
      { id: 7, name: 'Annihilation' },
    ])

    expect(client.get).toHaveBeenCalledWith(
      '/v1/reading-order-groups/threads/42/groups',
    )
  })

  it('loads multiple thread groups through routes that exist on the backend', async () => {
    client.get
      .mockResolvedValueOnce([{ id: 7, name: 'Annihilation' }])
      .mockResolvedValueOnce([])

    await expect(dependencyGroupsApi.listForThreads([42, 43])).resolves.toEqual({
      42: [{ id: 7, name: 'Annihilation' }],
      43: [],
    })

    expect(client.get).toHaveBeenNthCalledWith(
      1,
      '/v1/reading-order-groups/threads/42/groups',
    )
    expect(client.get).toHaveBeenNthCalledWith(
      2,
      '/v1/reading-order-groups/threads/43/groups',
    )
    expect(client.post).not.toHaveBeenCalledWith(
      '/v1/reading-order-groups/threads/groups:batch',
      expect.anything(),
    )
  })

  it('adds inclusive issue-position ranges', async () => {
    const result = {
      thread_id: 42,
      start_position: 1,
      end_position: 8,
      added_issue_ids: [10, 11],
      already_present_issue_ids: [9],
    }
    client.post.mockResolvedValueOnce(result)

    await expect(dependencyGroupsApi.addIssueRange(7, 42, 1, 8)).resolves.toEqual(result)

    expect(client.post).toHaveBeenCalledWith(
      '/v1/reading-order-groups/7/issue-ranges',
      {
        thread_id: 42,
        start_position: 1,
        end_position: 8,
      },
    )
  })

  it('adds and removes both supported membership target types', async () => {
    client.post
      .mockResolvedValueOnce({ id: 10, thread_id: 42, issue_id: null })
      .mockResolvedValueOnce({ id: 11, thread_id: null, issue_id: 99 })
    client.delete.mockResolvedValue(undefined)

    await dependencyGroupsApi.addMember(7, { thread_id: 42 })
    await dependencyGroupsApi.addMember(7, { issue_id: 99 })
    await dependencyGroupsApi.removeMember(7, 10)

    expect(client.post).toHaveBeenNthCalledWith(
      1,
      '/v1/reading-order-groups/7/members',
      { thread_id: 42 },
    )
    expect(client.post).toHaveBeenNthCalledWith(
      2,
      '/v1/reading-order-groups/7/members',
      { issue_id: 99 },
    )
    expect(client.delete).toHaveBeenCalledWith(
      '/v1/reading-order-groups/7/members/10',
    )
  })
})
