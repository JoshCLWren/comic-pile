import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EffectiveTags, Tag } from '../types'
import { queryKeys } from '../query/queryKeys'

const { getEffectiveTagsMock, assignTagMock, unassignTagMock, testQueryClientRef } = vi.hoisted(
  () => ({
    getEffectiveTagsMock: vi.fn(),
    assignTagMock: vi.fn(),
    unassignTagMock: vi.fn(),
    testQueryClientRef: { current: null as QueryClient | null },
  }),
)

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: vi.fn(),
    getTag: vi.fn(),
    createTag: vi.fn(),
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    assignTag: assignTagMock,
    unassignTag: unassignTagMock,
    getTagUsage: vi.fn(),
    getEffectiveTags: getEffectiveTagsMock,
    bulkTagOperations: vi.fn(),
  },
}))

vi.mock('../query/queryClient', () => ({
  get queryClient() {
    return testQueryClientRef.current
  },
}))

import { useAssignTag, useEffectiveTags, useUnassignTag } from '../hooks/useTags'

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

const effectiveTags: EffectiveTags = {
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

function makeWrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

beforeEach(() => {
  testQueryClientRef.current = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  getEffectiveTagsMock.mockReset().mockResolvedValue(effectiveTags)
  assignTagMock.mockReset().mockResolvedValue({ id: 1, tag_id: 3 })
  unassignTagMock.mockReset().mockResolvedValue({ id: 1, tag_id: 3 })
})

/** The active test client; `beforeEach` always installs one. */
function currentClient(): QueryClient {
  const client = testQueryClientRef.current
  if (!client) {
    throw new Error('No test QueryClient was installed')
  }
  return client
}

describe('useEffectiveTags', () => {
  it('fetches effective tags for an issue target', async () => {
    const client = currentClient()
    const { result } = renderHook(() => useEffectiveTags('issue', 11), {
      wrapper: makeWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(getEffectiveTagsMock).toHaveBeenCalledWith('Issue', 11)
    expect(result.current.data).toEqual(effectiveTags)
    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toEqual(effectiveTags)
  })

  it('fetches effective tags for a plan target using the ContinuityPlan type', async () => {
    const client = currentClient()
    const { result } = renderHook(() => useEffectiveTags('plan', 42), {
      wrapper: makeWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(getEffectiveTagsMock).toHaveBeenCalledWith('ContinuityPlan', 42)
  })

  it('does not fetch when the id is missing', async () => {
    const client = currentClient()
    const { result } = renderHook(() => useEffectiveTags('issue', 0), {
      wrapper: makeWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(getEffectiveTagsMock).not.toHaveBeenCalled()
  })
})

describe('useAssignTag', () => {
  it('assigns a tag and invalidates the effective tags for the target', async () => {
    const client = currentClient()
    client.setQueryData(queryKeys.tags.effective('plan', 42), {
      ...effectiveTags,
      target_type: 'ContinuityPlan',
      target_id: 42,
    })

    const { result } = renderHook(() => useAssignTag(), { wrapper: makeWrapper(client) })

    result.current.mutate({
      tag,
      targetLabel: 'Mignolaverse',
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
      expect(
        client.getQueryState(queryKeys.tags.effective('plan', 42))?.isInvalidated,
      ).toBe(true)
    })
  })

  it('optimistically records the assignment before the mutation resolves', async () => {
    const client = currentClient()
    client.setQueryData(queryKeys.tags.effective('issue', 11), effectiveTags)

    let resolveAssign: (value: unknown) => void = () => {}
    assignTagMock.mockReturnValue(
      new Promise((resolve) => {
        resolveAssign = resolve
      }),
    )

    const { result } = renderHook(() => useAssignTag(), { wrapper: makeWrapper(client) })

    result.current.mutate({
      tag: inheritedTag,
      targetLabel: 'B.P.R.D. #3',
      request: { target_type: 'Issue', target_id: 11 },
    })

    await waitFor(() => {
      const cached = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
      const entry = cached?.effective_tags.find((item) => item.tag.id === inheritedTag.id)
      expect(entry?.direct).toBe(true)
      expect(entry?.sources).toContainEqual({
        target_type: 'Issue',
        target_id: 11,
        display_name: 'B.P.R.D. #3',
      })
    })

    resolveAssign({ id: 2, tag_id: 7 })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('restores the prior cache when the assignment fails', async () => {
    const client = currentClient()
    client.setQueryData(queryKeys.tags.effective('issue', 11), effectiveTags)
    assignTagMock.mockRejectedValue(new Error('nope'))

    const { result } = renderHook(() => useAssignTag(), { wrapper: makeWrapper(client) })

    result.current.mutate({
      tag: inheritedTag,
      targetLabel: 'B.P.R.D. #3',
      request: { target_type: 'Issue', target_id: 11 },
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })

    expect(client.getQueryData(queryKeys.tags.effective('issue', 11))).toEqual(effectiveTags)
  })
})

describe('useUnassignTag', () => {
  it('unassigns a tag and invalidates the effective tags for the target', async () => {
    const client = currentClient()
    client.setQueryData(queryKeys.tags.effective('issue', 11), effectiveTags)

    const { result } = renderHook(() => useUnassignTag(), { wrapper: makeWrapper(client) })

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
      expect(
        client.getQueryState(queryKeys.tags.effective('issue', 11))?.isInvalidated,
      ).toBe(true)
    })
  })

  it('optimistically removes only this target source before the mutation resolves', async () => {
    const client = currentClient()
    client.setQueryData(queryKeys.tags.effective('issue', 11), effectiveTags)

    let resolveUnassign: (value: unknown) => void = () => {}
    unassignTagMock.mockReturnValue(
      new Promise((resolve) => {
        resolveUnassign = resolve
      }),
    )

    const { result } = renderHook(() => useUnassignTag(), { wrapper: makeWrapper(client) })

    result.current.mutate({
      tagId: 3,
      request: { target_type: 'Issue', target_id: 11 },
    })

    await waitFor(() => {
      const cached = client.getQueryData<EffectiveTags>(queryKeys.tags.effective('issue', 11))
      expect(cached?.effective_tags.map((entry) => entry.tag.id)).toEqual([7])
      expect(cached?.direct_tags).toEqual([])
    })

    resolveUnassign({ id: 1, tag_id: 3 })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })
})