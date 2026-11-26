import { StrictMode, type ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
import { useComicVineMetadataHydration } from '../hooks/useComicVineMetadataHydration'

vi.mock('../services/api-comicvine', async () => {
  const actual = await vi.importActual<typeof import('../services/api-comicvine')>('../services/api-comicvine')
  return { ...actual, comicVineApi: { getIssueIntelligence: vi.fn(), importIssue: vi.fn(), refreshMetadata: vi.fn() } }
})

const refreshMetadata = vi.mocked(comicVineApi.refreshMetadata)

function Wrapper({ children }: { children: ReactNode }) {
  return <StrictMode>{children}</StrictMode>
}

describe('temp StrictMode hydration probe', () => {
  beforeEach(() => {
    refreshMetadata.mockReset()
  })

  it('settles a retry to the terminal outcome under StrictMode', async () => {
    refreshMetadata.mockResolvedValue({
      issue_id: 1,
      refreshed: true,
      comicvine_issue_id: '100',
      outcome: 'no_credits',
      retry_after_seconds: null,
    })
    const metadata: ComicVineIssueIntelligence = {
      comicvine_issue_id: '100',
      comicvine_url: null,
      series_name: 'Test Series',
      series_id: 1,
      issue_number: '1',
      name: 'Test Issue',
      description: null,
      image_url: null,
      creators: [],
      story_arcs: [],
      metadata_status: 'needs_hydration',
      refresh_retry_after_seconds: null,
    }
    const { result } = renderHook(
      () => useComicVineMetadataHydration({
        issueId: 1,
        metadata,
        refetchIntelligence: async () => metadata,
      }),
      { wrapper: Wrapper },
    )

    await act(async () => {
      await result.current.retry()
    })

    expect(result.current.presentation).toBe('no_credits')
    expect(result.current.isHydrating).toBe(false)
  })
})
