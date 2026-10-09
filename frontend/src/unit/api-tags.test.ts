import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { tagsApi } from '../services/api-tags'

function jsonResponse(data: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 500,
    statusText: ok ? 'OK' : 'Internal Server Error',
    headers: new Headers(),
    redirected: false,
    type: 'default',
    url: '',
    clone: () => jsonResponse(data, ok),
    body: null,
    bodyUsed: false,
    arrayBuffer: async () => new ArrayBuffer(0),
    blob: async () => new Blob(),
    formData: async () => new FormData(),
    text: async () => JSON.stringify(data),
    json: async () => data,
    bytes: async () => new Uint8Array(),
  } as Response
}

describe('tagsApi', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists tags from the collection endpoint', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: 1, name: 'Horror' }]))

    const result = await tagsApi.listTags()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags')
    expect(result).toEqual([{ id: 1, name: 'Horror' }])
  })

  it('gets a tag by id', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 5, name: 'Physical' }))

    const result = await tagsApi.getTag(5)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/5')
    expect(result).toEqual({ id: 5, name: 'Physical' })
  })

  it('creates a tag and returns the created representation', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 9, name: 'New', scope: 'private' }))

    const result = await tagsApi.createTag({ name: 'New', scope: 'private' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New', scope: 'private' }),
    })
    expect(result).toEqual({ id: 9, name: 'New', scope: 'private' })
  })

  it('updates a tag with a PUT request', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 9, name: 'Renamed' }))

    const result = await tagsApi.updateTag(9, { name: 'Renamed' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/9', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Renamed' }),
    })
    expect(result).toEqual({ id: 9, name: 'Renamed' })
  })

  it('deletes a tag', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({}))

    await tagsApi.deleteTag(9)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/9', { method: 'DELETE' })
  })

  it('assigns a tag to a target', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 1, tag_id: 3 }))

    const result = await tagsApi.assignTag(3, { target_type: 'ContinuityPlan', target_id: 42 })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/3/assign/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_type: 'ContinuityPlan', target_id: 42 }),
    })
    expect(result).toEqual({ id: 1, tag_id: 3 })
  })

  it('unassigns a tag from a target', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({}))

    await tagsApi.unassignTag(3, { target_type: 'Issue', target_id: 7 })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/3/unassign/', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_type: 'Issue', target_id: 7 }),
    })
  })

  it('gets tag usage statistics', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ assignment_count: 4, filter_references: 1 }))

    const result = await tagsApi.getTagUsage(3)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/3/usage/')
    expect(result).toEqual({ assignment_count: 4, filter_references: 1 })
  })

  it('fetches effective tags for an issue', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ effective_tags: [] }))

    const result = await tagsApi.getEffectiveTags('Issue', 11)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/effective/issue/11/')
    expect(result).toEqual({ effective_tags: [] })
  })

  it('fetches effective tags for a thread', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ effective_tags: [] }))

    await tagsApi.getEffectiveTags('Thread', 12)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/effective/thread/12/')
  })

  it('fetches effective tags for a continuity plan via the plan URL segment', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ effective_tags: [] }))

    await tagsApi.getEffectiveTags('ContinuityPlan', 13)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/effective/plan/13/')
  })

  it('searches tags with query and limit', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: 1, name: 'Horror' }]))

    const result = await tagsApi.searchTags('hor', 5)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/search/?query=hor&limit=5')
    expect(result).toEqual([{ id: 1, name: 'Horror' }])
  })

  it('gets near matches for a candidate name', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse([{ tag: { id: 1 }, distance: 1 }]))

    const result = await tagsApi.getNearMatches('Horor')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/near-matches/?name=Horor&limit=8')
    expect(result).toEqual([{ tag: { id: 1 }, distance: 1 }])
  })

  it('performs bulk tag operations', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({}))

    await tagsApi.bulkTagOperations([
      { tag_id: 1, target_type: 'Issue', target_ids: [1, 2], action: 'add' },
      { tag_id: 2, target_type: 'Thread', target_ids: [3], action: 'remove' },
    ])

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/bulk/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operations: [
          { tag_id: 1, target_type: 'Issue', target_ids: [1, 2], action: 'add' },
          { tag_id: 2, target_type: 'Thread', target_ids: [3], action: 'remove' },
        ],
      }),
    })
  })

  it('checks name availability for a scope', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({ available: false, existing_tag: { id: 1 } }))

    const result = await tagsApi.checkNameAvailability('Horror', 'private')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags/check-name/?name=Horror&scope=private')
    expect(result).toEqual({ available: false, existing_tag: { id: 1 } })
  })

  it('throws a descriptive error when the API responds with a failure', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({}, false))

    await expect(tagsApi.listTags()).rejects.toThrow('Failed to list tags: Internal Server Error')
  })
})
