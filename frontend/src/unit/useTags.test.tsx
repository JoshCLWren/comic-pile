import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getEffectiveTagsMock, getTagMock, assignTagMock, unassignTagMock, testQueryClient } = vi.hoisted(() => {
  const { QueryClient } = require('@tanstack/react-query')
  return {
    getEffectiveTagsMock: vi.fn(),
    getTagMock: vi.fn(),
    assignTagMock: vi.fn(),
    unassignTagMock: vi.fn(),
    testQueryClient: new QueryClient(),
  }
})

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: vi.fn(),
    getTag: getTagMock,
    createTag: vi.fn(),
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    assignTag: assignTagMock,
    unassignTag: unassignTagMock,
    getTagUsage: vi.fn(),
    getEffectiveTags: getEffectiveTagsMock,
    searchTags: vi.fn(),
    getNearMatches: vi.fn(),
    bulkTagOperations: vi.fn(),
    checkNameAvailability: vi.fn(),
  },
}))

// Mock the singleton queryClient so hooks use the test client
vi.mock('../query/queryClient', () => ({
  queryClient: testQueryClient,
}))

import { QueryClientProvider } from '@tanstack/react-query'
import { useAssignTag, useEffectiveTags, useUnassignTag } from '../hooks/useTags'
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
    assignments: [],
    inheritance_sources: [{ id: 10, type: 'Thread', name: 'B.P.R.D.', direct: true }],
  },
]

function makeWrapper() {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={testQueryClient}>{children}</QueryClientProvider>
  )
}

beforeEach(() => {
  testQueryClient.clear()
  getEffectiveTagsMock.mockReset().mockResolvedValue(effectiveTags)
  getTagMock.mockReset().mockResolvedValue(tag)
  assignTagMock.mockReset().mockResolvedValue({ id: 1, tag_id: 3 })
  unassignTagMock.mockReset().mockResolvedValue(undefined)
})

describe('useEffectiveTags', () => {
  it('fetches effective tags for an issue target', async () => {
    const { result } = renderHook(() => useEffectiveTags('issue', 11), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(getEffectiveTagsMock).toHaveBeenCalledWith('Issue', 11)
    expect(result.current.data).toEqual(effectiveTags)
    expect(testQueryClient.getQueryData(queryKeys.tags.effective('issue', 11))).toEqual(effectiveTags)
  })

  it('fetches effective tags for a plan target using the ContinuityPlan type', async () => {
    const { result } = renderHook(() => useEffectiveTags('plan', 42), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(getEffectiveTagsMock).toHaveBeenCalledWith('ContinuityPlan', 42)
  })

  it('does not fetch when the id is missing', async () => {
    const { result } = renderHook(() => useEffectiveTags('issue', 0), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(getEffectiveTagsMock).not.toHaveBeenCalled()
  })
})

describe('useAssignTag', () => {
  it('assigns a tag and invalidates the effective tags for the target', async () => {
    testQueryClient.setQueryData(queryKeys.tags.effective('plan', 42), effectiveTags)

    const { result } = renderHook(() => useAssignTag(), { wrapper: makeWrapper() })

    result.current.mutate({
      tagId: 3,
      request: { target_type: 'ContinuityPlan', target_id: 42 },
    })

    await waitFor(() => {
      expect(assignTagMock).toHaveBeenCalledWith(3, {
        target_type: 'ContinuityPlan',
        target_id: 42,
      })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    await waitFor(() => {
      expect(testQueryClient.getQueryState(queryKeys.tags.effective('plan', 42))?.isInvalidated).toBe(true)
    })
  })

  it('optimistically adds the assignment before the mutation resolves', async () => {
    testQueryClient.setQueryData(queryKeys.tags.effective('issue', 11), effectiveTags)

    let resolveAssign: (value: unknown) => void = () => {}
    assignTagMock.mockReturnValue(
      new Promise((resolve) => {
        resolveAssign = resolve
      }),
    )

    const { result } = renderHook(() => useAssignTag(), { wrapper: makeWrapper() })

    result.current.mutate({
      tagId: 3,
      request: { target_type: 'Issue', target_id: 11 },
    })

    await waitFor(() => {
      const cached = testQueryClient.getQueryData<EffectiveTag[]>(queryKeys.tags.effective('issue', 11))
      expect(cached?.[0].assignments).toHaveLength(1)
      expect(cached?.[0].assignments[0]).toMatchObject({
        tag_id: 3,
        target_type: 'Issue',
        target_id: 11,
      })
    })

    resolveAssign({ id: 2, tag_id: 3 })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })
})

describe('useUnassignTag', () => {
  const assignedEffectiveTags: EffectiveTag[] = [
    {
      tag,
      assignments: [
        { id: 1, tag_id: 3, target_type: 'Issue', target_id: 11, created_at: '2026-01-01T00:00:00Z' },
      ],
      inheritance_sources: [],
    },
  ]

  it('unassigns a tag and invalidates the effective tags for the target', async () => {
    testQueryClient.setQueryData(queryKeys.tags.effective('issue', 11), assignedEffectiveTags)

    const { result } = renderHook(() => useUnassignTag(), { wrapper: makeWrapper() })

    result.current.mutate({
      tagId: 3,
      request: { target_type: 'Issue', target_id: 11 },
    })

    await waitFor(() => {
      expect(unassignTagMock).toHaveBeenCalledWith(3, {
        target_type: 'Issue',
        target_id: 11,
      })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    await waitFor(() => {
      expect(testQueryClient.getQueryState(queryKeys.tags.effective('issue', 11))?.isInvalidated).toBe(true)
    })
  })
})
