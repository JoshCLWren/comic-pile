import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createTagsApi } from '../services/api-tags'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const tagsApi = createTagsApi(client)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('tagsApi routes (issue #3032)', () => {
  it('lists tags and omits the search param for a blank filter', async () => {
    client.get.mockResolvedValue({ tags: [] })

    await tagsApi.list()
    await tagsApi.list('  ')
    await tagsApi.list('  physical ')

    expect(client.get).toHaveBeenNthCalledWith(1, '/v1/tags/', {
      params: undefined,
    })
    expect(client.get).toHaveBeenNthCalledWith(2, '/v1/tags/', {
      params: undefined,
    })
    expect(client.get).toHaveBeenNthCalledWith(3, '/v1/tags/', {
      params: { search: 'physical' },
    })
  })

  it('reads, updates, and deletes one tag', async () => {
    client.get.mockResolvedValue({ id: 3, name: 'Horror' })
    client.put.mockResolvedValue({ id: 3, name: 'Fear' })
    client.delete.mockResolvedValue({ tag_id: 3, assignments_removed: 2 })

    await tagsApi.get(3)
    await tagsApi.update(3, { name: 'Fear', color: 'blue' })
    await tagsApi.delete(3)

    expect(client.get).toHaveBeenCalledWith('/v1/tags/3/')
    expect(client.put).toHaveBeenCalledWith('/v1/tags/3/', { name: 'Fear', color: 'blue' })
    expect(client.delete).toHaveBeenCalledWith('/v1/tags/3/')
  })

  it('creates a tag and reads usage for the delete confirmation', async () => {
    client.post.mockResolvedValue({ tag: { id: 9 }, near_matches: [] })
    client.get.mockResolvedValue({ tag_id: 9, total_assignments: 1 })

    await tagsApi.create({ name: 'Physical', color: 'red', include_near_matches: true })
    await tagsApi.usage(9)

    expect(client.post).toHaveBeenCalledWith('/v1/tags/', {
      name: 'Physical',
      color: 'red',
      include_near_matches: true,
    })
    expect(client.get).toHaveBeenCalledWith('/v1/tags/9/usage/')
  })

  it('assigns and unassigns one tag on a single target', async () => {
    client.post.mockResolvedValue({ id: 1, tag_id: 3 })
    client.delete.mockResolvedValue({ id: 1, tag_id: 3 })

    await tagsApi.assign(3, { target_type: 'Issue', target_id: 11 })
    await tagsApi.unassign(3, { target_type: 'Thread', target_id: 4 })

    expect(client.post).toHaveBeenCalledWith('/v1/tags/3/assign/', {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(client.delete).toHaveBeenCalledWith('/v1/tags/3/unassign/', {
      data: { target_type: 'Thread', target_id: 4 },
    })
  })

  it('bulk assigns and bulk unassigns across many targets', async () => {
    client.post.mockResolvedValue({ tag_id: 3, affected_ids: [1], already_ids: [2] })

    await tagsApi.bulkAssign(3, { target_type: 'Issue', target_ids: [1, 2] })
    await tagsApi.bulkUnassign(3, { target_type: 'Issue', target_ids: [1, 2] })

    expect(client.post).toHaveBeenNthCalledWith(1, '/v1/tags/3/bulk-assign/', {
      target_type: 'Issue',
      target_ids: [1, 2],
    })
    expect(client.post).toHaveBeenNthCalledWith(2, '/v1/tags/3/bulk-unassign/', {
      target_type: 'Issue',
      target_ids: [1, 2],
    })
  })

  it('reads effective tags per supported target type', async () => {
    client.get.mockResolvedValue({ target_type: 'Issue', target_id: 1, effective_tags: [] })

    await tagsApi.effectiveForIssue(11)
    await tagsApi.effectiveForThread(4)
    await tagsApi.effectiveForPlan(9)

    expect(client.get).toHaveBeenNthCalledWith(1, '/v1/tags/effective/issue/11/')
    expect(client.get).toHaveBeenNthCalledWith(2, '/v1/tags/effective/thread/4/')
    expect(client.get).toHaveBeenNthCalledWith(3, '/v1/tags/effective/plan/9/')
  })

  it('reads bulk effective tags for every issue in a thread (issue #3422)', async () => {
    client.get.mockResolvedValue({ thread_id: 4, issues: [] })

    await tagsApi.threadIssuesEffective(4)

    expect(client.get).toHaveBeenCalledWith('/v1/tags/effective/thread/4/issues/')
  })
})