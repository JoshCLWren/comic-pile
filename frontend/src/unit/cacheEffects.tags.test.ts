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
import type { EffectiveTag, Tag } from '../types'

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

const effectiveTags: EffectiveTag[] = [
  {
    tag,
    assignments: [
      {
        id: 1,
        tag_id: 3,
        target_type: 'Issue',
        target_id: 11,
        created_at: '2026-01-01T00:00:00Z',
      },
    ],
    inheritance_sources: [],
  },
]

function makeClientWithEffectiveTags(): QueryClient {
  const client = new QueryClient()
  client.setQueryData(queryKeys.tags.effective('issue', 11), effectiveTags)
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

    expect(client.getQueryData(queryKeys.tags.detail(3))).toBeUndefined()
  })
})

describe('optimisticallyAssignTag', () => {
  it('adds an assignment with the ContinuityPlan target type for plan targets', () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.effective('plan', 42), effectiveTags)

    const rollback = optimisticallyAssignTag(client, tag, 'plan', 42)

    const updated = client.getQueryData<EffectiveTag[]>(queryKeys.tags.effective('plan', 42))
    expect(updated?.[0].assignments).toHaveLength(2)
    expect(updated?.[0].assignments[1]).toMatchObject({
      tag_id: 3,
      target_type: 'ContinuityPlan',
      target_id: 42,
    })

    rollback()

    expect(client.getQueryData<EffectiveTag[]>(queryKeys.tags.effective('plan', 42))).toEqual(
      effectiveTags,
    )
  })

  it('does not manufacture effective tags when nothing is cached', () => {
    const client = new QueryClient()

    const rollback = optimisticallyAssignTag(client, tag, 'issue', 11)

    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toBeUndefined()

    rollback()

    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toBeUndefined()
  })
})

describe('optimisticallyUnassignTag', () => {
  it('removes only the matching assignment', () => {
    const client = makeClientWithEffectiveTags()

    const rollback = optimisticallyUnassignTag(client, 3, 'issue', 11)

    const updated = client.getQueryData<EffectiveTag[]>(queryKeys.tags.effective('issue', 11))
    expect(updated?.[0].assignments).toHaveLength(0)

    rollback()

    expect(client.getQueryData<EffectiveTag[]>(queryKeys.tags.effective('issue', 11))).toEqual(
      effectiveTags,
    )
  })

  it('keeps assignments for other targets', () => {
    const client = makeClientWithEffectiveTags()

    optimisticallyUnassignTag(client, 3, 'thread', 99)

    expect(
      client.getQueryData<EffectiveTag[]>(queryKeys.tags.effective('issue', 11)),
    ).toEqual(effectiveTags)
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

    expect(client.getQueryData(queryKeys.tags.detail(3))).toBeUndefined()
  })
})

describe('tag invalidation helpers', () => {
  it('invalidates tag queries after a bulk operation', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.all, [tag])

    await invalidateAfterBulkTagOperation(client)

    expect(client.getQueryState(queryKeys.tags.all)?.isInvalidated).toBe(true)
  })

  it('invalidates effective tags for the changed target', async () => {
    const client = makeClientWithEffectiveTags()

    await invalidateAfterTagAssignment(client, 'issue', 11)

    expect(client.getQueryState(queryKeys.tags.effective('issue', 11))?.isInvalidated).toBe(true)
  })

  it('invalidates effective tags for a continuity plan target', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.effective('plan', 42), effectiveTags)

    await invalidateAfterTagAssignment(client, 'plan', 42)

    expect(client.getQueryState(queryKeys.tags.effective('plan', 42))?.isInvalidated).toBe(true)
  })

  it('invalidates tag queries after creation', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.list(), [tag])

    await invalidateAfterTagCreate(client)

    expect(client.getQueryState(queryKeys.tags.list())?.isInvalidated).toBe(true)
  })

  it('invalidates the tag detail after update', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)

    await invalidateAfterTagUpdate(client, tag)

    expect(client.getQueryState(queryKeys.tags.detail(3))?.isInvalidated).toBe(true)
  })

  it('removes the tag detail after deletion', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.tags.detail(3), tag)

    await invalidateAfterTagDelete(client, 3)

    expect(client.getQueryState(queryKeys.tags.detail(3))?.isInvalidated).toBe(true)
  })
})
