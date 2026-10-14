/**
 * Account-wide Roll tag exclusions (issue #3033).
 *
 * Exclusions are persistent eligibility constraints the reader manages directly
 * from Roll. These cases pin the three surfaces that make that work: the API
 * routes, the TanStack hooks that own the writes, and the two Roll affordances
 * (the "Excluded from Roll" manager and the per-chip Exclude action).
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createRollTagExclusionApi } from '../services/api-roll-exclusions'
import type { Tag } from '../services/api-tags'
import {
  useAddTagExclusion,
  useExcludeTagAndReroll,
  useRemoveTagExclusion,
  useTagExclusions,
} from '../hooks/useRollTagExclusions'
import { TagExclusionManager } from '../pages/RollPage/components/TagExclusionManager'
import { TagChips } from '../components/Tags/TagChips'
import type { EffectiveTagsResponse } from '../services/api-tags'
import { createHttpClientStub } from './httpClientStub'

const api = vi.hoisted(() => ({
  rollTagExclusionApi: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    excludeAndReroll: vi.fn(),
  },
}))

vi.mock('../services/api-roll-exclusions', async (importOriginal) => {
  // SAFETY: the factory and payload types are real; only the bound singleton is doubled
  const actual = await importOriginal<typeof import('../services/api-roll-exclusions')>()
  return { ...actual, rollTagExclusionApi: api.rollTagExclusionApi }
})

function tag(id: number, name: string): Tag {
  return {
    id,
    name,
    normalized_name: name.toLowerCase(),
    scope: 'global',
    owner_user_id: null,
    color: '#DC2626',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
  }
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return Wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('rollTagExclusionApi routes (issue #3033)', () => {
  it('addresses the versioned exclusion routes', async () => {
    const client = createHttpClientStub()
    const service = createRollTagExclusionApi(client)
    client.get.mockResolvedValue({ excluded_tags: [] })
    client.post.mockResolvedValue(tag(1, 'Prose'))
    client.delete.mockResolvedValue(tag(1, 'Prose'))

    await service.list()
    await service.add(1)
    await service.remove(1)
    await service.excludeAndReroll(1)

    expect(client.get).toHaveBeenCalledWith('/v1/roll/tag-exclusions/')
    expect(client.post).toHaveBeenNthCalledWith(1, '/v1/roll/tag-exclusions/', { tag_id: 1 })
    expect(client.delete).toHaveBeenCalledWith('/v1/roll/tag-exclusions/1/')
    expect(client.post).toHaveBeenNthCalledWith(2, '/v1/roll/tag-exclusions/1/exclude-and-reroll/')
  })
})

describe('roll tag-exclusion hooks (issue #3033)', () => {
  it('reads the active exclusions', async () => {
    api.rollTagExclusionApi.list.mockResolvedValue({ excluded_tags: [tag(4, 'Prose')] })

    const { result } = renderHook(() => useTagExclusions(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.excluded_tags).toHaveLength(1)
  })

  it('persists and removes an exclusion', async () => {
    api.rollTagExclusionApi.add.mockResolvedValue(tag(4, 'Prose'))
    api.rollTagExclusionApi.remove.mockResolvedValue(tag(4, 'Prose'))
    const wrapper = createWrapper()

    const { result: add } = renderHook(() => useAddTagExclusion(), { wrapper })
    await add.current.mutateAsync(4)
    await waitFor(() => expect(add.current.isSuccess).toBe(true))
    expect(api.rollTagExclusionApi.add).toHaveBeenCalledWith(4)

    const { result: remove } = renderHook(() => useRemoveTagExclusion(), { wrapper })
    await remove.current.mutateAsync(4)
    await waitFor(() => expect(remove.current.isSuccess).toBe(true))
    expect(api.rollTagExclusionApi.remove).toHaveBeenCalledWith(4)
  })

  it('maps the exclude-and-reroll outcome onto the camelCase hook contract', async () => {
    api.rollTagExclusionApi.excludeAndReroll.mockResolvedValue({
      excluded_tag: tag(4, 'Prose'),
      pending_invalidated: true,
      roll: { id: 9, title: 'Saga' },
    })

    const { result } = renderHook(() => useExcludeTagAndReroll(), { wrapper: createWrapper() })
    const outcome = await result.current.mutateAsync(4)

    expect(outcome).toEqual({
      excludedTag: tag(4, 'Prose'),
      pendingInvalidated: true,
      roll: { id: 9, title: 'Saga' },
    })
  })

  it('surfaces an exclude-and-reroll failure so the caller can report it', async () => {
    api.rollTagExclusionApi.excludeAndReroll.mockRejectedValue(new Error('no eligible candidates'))

    const { result } = renderHook(() => useExcludeTagAndReroll(), { wrapper: createWrapper() })

    await expect(result.current.mutateAsync(4)).rejects.toThrow('no eligible candidates')
  })
})

describe('TagExclusionManager (issue #3033)', () => {
  it('renders nothing while no exclusion is active', () => {
    const { container } = render(
      <TagExclusionManager excludedTags={[]} onRemove={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('names every active exclusion and removes the chosen one', async () => {
    const onRemove = vi.fn()
    render(
      <TagExclusionManager
        excludedTags={[tag(1, 'Prose'), tag(2, 'Anthology')]}
        onRemove={onRemove}
      />,
    )

    expect(screen.getByText('Excluded from Roll')).toBeInTheDocument()
    expect(screen.getByText('Prose')).toBeInTheDocument()
    expect(screen.getByText('Anthology')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove exclusion for tag Anthology' }))
    expect(onRemove).toHaveBeenCalledWith(2)
  })

  it('disables removal while one is already in flight', () => {
    render(
      <TagExclusionManager
        excludedTags={[tag(1, 'Prose')]}
        onRemove={vi.fn()}
        isPending
      />,
    )
    expect(screen.getByRole('button', { name: 'Remove exclusion for tag Prose' })).toBeDisabled()
  })

  it('reports a failed load instead of claiming there are no exclusions', async () => {
    const onRetry = vi.fn()
    render(
      <TagExclusionManager
        excludedTags={[tag(1, 'Prose')]}
        onRemove={vi.fn()}
        loadError={new Error('offline')}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByText(/Exclusions could not be loaded/)).toBeInTheDocument()
    expect(screen.queryByText('Prose')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})

describe('tag chip exclude affordance (issue #3033)', () => {
  function chipData(): EffectiveTagsResponse {
    const prose = tag(1, 'Prose')
    const inherited = tag(2, 'Anthology')
    return {
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [prose],
      effective_tags: [
        { tag: prose, direct: true, sources: [] },
        {
          tag: inherited,
          direct: false,
          sources: [{ target_type: 'Thread', target_id: 3, display_name: 'B.P.R.D.' }],
        },
      ],
    }
  }

  function renderChips(onExcludeTag?: (tag: Tag) => void, excludeIsPending = false) {
    return render(
      <MemoryRouter>
        <TagChips data={chipData()} onExcludeTag={onExcludeTag} excludeIsPending={excludeIsPending} />
      </MemoryRouter>,
    )
  }

  it('offers Exclude on every chip only where Roll supplies a handler', () => {
    renderChips()
    expect(screen.queryAllByRole('button', { name: /Exclude tag .* from Roll/ })).toHaveLength(0)

    renderChips(vi.fn())
    expect(screen.getAllByRole('button', { name: /Exclude tag .* from Roll/ })).toHaveLength(2)
  })

  it('excludes the tag behind the chip the reader pressed', async () => {
    const onExcludeTag = vi.fn()
    renderChips(onExcludeTag)

    await userEvent.click(screen.getByRole('button', { name: 'Exclude tag Anthology from Roll' }))
    expect(onExcludeTag).toHaveBeenCalledTimes(1)
    expect(onExcludeTag.mock.calls[0][0]).toMatchObject({ id: 2, name: 'Anthology' })
  })

  it('blocks a second exclusion while one is in flight', () => {
    renderChips(vi.fn(), true)
    for (const button of screen.getAllByRole('button', { name: /Exclude tag .* from Roll/ })) {
      expect(button).toBeDisabled()
    }
  })
})