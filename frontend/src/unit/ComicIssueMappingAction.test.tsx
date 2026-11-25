/**
 * Shared issue mapping control (#4450).
 *
 * Guards the owner-approved contract: every owned issue card exposes a
 * visible Map/Change/Review action, mapping is optional for reading, search
 * runs only on demand, and provider-only entries never hit the owner-scoped
 * mapping mutation.
 */
<<<<<<< HEAD
import { render, screen, waitFor, fireEvent } from './testingLibrary'
=======
import { render, screen, waitFor, fireEvent, renderHook, act } from '@testing-library/react'
>>>>>>> origin/main
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IssueIdentityResponse } from '../services/api-comicvine'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { useComicIssueMapping } from '../hooks/useComicIssueMapping'

const { searchSeriesSpy, getIssueIdentitySpy, confirmIdentitySpy, replaceIdentitySpy, removeIdentitySpy } =
  vi.hoisted(() => ({
    searchSeriesSpy: vi.fn(),
    getIssueIdentitySpy: vi.fn(),
    confirmIdentitySpy: vi.fn(),
    replaceIdentitySpy: vi.fn(),
    removeIdentitySpy: vi.fn(),
  }))

await injectModuleDoubles(await import('../services/api-comicvine'), () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    getSeriesIssues: vi.fn().mockResolvedValue({ comicvine_volume_id: 42, series_name: '', issues: [] }),
    getIssueIntelligence: vi.fn().mockResolvedValue(null),
    getIssueIdentity: getIssueIdentitySpy,
    confirmIdentity: confirmIdentitySpy,
    replaceIdentity: replaceIdentitySpy,
    removeIdentity: removeIdentitySpy,
    refreshMetadata: vi.fn(),
    applyCorrection: vi.fn(),
    listCorrections: vi.fn().mockResolvedValue([]),
    revertCorrection: vi.fn(),
  },
}))

import ComicIssueMappingAction from '../components/ComicIssueMappingAction'
import { injectModuleDoubles } from './injectModuleDoubles'

const UNMAPPED: IssueIdentityResponse = {
  issue_id: 77,
  thread_id: 7,
  thread_title: 'Hellboy in Hell',
  has_confirmed_identity: false,
  comicvine_issue_id: null,
  confirmed_mappings: [],
  candidate_mappings: [],
  has_unresolved: false,
}

const MAPPED: IssueIdentityResponse = {
  ...UNMAPPED,
  has_confirmed_identity: true,
  comicvine_issue_id: '36956',
  confirmed_mappings: [],
}

const AMBIGUOUS: IssueIdentityResponse = {
  ...UNMAPPED,
  has_unresolved: true,
  candidate_mappings: [
    {
      external_identity_id: 1,
      provider: 'comicvine',
      comicvine_id: '36956',
      status: 'candidate',
      confidence: null,
      evidence_source: null,
      created_at: null,
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  getIssueIdentitySpy.mockResolvedValue(UNMAPPED)
  confirmIdentitySpy.mockResolvedValue(MAPPED)
  removeIdentitySpy.mockResolvedValue(UNMAPPED)
})

describe('ComicIssueMappingAction', () => {
  it('shows a visible Map comic action for an unmapped owned issue without opening a search', async () => {
    render(
      <ComicIssueMappingAction issueId={77} threadTitle="Hellboy in Hell" issueNumber="1" />,
    )
    expect(await screen.findByTestId('comic-mapping-map')).toHaveTextContent('Map comic')
    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Not mapped')
    expect(searchSeriesSpy).not.toHaveBeenCalled()
  })

  it('shows a loading mapping state on mount instead of a transient unmapped state (#5264)', async () => {
    let resolveIdentity: (value: IssueIdentityResponse) => void = () => {}
    getIssueIdentitySpy.mockReturnValueOnce(
      new Promise<IssueIdentityResponse>((resolve) => {
        resolveIdentity = resolve
      }),
    )

    render(
      <ComicIssueMappingAction issueId={77} threadTitle="Hellboy in Hell" issueNumber="1" />,
    )

    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Checking mapping…')
    expect(screen.queryByText('Not mapped')).toBeNull()

    resolveIdentity(UNMAPPED)
    expect(await screen.findByTestId('comic-mapping-map')).toHaveTextContent('Map comic')
    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Not mapped')
  })

  it('shows Mapped plus Change mapping for a mapped issue', () => {
    render(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={MAPPED}
      />,
    )
    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Mapped')
    expect(screen.getByTestId('comic-mapping-change')).toHaveTextContent('Change mapping')
    expect(screen.getByTestId('comic-mapping-remove')).toBeTruthy()
    expect(getIssueIdentitySpy).not.toHaveBeenCalled()
  })

  it('shows Review mapping for ambiguous candidates without auto-confirming', () => {
    render(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={AMBIGUOUS}
      />,
    )
    expect(screen.getByTestId('comic-mapping-map')).toHaveTextContent('Review mapping')
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('renders a non-blocking error status with Retry when the identity lookup fails', async () => {
    getIssueIdentitySpy.mockRejectedValueOnce(new Error('offline'))
    render(
      <ComicIssueMappingAction issueId={77} threadTitle="Hellboy in Hell" issueNumber="1" />,
    )
    expect(await screen.findByTestId('comic-mapping-retry')).toBeTruthy()
    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Mapping status unavailable')
    // Reading actions are owned by the parent card and stay enabled.
    expect(screen.getByTestId('comic-mapping-map')).toBeTruthy()
  })

  it('offers Add to ComicPile instead of mapping for provider-only entries', () => {
    const onAdd = vi.fn()
    render(
      <ComicIssueMappingAction
        issueId={null}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        isOwned={false}
        onAddToLibrary={onAdd}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Add to ComicPile' }))
    expect(onAdd).toHaveBeenCalledTimes(1)
    expect(getIssueIdentitySpy).not.toHaveBeenCalled()
    expect(screen.queryByTestId('comic-mapping-map')).toBeNull()
  })

  it('opens the shared search dialog only after the reader asks for it', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Hellboy in Hell',
      results: [],
      total_available: 0,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    render(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={UNMAPPED}
      />,
    )
    fireEvent.click(screen.getByTestId('comic-mapping-map'))
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
  })

  it('removes the mapping through the accessible confirm dialog and refetches', async () => {
    const onMapped = vi.fn().mockResolvedValue(undefined)
    render(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={MAPPED}
        onMapped={onMapped}
      />,
    )
    fireEvent.click(screen.getByTestId('comic-mapping-remove'))
    fireEvent.click(await screen.findByText('Remove mapping'))
    await waitFor(() => expect(removeIdentitySpy).toHaveBeenCalledWith(77))
    await waitFor(() => expect(queryClient.setQueryData).toHaveBeenCalledWith(
      queryKeys.comicVine.issueIntelligence(77),
      null,
    ))
    await waitFor(() => expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.comicVine.issueIntelligence(77),
      exact: true,
    }))
    await waitFor(() => expect(onMapped).toHaveBeenCalled())
    expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Not mapped')
    expect(screen.getByTestId('comic-mapping-map')).toHaveTextContent('Map comic')
    expect(screen.queryByTestId('comic-mapping-change')).not.toBeInTheDocument()
    expect(screen.queryByTestId('comic-mapping-remove')).not.toBeInTheDocument()
  })

  it('keeps a successful removal visible when identity reconciliation fails', async () => {
    const onMapped = vi.fn().mockResolvedValue(undefined)
    getIssueIdentitySpy.mockRejectedValue(new Error('identity refresh offline'))
    const { rerender } = render(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={MAPPED}
        onMapped={onMapped}
      />,
    )

    fireEvent.click(screen.getByTestId('comic-mapping-remove'))
    fireEvent.click(await screen.findByText('Remove mapping'))

    await waitFor(() => expect(removeIdentitySpy).toHaveBeenCalledWith(77))
    await waitFor(() =>
      expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Not mapped'),
    )
    rerender(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={{ ...MAPPED }}
        onMapped={onMapped}
      />,
    )
    await waitFor(() =>
      expect(screen.getByTestId('comic-mapping-status')).toHaveTextContent('Not mapped'),
    )
    expect(screen.getByTestId('comic-mapping-map')).toHaveTextContent('Map comic')
    expect(screen.queryByTestId('comic-mapping-retry')).not.toBeInTheDocument()
    expect(screen.queryByTestId('comic-mapping-change')).not.toBeInTheDocument()
    expect(screen.queryByTestId('comic-mapping-remove')).not.toBeInTheDocument()
    await waitFor(() => expect(onMapped).toHaveBeenCalled())
  })

  it('ignores close while a mapping removal is in flight', async () => {
    let resolveRemoval!: (value: IssueIdentityResponse) => void
    removeIdentitySpy.mockImplementation(
      () => new Promise<IssueIdentityResponse>((resolve) => { resolveRemoval = resolve }),
    )
    const { result } = renderHook(() =>
      useComicIssueMapping({
        issueId: 77,
        threadTitle: 'Hellboy in Hell',
        issueNumber: '1',
        initialIdentity: MAPPED,
      }),
    )

    act(() => { result.current.openRemoveDialog() })
    expect(result.current.isRemoveDialogOpen).toBe(true)

    let removePromise!: Promise<void>
    act(() => { removePromise = result.current.handleRemoveMapping() })
    await waitFor(() => expect(result.current.isRemovingMapping).toBe(true))

    act(() => { result.current.closeRemoveDialog() })
    expect(result.current.isRemoveDialogOpen).toBe(true)

    await act(async () => {
      resolveRemoval(UNMAPPED)
      await removePromise
    })
    expect(result.current.isRemoveDialogOpen).toBe(false)
  })

  it('shows a fallback message when mapping removal throws a non-Error value', async () => {
    removeIdentitySpy.mockRejectedValue('boom')

    render(
      <ComicIssueMappingAction
        issueId={77}
        threadTitle="Hellboy in Hell"
        issueNumber="1"
        initialIdentity={MAPPED}
      />,
    )

    fireEvent.click(screen.getByTestId('comic-mapping-remove'))
    fireEvent.click(await screen.findByText('Remove mapping'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not remove the ComicVine mapping.',
    )
  })
})
