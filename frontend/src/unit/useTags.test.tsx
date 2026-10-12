import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  useAssignTag,
  useBulkAssignTag,
  useBulkUnassignTag,
  useCreateTag,
  useDeleteTag,
  useEffectiveTags,
  useTag,
  useTags,
  useTagUsage,
  useThreadIssuesEffectiveTags,
  useUnassignTag,
  useUpdateTag,
} from '../hooks/useTags'
import { tagsApi } from '../services/api-tags'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    usage: vi.fn(),
    assign: vi.fn(),
    unassign: vi.fn(),
    bulkAssign: vi.fn(),
    bulkUnassign: vi.fn(),
    effectiveForIssue: vi.fn(),
    effectiveForThread: vi.fn(),
    effectiveForPlan: vi.fn(),
    threadIssuesEffective: vi.fn(),
  },
}))

const mockedTagsApi = vi.mocked(tagsApi)

function tag(id: number, scope: 'global' | 'private' = 'private') {
  return {
    id,
    name: `Tag ${id}`,
    normalized_name: `tag ${id}`,
    scope,
    owner_user_id: 1,
    color: '#DC2626',
    created_at: '',
    updated_at: '',
  }
}

function assignment(tagId: number) {
  return {
    id: 1,
    tag_id: tagId,
    target_type: 'Issue' as const,
    target_id: 2,
    created_at: '',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useTags', () => {
  it('queries the canonical list key and passes the raw filter through', async () => {
    mockedTagsApi.list.mockResolvedValue({ tags: [tag(1)] })

    const { result } = renderHook(() => useTags(' physical '))
    await waitFor(() => expect(result.current.data?.tags).toHaveLength(1))

    expect(mockedTagsApi.list).toHaveBeenCalledWith(' physical ')
    expect(result.current.data).toEqual({ tags: [tag(1)] })
  })
})

describe('useTag', () => {
  it('stays disabled without an id', () => {
    const { result } = renderHook(() => useTag(null))

    expect(result.current.fetchStatus).toBe('idle')
    expect(mockedTagsApi.get).not.toHaveBeenCalled()
  })

  it('loads one tag by id', async () => {
    mockedTagsApi.get.mockResolvedValue(tag(4))

    const { result } = renderHook(() => useTag(4))
    await waitFor(() => expect(result.current.data?.id).toBe(4))
    expect(mockedTagsApi.get).toHaveBeenCalledWith(4)
  })
})

describe('useEffectiveTags', () => {
  it.each([
    ['Issue' as const, 'effectiveForIssue' as const],
    ['Thread' as const, 'effectiveForThread' as const],
    ['ContinuityPlan' as const, 'effectiveForPlan' as const],
  ])('routes %s targets to the matching effective endpoint', async (targetType, method) => {
    mockedTagsApi[method].mockResolvedValue({
      target_type: targetType,
      target_id: 5,
      direct_tags: [],
      effective_tags: [],
    })

    const { result } = renderHook(() => useEffectiveTags(targetType, 5))
    await waitFor(() => expect(result.current.data?.target_id).toBe(5))
    expect(mockedTagsApi[method]).toHaveBeenCalledWith(5)
  })

  it('stays disabled without both a target type and id', () => {
    const { result } = renderHook(() => useEffectiveTags(null, 5))
    expect(result.current.fetchStatus).toBe('idle')
    expect(mockedTagsApi.effectiveForIssue).not.toHaveBeenCalled()
  })

  it('refetches after a retry request', async () => {
    mockedTagsApi.effectiveForIssue.mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() => useEffectiveTags('Issue', 11))

    await waitFor(() => expect(result.current.isError).toBe(true))

    mockedTagsApi.effectiveForIssue.mockResolvedValue({
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [],
      effective_tags: [],
    })
    await act(async () => {
      await result.current.refetch()
    })
    await waitFor(() => expect(result.current.isError).toBe(false))
    expect(result.current.data?.target_id).toBe(11)
  })
})

describe('useThreadIssuesEffectiveTags (issue #3422)', () => {
  it('loads bulk effective tags under the canonical thread-issues key', async () => {
    mockedTagsApi.threadIssuesEffective.mockResolvedValue({ thread_id: 4, issues: [] })

    const { result } = renderHook(() => useThreadIssuesEffectiveTags(4))
    await waitFor(() => expect(result.current.data?.thread_id).toBe(4))

    expect(mockedTagsApi.threadIssuesEffective).toHaveBeenCalledWith(4)
    expect(queryClient.getQueryData(queryKeys.tags.effectiveForThreadIssues(4))).toEqual({
      thread_id: 4,
      issues: [],
    })
  })

  it('stays disabled without a thread id or when gated off', () => {
    const { result: withoutId } = renderHook(() => useThreadIssuesEffectiveTags(null))
    expect(withoutId.current.fetchStatus).toBe('idle')

    const { result: gated } = renderHook(() => useThreadIssuesEffectiveTags(4, false))
    expect(gated.current.fetchStatus).toBe('idle')
    expect(mockedTagsApi.threadIssuesEffective).not.toHaveBeenCalled()
  })
})

describe('useTagUsage', () => {
  it('stays disabled without an id', () => {
    const { result } = renderHook(() => useTagUsage(null))
    expect(result.current.fetchStatus).toBe('idle')
    expect(mockedTagsApi.usage).not.toHaveBeenCalled()
  })

  it('loads usage counts for the delete confirmation', async () => {
    mockedTagsApi.usage.mockResolvedValue({
      tag_id: 2,
      total_assignments: 3,
      assignments_by_target_type: { Issue: 3 },
      references_removed_by_consumers: {},
    })

    const { result } = renderHook(() => useTagUsage(2))
    await waitFor(() => expect(result.current.data?.total_assignments).toBe(3))
    expect(mockedTagsApi.usage).toHaveBeenCalledWith(2)
  })
})

describe('tag mutations', () => {
  it('creates a tag and invalidates every tag cache', async () => {
    mockedTagsApi.create.mockResolvedValue({
      tag: tag(6),
      redirected_to_global: false,
      near_matches: [],
    })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useCreateTag())
    await act(async () => {
      await result.current.mutateAsync({ name: 'Tag 6' })
    })

    expect(mockedTagsApi.create).toHaveBeenCalledWith({ name: 'Tag 6' })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tags.all })
  })

  it('renames a tag', async () => {
    mockedTagsApi.update.mockResolvedValue(tag(6))
    const { result } = renderHook(() => useUpdateTag())
    await act(async () => {
      await result.current.mutateAsync({ id: 6, data: { name: 'Renamed' } })
    })
    expect(mockedTagsApi.update).toHaveBeenCalledWith(6, { name: 'Renamed' })
  })

  it('deletes a tag', async () => {
    mockedTagsApi.delete.mockResolvedValue({
      tag_id: 6,
      assignments_removed: 1,
      references_removed_by_consumers: {},
    })
    const { result } = renderHook(() => useDeleteTag())
    await act(async () => {
      await result.current.mutateAsync(6)
    })
    expect(mockedTagsApi.delete).toHaveBeenCalledWith(6)
  })

  it('assigns and unassigns a single tag on a target', async () => {
    mockedTagsApi.assign.mockResolvedValue(assignment(7))
    mockedTagsApi.unassign.mockResolvedValue(assignment(7))

    const { result: assign } = renderHook(() => useAssignTag())
    await act(async () => {
      await assign.current.mutateAsync({ id: 7, data: { target_type: 'Issue', target_id: 2 } })
    })
    expect(mockedTagsApi.assign).toHaveBeenCalledWith(7, {
      target_type: 'Issue',
      target_id: 2,
    })

    const { result: unassign } = renderHook(() => useUnassignTag())
    await act(async () => {
      await unassign.current.mutateAsync({ id: 7, data: { target_type: 'Issue', target_id: 2 } })
    })
    expect(mockedTagsApi.unassign).toHaveBeenCalledWith(7, {
      target_type: 'Issue',
      target_id: 2,
    })
  })

  it('bulk assigns and bulk unassigns across many targets', async () => {
    mockedTagsApi.bulkAssign.mockResolvedValue({
      tag_id: 8,
      target_type: 'Issue',
      requested_ids: [1, 2],
      affected_ids: [1],
      already_ids: [2],
    })
    mockedTagsApi.bulkUnassign.mockResolvedValue({
      tag_id: 8,
      target_type: 'Issue',
      requested_ids: [1, 2],
      affected_ids: [1],
      already_ids: [2],
    })

    const { result: bulkAssign } = renderHook(() => useBulkAssignTag())
    await act(async () => {
      await bulkAssign.current.mutateAsync({
        id: 8,
        data: { target_type: 'Issue', target_ids: [1, 2] },
      })
    })
    expect(mockedTagsApi.bulkAssign).toHaveBeenCalledWith(8, {
      target_type: 'Issue',
      target_ids: [1, 2],
    })

    const { result: bulkUnassign } = renderHook(() => useBulkUnassignTag())
    await act(async () => {
      await bulkUnassign.current.mutateAsync({
        id: 8,
        data: { target_type: 'Issue', target_ids: [1, 2] },
      })
    })
    expect(mockedTagsApi.bulkUnassign).toHaveBeenCalledWith(8, {
      target_type: 'Issue',
      target_ids: [1, 2],
    })
  })

  it('surfaces mutation failures instead of resolving them silently', async () => {
    mockedTagsApi.assign.mockRejectedValueOnce(new Error('only admins can do that'))
    const { result } = renderHook(() => useAssignTag())

    await expect(
      act(async () =>
        result.current.mutateAsync({ id: 9, data: { target_type: 'Issue', target_id: 3 } }),
      ),
    ).rejects.toThrow('only admins can do that')
  })
})