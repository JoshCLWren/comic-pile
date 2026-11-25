import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { issueCardsApi } from '../services/issueCardsApi'
import { existingList } from './fixtures/customCblFixture'
import { injectModuleDoubles } from './injectModuleDoubles'

const mocks = {
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  searchIssues: vi.fn(),
  apply: vi.fn(),
  exportXml: vi.fn(),
}

await injectModuleDoubles(await import('../services/api-custom-cbl'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-custom-cbl')>()
  return { ...actual, customCBLApi: mocks }
})

const cblMocks = { discover: vi.fn(), preview: vi.fn() }

await injectModuleDoubles(await import('../services/api-cbl-sources'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-cbl-sources')>()
  return { ...actual, cblSourcesApi: cblMocks }
})

function renderCanonicalBuilder() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: false,
      },
      mutations: { retry: false },
    },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CustomCBLBuilder /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('canonical Custom CBL deletion accessibility', () => {
  const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')

  beforeEach(() => {
    vi.resetAllMocks()
    fetchCards.mockResolvedValue([])
    mocks.get.mockResolvedValue(existingList)
    mocks.searchIssues.mockResolvedValue([])
    cblMocks.discover.mockResolvedValue([])
    cblMocks.preview.mockResolvedValue(null)
  })

  it('keeps pending deletion focused and undismissable, then restores focus after success', async () => {
    let finishDelete: (() => void) | undefined
    let finishListRefresh: (() => void) | undefined
    mocks.list.mockResolvedValueOnce([{
      id: existingList.id,
      name: existingList.name,
      description: existingList.description,
      mode: existingList.mode,
      issue_count: existingList.issue_count,
      updated_at: existingList.updated_at,
    }]).mockImplementation(() => new Promise((resolve) => {
      finishListRefresh = () => resolve([])
    }))
    mocks.delete.mockImplementation(() => new Promise<void>((resolve) => {
      finishDelete = resolve
    }))

    renderCanonicalBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete custom CBL' }))
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledExactlyOnceWith(9))

    await waitFor(() => {
      expect(dialog).toHaveFocus()
      expect(within(dialog).getByRole('button', { name: 'Close modal' })).toBeDisabled()
      expect(within(dialog).getByRole('status')).toHaveTextContent('Deleting…')
    })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(dialog).toBeInTheDocument()
    expect(mocks.delete).toHaveBeenCalledExactlyOnceWith(9)

    await act(async () => {
      finishDelete?.()
    })
    // The mutation remains pending while the authoritative list cache refreshes.
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2))
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Close modal' })).toBeDisabled()

    await act(async () => {
      finishListRefresh?.()
    })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Custom CBL deleted.'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Custom CBLs' })).toHaveFocus()
  })
})
