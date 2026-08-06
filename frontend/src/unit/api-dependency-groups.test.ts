import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
      ...apiMock,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    })),
  },
}))

import { dependencyGroupsApi } from '../services/api-dependency-groups'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('dependencyGroupsApi', () => {
  it('uses the ownership-scoped group collection routes', async () => {
    apiMock.get.mockResolvedValueOnce([])
    apiMock.post.mockResolvedValueOnce({ id: 1, name: 'Cosmic', memberships: [] })

    await dependencyGroupsApi.list()
    await dependencyGroupsApi.create('Cosmic')

    expect(apiMock.get).toHaveBeenCalledWith('/v1/reading-order-groups/')
    expect(apiMock.post).toHaveBeenCalledWith(
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
    apiMock.get.mockResolvedValueOnce(group)

    await expect(dependencyGroupsApi.get(3)).resolves.toEqual(group)

    expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/reading-order-groups/3',
    )
  })

  it('supports group rename and deletion', async () => {
    apiMock.patch.mockResolvedValue({ id: 3, name: 'Infinity', memberships: [] })
    apiMock.delete.mockResolvedValue(undefined)

    await dependencyGroupsApi.rename(3, 'Infinity')
    await dependencyGroupsApi.delete(3)

    expect(apiMock.patch).toHaveBeenCalledWith(
      '/v1/reading-order-groups/3',
      { name: 'Infinity' },
    )
    expect(apiMock.delete).toHaveBeenCalledWith('/v1/reading-order-groups/3')
  })

  it('loads compact group names for the Roll view', async () => {
    apiMock.get.mockResolvedValue([{ id: 7, name: 'Annihilation' }])

    await expect(dependencyGroupsApi.listForThread(42)).resolves.toEqual([
      { id: 7, name: 'Annihilation' },
    ])

    expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/reading-order-groups/threads/42/groups',
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
    apiMock.post.mockResolvedValueOnce(result)

    await expect(dependencyGroupsApi.addIssueRange(7, 42, 1, 8)).resolves.toEqual(result)

    expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/reading-order-groups/7/issue-ranges',
      {
        thread_id: 42,
        start_position: 1,
        end_position: 8,
      },
    )
  })

  it('adds and removes both supported membership target types', async () => {
    apiMock.post
      .mockResolvedValueOnce({ id: 10, thread_id: 42, issue_id: null })
      .mockResolvedValueOnce({ id: 11, thread_id: null, issue_id: 99 })
    apiMock.delete.mockResolvedValue(undefined)

    await dependencyGroupsApi.addMember(7, { thread_id: 42 })
    await dependencyGroupsApi.addMember(7, { issue_id: 99 })
    await dependencyGroupsApi.removeMember(7, 10)

    expect(apiMock.post).toHaveBeenNthCalledWith(
      1,
      '/v1/reading-order-groups/7/members',
      { thread_id: 42 },
    )
    expect(apiMock.post).toHaveBeenNthCalledWith(
      2,
      '/v1/reading-order-groups/7/members',
      { issue_id: 99 },
    )
    expect(apiMock.delete).toHaveBeenCalledWith(
      '/v1/reading-order-groups/7/members/10',
    )
  })
})
