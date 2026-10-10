import { describe, expect, it, vi } from 'vitest'

import { createTagsApi, type TagsApi } from '../services/api-tags'
import type { Tag, TagBulkOperation } from '../types'
import type { HttpClient } from '../services/httpClient'

function makeClient(): HttpClient & {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
} {
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  } as unknown as HttpClient & {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
  }
}

function tagFixture(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'Horror',
    normalized_name: 'horror',
    scope: 'global',
    owner_user_id: null,
    color: '#DC2626',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('tagsApi', () => {
  describe('listTags', () => {
    it('unwraps the tag list envelope from the collection endpoint', async () => {
      const client = makeClient()
      const tag = tagFixture()
      client.get.mockResolvedValue({ tags: [tag] })
      const api: TagsApi = createTagsApi(client)

      await expect(api.listTags()).resolves.toEqual([tag])
      expect(client.get).toHaveBeenCalledWith('/v1/tags/')
    })
  })

  describe('getTag', () => {
    it('requests a single tag by id', async () => {
      const client = makeClient()
      const tag = tagFixture({ id: 5, name: 'Physical' })
      client.get.mockResolvedValue(tag)
      const api: TagsApi = createTagsApi(client)

      await expect(api.getTag(5)).resolves.toEqual(tag)
      expect(client.get).toHaveBeenCalledWith('/v1/tags/5/')
    })
  })

  describe('createTag', () => {
    it('returns the full creation envelope so callers can see a global redirect', async () => {
      const client = makeClient()
      const response = {
        tag: tagFixture({ id: 9, name: 'Cosmic', scope: 'private' as const }),
        redirected_to_global: false,
        near_matches: [],
      }
      client.post.mockResolvedValue(response)
      const api: TagsApi = createTagsApi(client)

      await expect(
        api.createTag({ name: 'Cosmic', scope: 'private', include_near_matches: true }),
      ).resolves.toEqual(response)
      expect(client.post).toHaveBeenCalledWith('/v1/tags/', {
        name: 'Cosmic',
        scope: 'private',
        include_near_matches: true,
      })
    })

    it('surfaces an exact normalized match as a redirected global tag', async () => {
      const client = makeClient()
      const globalTag = tagFixture({ id: 2, name: 'Horror', scope: 'global' })
      client.post.mockResolvedValue({
        tag: globalTag,
        redirected_to_global: true,
        near_matches: [],
      })
      const api: TagsApi = createTagsApi(client)

      const result = await api.createTag({ name: 'horror', scope: 'private' })

      expect(result.redirected_to_global).toBe(true)
      expect(result.tag).toEqual(globalTag)
    })
  })

  describe('updateTag', () => {
    it('sends a PUT to the tag resource', async () => {
      const client = makeClient()
      const renamed = tagFixture({ id: 3, name: 'Supernatural', normalized_name: 'supernatural' })
      client.put.mockResolvedValue(renamed)
      const api: TagsApi = createTagsApi(client)

      await expect(api.updateTag(3, { name: 'Supernatural' })).resolves.toEqual(renamed)
      expect(client.put).toHaveBeenCalledWith('/v1/tags/3/', { name: 'Supernatural' })
    })
  })

  describe('deleteTag', () => {
    it('returns the deletion summary including cascaded assignment counts', async () => {
      const client = makeClient()
      const result = { tag_id: 3, assignments_removed: 4, references_removed_by_consumers: {} }
      client.delete.mockResolvedValue(result)
      const api: TagsApi = createTagsApi(client)

      await expect(api.deleteTag(3)).resolves.toEqual(result)
      expect(client.delete).toHaveBeenCalledWith('/v1/tags/3/')
    })
  })

  describe('assignTag and unassignTag', () => {
    it('assigns a tag to a target', async () => {
      const client = makeClient()
      const request = { target_type: 'Issue' as const, target_id: 11 }
      client.post.mockResolvedValue({ id: 1, tag_id: 3, ...request, created_at: '2026-01-01T00:00:00Z' })
      const api: TagsApi = createTagsApi(client)

      await api.assignTag(3, request)

      expect(client.post).toHaveBeenCalledWith('/v1/tags/3/assign/', request)
    })

    it('unassigns a tag using a DELETE with a request body', async () => {
      const client = makeClient()
      const request = { target_type: 'ContinuityPlan' as const, target_id: 42 }
      client.delete.mockResolvedValue({ id: 1, tag_id: 3, ...request, created_at: '2026-01-01T00:00:00Z' })
      const api: TagsApi = createTagsApi(client)

      await api.unassignTag(3, request)

      expect(client.delete).toHaveBeenCalledWith('/v1/tags/3/unassign/', { data: request })
    })
  })

  describe('getTagUsage', () => {
    it('reads the usage counts used to confirm a deletion', async () => {
      const client = makeClient()
      const usage = {
        tag_id: 3,
        total_assignments: 7,
        assignments_by_target_type: { Issue: 5, Thread: 2 },
        references_removed_by_consumers: {},
      }
      client.get.mockResolvedValue(usage)
      const api: TagsApi = createTagsApi(client)

      await expect(api.getTagUsage(3)).resolves.toEqual(usage)
      expect(client.get).toHaveBeenCalledWith('/v1/tags/3/usage/')
    })
  })

  describe('getEffectiveTags', () => {
    it.each([
      ['Issue', '/v1/tags/effective/issue/11/'],
      ['Thread', '/v1/tags/effective/thread/11/'],
      ['ContinuityPlan', '/v1/tags/effective/plan/11/'],
    ] as const)('uses the %s url segment for effective tags', async (targetType, expectedUrl) => {
      const client = makeClient()
      const effective = { target_type: targetType, target_id: 11, direct_tags: [], effective_tags: [] }
      client.get.mockResolvedValue(effective)
      const api: TagsApi = createTagsApi(client)

      await api.getEffectiveTags(targetType, 11)

      expect(client.get).toHaveBeenCalledWith(expectedUrl)
    })
  })

  describe('bulkTagOperations', () => {
    it('fans an add operation out to one assignment call per target', async () => {
      const client = makeClient()
      client.post.mockResolvedValue({})
      const api: TagsApi = createTagsApi(client)
      const operations: TagBulkOperation[] = [
        { tag_id: 21, target_type: 'Issue', target_ids: [1, 2], action: 'add' },
      ]

      await api.bulkTagOperations(operations)

      expect(client.post).toHaveBeenCalledTimes(2)
      expect(client.post).toHaveBeenCalledWith('/v1/tags/21/assign/', {
        target_type: 'Issue',
        target_id: 1,
      })
      expect(client.post).toHaveBeenCalledWith('/v1/tags/21/assign/', {
        target_type: 'Issue',
        target_id: 2,
      })
    })

    it('fans a remove operation out to one unassignment call per target', async () => {
      const client = makeClient()
      client.delete.mockResolvedValue({})
      const api: TagsApi = createTagsApi(client)
      const operations: TagBulkOperation[] = [
        { tag_id: 21, target_type: 'ContinuityPlan', target_ids: [5], action: 'remove' },
      ]

      await api.bulkTagOperations(operations)

      expect(client.delete).toHaveBeenCalledWith('/v1/tags/21/unassign/', {
        data: { target_type: 'ContinuityPlan', target_id: 5 },
      })
      expect(client.post).not.toHaveBeenCalled()
    })

    it('only touches the requested tag assignment and leaves other tags alone', async () => {
      const client = makeClient()
      client.post.mockResolvedValue({})
      const api: TagsApi = createTagsApi(client)
      const operations: TagBulkOperation[] = [
        { tag_id: 21, target_type: 'Issue', target_ids: [1, 2, 3], action: 'add' },
      ]

      await api.bulkTagOperations(operations)

      const touchedTagIds = client.post.mock.calls.map(
        ([url]) => (url as string).split('/')[3],
      )
      expect(new Set(touchedTagIds)).toEqual(new Set(['21']))
      expect(client.post).toHaveBeenCalledTimes(3)
    })
  })
})