import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from './testingLibrary'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { customCBLApi } from '../services/api-custom-cbl'
import { cblSourcesApi, type CBLAdoptionPreview } from '../services/api-cbl-sources'
import { issueCardsApi } from '../services/issueCardsApi'
import { existingList } from './fixtures/customCblFixture'

const mocks = {
  list: vi.spyOn(customCBLApi, 'list'),
  get: vi.spyOn(customCBLApi, 'get'),
  create: vi.spyOn(customCBLApi, 'create'),
  update: vi.spyOn(customCBLApi, 'update'),
  delete: vi.spyOn(customCBLApi, 'delete'),
  searchIssues: vi.spyOn(customCBLApi, 'searchIssues'),
  apply: vi.spyOn(customCBLApi, 'apply'),
  exportXml: vi.spyOn(customCBLApi, 'exportXml'),
}

const cblMocks = {
  discover: vi.spyOn(cblSourcesApi, 'discover'),
  preview: vi.spyOn(cblSourcesApi, 'preview'),
}

const emptyPreview: CBLAdoptionPreview = {
  source: {
    source_list_id: 1,
    source_repository: 'test',
    source_path: 'list.cbl',
    content_hash: 'hash',
    revision_sha: 'revision',
  },
  total_positions: 0,
  entries: [],
  summary: {
    reused_existing_count: 0,
    missing_would_create_count: 0,
    excluded_count: 0,
    unresolved_count: 0,
    awaiting_opt_in_count: 0,
    final_adopted_count: 0,
    final_adopted_order: [],
    reused_existing_positions: [],
    missing_would_create_positions: [],
    excluded_positions: [],
    unresolved_positions: [],
    awaiting_opt_in_positions: [],
  },
}

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
    cblMocks.preview.mockResolvedValue(emptyPreview)
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
