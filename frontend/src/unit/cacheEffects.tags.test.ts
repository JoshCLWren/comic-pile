import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import {
  applyCreatedTag,
  applyDeletedTag,
  applyUpdatedTag,
  invalidateAfterBulkTagOperation,
  invalidateAfterTagAssignment,
  invalidateAfterTagCreate,
  invalidateAfterTagDelete,
  invalidateAfterTagUpdate,
  optimisticallyAssignTag,
  optimisticallyUnassignTag,
  optimisticallyUpdateTag,
} from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import type { EffectiveTags, Tag } from '../types'

const tag: Tag = {
  id: 3,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'global',
  owner_user_id: null,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const inheritedTag: Tag = {
  id: 7,
  name: 'Physical',
  normalized_name: 'physical',
  scope: 'private',
  owner_user_id: 4,
  color: '#16A34A',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

/** Issue 11 holds `tag` directly and also inherits `inheritedTag` from its thread. */
function makeEffectiveTags(): EffectiveTags {
  return {
    target_type: 'Issue',
    target_id: 11,
    direct_tags: [tag],
    effective_tags: [
      {
        tag,
        direct: true,
        sources: [{ target_type: 'Issue', target_id: 11, display_name: 'B.P.R.D. #3' }],
      },
      {
        tag: inheritedTag,
        direct: false,
        sources: [{ target_type: 'Thread', target_id: 10, display_name: 'B.P.R.D.' }],
      },
    ],
  }
}

function makeClientWithEffectiveTags(): QueryClient {
  const client = new QueryClient()
  client.setQueryData(queryKeys.tags.effective('issue', 11), makeEffectiveTags())
  return client
}

describe('optimisticallyUpdateTag', () => {
  it('updates a cached tag detail and rolls back', () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)

    const rollback = optimisticallyUpdateTag(client, 3, (current) => ({
      ...current,
      name: 'Supernatural',
    }))

    expect(client.getQueryData<Tag>(queryKeys.tags.detail(3))?.name).toBe('Supernatural')

    rollback()

    expect(client.getQueryData<Tag>(queryKeys.tags.detail(3))).toEqual(tag)
  })

  it('removes the cached detail on rollback when it did not exist before', () => {
    const client = new QueryClient()

    const rollback = optimisticallyUpdateTag(client, 3, (current) => ({
      ...current,
      name: 'Supernatural',
    }))

    rollback()

    expect(client.getQueryData<Tag>(queryKeys.tags.detail(3))).toBeUndefined()
  })
})

describe('optimisticallyAssignTag', () => {
  it('adds a not-yet-effective tag as direct without disturbing existing tags', () => {
    const client = makeClientWithEffectiveTags()

    const rollback = optimisticallyAssignTag(client, inheritedTag, 'issue', 11, 'B.P.R.D. #3')

    const updated = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
    expect(updated?.effective_tags).toHaveLength(2)
    expect(updated?.direct_tags.map((entry) => entry.id)).toEqual([3, 7])
    expect(updated?.effective_tags[1]).toMatchObject({ direct: true })

    rollback()

    expect(client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))).toEqual(
      makeEffectiveTags(),
    )
  })

  it('marks an already-inherited tag direct and retains its inherited sources', () => {
    const client = makeClientWithEffectiveTags()

    optimisticallyAssignTag(client, inheritedTag, 'issue', 11, 'B.P.R.D. #3')

    const updated = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
    const entry = updated?.effective_tags.find((item) => item.tag.id === inheritedTag.id)

    expect(entry?.direct).toBe(true)
    expect(entry?.sources).toHaveLength(2)
  })

  it('does not duplicate a source the target already contributes', () => {
    const client = makeClientWithEffectiveTags()

    optimisticallyAssignTag(client, tag, 'issue', 11, 'B.P.R.D. #3')

    const updated = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
    const entry = updated?.effective_tags.find((item) => item.tag.id === tag.id)

    expect(entry?.sources).toHaveLength(1)
  })

  it('does not manufacture effective tags when nothing is cached', () => {
    const client = new QueryClient()

    const rollback = optimisticallyAssignTag(client, tag, 'issue', 11, 'B.P.R.D. #3')

    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toBeUndefined()

    rollback()

    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toBeUndefined()
  })
})

describe('optimisticallyUnassignTag', () => {
  it('drops a tag the target assigned directly when no other source contributes', () => {
    const client = makeClientWithEffectiveTags()

    const rollback = optimisticallyUnassignTag(client, 3, 'issue', 11)

    const updated = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
    expect(updated?.effective_tags.map((entry) => entry.tag.id)).toEqual([7])
    expect(updated?.direct_tags.map((entry) => entry.id)).toEqual([])

    rollback()

    expect(client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))).toEqual(
      makeEffectiveTags(),
    )
  })

  it('keeps the tag effective when another source still contributes it', () => {
    const client = new QueryClient()
    client.setQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11), {
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [tag],
      effective_tags: [
        {
          tag,
          direct: true,
          sources: [
            { target_type: 'Issue', target_id: 11, display_name: 'B.P.R.D. #3' },
            { target_type: 'ContinuityPlan', target_id: 42, display_name: 'Mignolaverse' },
          ],
        },
      ],
    })

    optimisticallyUnassignTag(client, 3, 'issue', 11)

    const updated = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
    const entry = updated?.effective_tags[0]

    expect(updated?.effective_tags).toHaveLength(1)
    expect(entry?.direct).toBe(false)
    expect(entry?.sources).toEqual([
      { target_type: 'ContinuityPlan', target_id: 42, display_name: 'Mignolaverse' },
    ])
  })

  it('leaves unrelated tags untouched', () => {
    const client = makeClientWithEffectiveTags()

    optimisticallyUnassignTag(client, 3, 'thread', 99)

    expect(client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))).toEqual(
      makeEffectiveTags(),
    )
  })

  it('leaves the cache alone when the target has no cached effective tags', () => {
    const client = new QueryClient()

    const rollback = optimisticallyUnassignTag(client, 3, 'issue', 11)

    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toBeUndefined()
    expect(() => rollback()).not.toThrow()
  })
})

describe('applyCreatedTag', () => {
  it('stores the created tag in the detail cache', async () => {
    const client = new QueryClient()

    await applyCreatedTag(client, tag)

    expect(client.getQueryData<Tag>(queryKeys.tags.detail(3))).toEqual(tag)
  })
})

describe('applyUpdatedTag', () => {
  it('replaces the cached tag detail', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)

    const renamed = { ...tag, name: 'Supernatural' }
    await applyUpdatedTag(client, renamed)

    expect(client.getQueryData<Tag>(queryKeys.tags.detail(3))).toEqual(renamed)
  })
})

describe('applyDeletedTag', () => {
  it('removes the tag from the detail cache', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)

    await applyDeletedTag(client, 3)

    expect(client.getQueryData<Tag>(queryKeys.tags.detail(3))).toBeUndefined()
  })
})

describe('tag invalidation helpers', () => {
  it('invalidates every cached tag query after a bulk operation', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.list(), [tag])
    client.setQueryData(queryKeys.tags.detail(3), tag)
    client.setQueryData(queryKeys.tags.effective('issue', 11), makeEffectiveTags())

    await invalidateAfterBulkTagOperation(client)

    expect(client.getQueryState(queryKeys.tags.list())?.isInvalidated).toBe(true)
    expect(client.getQueryState(queryKeys.tags.detail(3))?.isInvalidated).toBe(true)
    expect(client.getQueryState(queryKeys.tags.effective('issue', 11))?.isInvalidated).toBe(true)
  })

  it('invalidates effective tags for the changed issue target', async () => {
    const client = makeClientWithEffectiveTags()

    await invalidateAfterTagAssignment(client, 'issue', 11)

    expect(client.getQueryState(queryKeys.tags.effective('issue', 11))?.isInvalidated).toBe(true)
  })

  it('invalidates effective tags for a continuity plan target', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.effective('plan', 42), makeEffectiveTags())

    await invalidateAfterTagAssignment(client, 'plan', 42)

    expect(client.getQueryState(queryKeys.tags.effective('plan', 42))?.isInvalidated).toBe(true)
  })

  it('invalidates the tag list after creation', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.list(), [tag])

    await invalidateAfterTagCreate(client)

    expect(client.getQueryState(queryKeys.tags.list())?.isInvalidated).toBe(true)
  })

  it('invalidates the tag detail and list after an update', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)
    client.setQueryData(queryKeys.tags.list(), [tag])

    await invalidateAfterTagUpdate(client, tag)

    expect(client.getQueryState(queryKeys.tags.detail(3))?.isInvalidated).toBe(true)
    expect(client.getQueryState(queryKeys.tags.list())?.isInvalidated).toBe(true)
  })

  it('removes the tag detail and invalidates the list after deletion', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)
    client.setQueryData(queryKeys.tags.list(), [tag])

    await invalidateAfterTagDelete(client, 3)

    expect(client.getQueryData(queryKeys.tags.detail(3))).toBeUndefined()
    expect(client.getQueryState(queryKeys.tags.list())?.isInvalidated).toBe(true)
  })
})