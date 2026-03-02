import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}))

const { get, post, put } = apiMock
const del = apiMock.delete

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { dependenciesApi, queueApi, threadsApi } from '../services/api'

beforeEach(() => {
  get.mockResolvedValue({})
  post.mockResolvedValue({})
  put.mockResolvedValue({})
  del.mockResolvedValue({})
})

it('calls thread endpoints with expected paths', () => {
  threadsApi.list()
  threadsApi.list({ search: 'bat' })
  threadsApi.get(9)

  expect(get).toHaveBeenCalledWith('/threads/', { params: undefined })
  expect(get).toHaveBeenCalledWith('/threads/', { params: { search: 'bat' } })
  expect(get).toHaveBeenCalledWith('/threads/9')
})

it('calls queue endpoints with expected paths', () => {
  queueApi.moveToPosition(3, 2)
  queueApi.moveToFront(4)
  queueApi.moveToBack(5)

  expect(put).toHaveBeenCalledWith('/queue/threads/3/position/', { new_position: 2 })
  expect(put).toHaveBeenCalledWith('/queue/threads/4/front/')
  expect(put).toHaveBeenCalledWith('/queue/threads/5/back/')
})

it('calls dependency endpoints with expected paths', () => {
  dependenciesApi.listBlockedThreadIds()
  dependenciesApi.listThreadDependencies(11)
  dependenciesApi.getBlockingInfo(12)
  dependenciesApi.createDependency({ sourceId: 1, targetId: 2 })
  dependenciesApi.deleteDependency(7)

  expect(get).toHaveBeenCalledWith('/v1/dependencies/blocked')
  expect(get).toHaveBeenCalledWith('/v1/threads/11/dependencies')
  expect(post).toHaveBeenCalledWith('/v1/threads/12:getBlockingInfo')
  expect(post).toHaveBeenCalledWith('/v1/dependencies/', {
    source_type: 'thread',
    source_id: 1,
    target_type: 'thread',
    target_id: 2,
  })
  expect(del).toHaveBeenCalledWith('/v1/dependencies/7')
})
