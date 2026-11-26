import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { createToastSpy } from './toastSpy'
import { ToastContextSpy } from './toastTestHarness'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { ComicIdentity } from '../pages/RollPage/components/ComicIdentity'

const toast = createToastSpy()

function ToastWrapper({ children }: { children: ReactNode }) {
  return <ToastContextSpy value={toast}>{children}</ToastContextSpy>
}

function renderWithToast(ui: ReactElement) {
  return render(ui, { wrapper: ToastWrapper })
}

vi.mock('../services/api-comicvine', async () => {
  const actual = await vi.importActual<typeof import('../services/api-comicvine')>('../services/api-comicvine')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn(), importIssue: vi.fn(), refreshMetadata: vi.fn() } }
})

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: {
    list: vi.fn().mockResolvedValue({ reading_orders: [] }),
  },
}))

const getIntelligence = vi.mocked(comicVineApi.getIssueIntelligence)
const refreshMetadata = vi.mocked(comicVineApi.refreshMetadata)

function intelligence(overrides: Partial<ComicVineIssueIntelligence> = {}) {
  return {
    comicvine_issue_id: 'A',
    comicvine_url: null,
    series_name: 'Test Series',
    series_id: 1,
    issue_number: '1',
    name: 'Test Issue',
    description: null,
    image_url: null,
    cover_date: null,
    store_date: null,
    creators: [],
    story_arcs: [],
    ...overrides,
  }
}

describe('ComicIdentity remap races (issue #5841)', () => {
  beforeEach(() => {
    queryClient.clear()
    getIntelligence.mockReset()
    refreshMetadata.mockReset()
  })

  it('a late hydration for identity A cannot overwrite remapped identity B', async () => {
    let resolveA: ((value: unknown) => void) | undefined
    const pendingA = new Promise((resolve) => {
      resolveA = resolve
    })
    getIntelligence
      .mockResolvedValueOnce(intelligence({
        comicvine_issue_id: 'A',
        metadata_status: 'not_deep_fetched',
      }))
      .mockResolvedValue(intelligence({
        comicvine_issue_id: 'B',
        metadata_status: 'complete',
        creators: [{ name: 'Writer B', roles: ['penciler'] }],
      }))
    refreshMetadata.mockImplementationOnce(() => pendingA).mockResolvedValue({
      issue_id: 1,
      refreshed: true,
      comicvine_issue_id: 'B',
      outcome: 'complete',
    })

    const { rerender } = renderWithToast(<ComicIdentity issueId={1} />)
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))

    // Remapping the same owned issue replaces the confirmed identity. The
    // canonical cache is cleared by the mapping hook before this projection.
    await act(async () => {
      queryClient.setQueryData(
        queryKeys.comicVine.issueIntelligence(1),
        intelligence({
          comicvine_issue_id: 'B',
          metadata_status: 'complete',
          creators: [{ name: 'Writer B', roles: ['penciler'] }],
        }),
      )
    })
    rerender(<ComicIdentity issueId={1} />)
    await waitFor(() => expect(screen.getByText('Writer B')).toBeInTheDocument())

    // A's awaited request finally settles after the remap.
    await act(async () => {
      resolveA?.({ issue_id: 1, refreshed: true, comicvine_issue_id: 'A', outcome: 'complete' })
    })
    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByText('Writer B')).toBeInTheDocument()
    expect(screen.queryByText('Writer A')).not.toBeInTheDocument()
    expect(refreshMetadata).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('creator-status-hydrating')).not.toBeInTheDocument()
  })

  it('navigation to another issue cancels the previous hydration', async () => {
    let resolveA: ((value: unknown) => void) | undefined
    refreshMetadata.mockImplementationOnce(() => new Promise((resolve) => {
      resolveA = resolve
    }))
    getIntelligence
      .mockResolvedValueOnce(intelligence({
        comicvine_issue_id: 'A',
        metadata_status: 'not_deep_fetched',
      }))
      .mockResolvedValueOnce(intelligence({
        comicvine_issue_id: 'B',
        metadata_status: 'complete',
        creators: [{ name: 'Navigated Writer', roles: ['writer'] }],
      }))

    const { rerender } = renderWithToast(<ComicIdentity issueId={1} />)
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledWith(1))

    rerender(<ComicIdentity issueId={2} />)
    expect(await screen.findByText('Navigated Writer')).toBeInTheDocument()

    await act(async () => {
      resolveA?.({ issue_id: 1, refreshed: true, comicvine_issue_id: 'A' })
    })
    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByText('Navigated Writer')).toBeInTheDocument()
    expect(screen.queryByText('Writer A')).not.toBeInTheDocument()
    expect(refreshMetadata).toHaveBeenCalledTimes(1)
  })
})
