import { beforeEach, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
const del = vi.fn()

const apiMock = {
  get,
  post,
  put,
  delete: del,
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { queueApi, settingsApi, threadsApi } from '../services/api'

beforeEach(() => {
  get.mockResolvedValue({})
  post.mockResolvedValue({})
  put.mockResolvedValue({})
  del.mockResolvedValue({})
})

it('calls thread endpoints with expected paths', () => {
  threadsApi.list()
  threadsApi.get(9)

  expect(get).toHaveBeenCalledWith('/threads/')
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

it('calls settings endpoints with expected paths', () => {
  settingsApi.get()
  settingsApi.update({ start_die: 8 })

  expect(get).toHaveBeenCalledWith('/admin/settings')
  expect(put).toHaveBeenCalledWith('/admin/settings', { start_die: 8 })
})
