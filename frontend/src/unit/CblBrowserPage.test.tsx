import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { PropsWithChildren } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CblBrowserPage from '../pages/CblBrowserPage'
import { cblSourcesApi } from '../services/api-cbl-sources'
import { continuityPlansApi } from '../services/api-continuity-plans'
import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
  CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { cast } from '../utils/cast'

vi.mock('../services/api-cbl-sources', () => ({
  cblSourcesApi: {
    discover: vi.fn(),
    preview: vi.fn(),
    plan: vi.fn(),
    commitNew: vi.fn(),
  },
}))

vi.mock('../services/api-continuity-plans', () => ({
  continuityPlansApi: {
    list: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../query/cacheEffects', () => ({
  applyCommittedReadingPlan: vi.fn(),
}))

const mockDiscover = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.discover)
const mockPreview = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.preview)
const mockPlan = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.plan)
const mockCommitNew = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.commitNew)
const mockListPlans = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.list)
const mockGetPlan = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.get)
const mockApplyCommitted = cast<ReturnType<typeof vi.fn>>(applyCommittedReadingPlan)

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})

function queryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname}</p>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cbl-sources']}>
      <Routes>
        <Route path="/cbl-sources" element={<CblBrowserPage />} />
        <Route path="/continuity-plans/:id" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: queryWrapper },
  )
}

const source: CBLSourceListDiscoveryItem = {
  id: 7,
  name: 'Ultimate Universe',
  source_path: 'Ultimate.cbl',
  source_repository: 'JoshCLWren/CBL-ReadingLists',
  declared_issue_count: 4,
  content_hash: 'hash-1',
  revision_sha: 'abcdef1234567890',
}

function entry(overrides: Partial<CBLAdoptionPreviewEntry>): CBLAdoptionPreviewEntry {
  return {
    cbl_position: 1,
    cbl_entry_id: 101,
    series_name: 'Ultimate Spider-Man',
    issue_number: '1',
    series_group_id: 'group-1',
    adoption_class: 'existing',
    adoption_decision: 'included_existing',
    adopted: true,
    comicvine_issue_id: '4000-1',
    comicvine_series_id: null,
    series_provider: 'comicvine',
    series_external_id: null,
    resolved_issue_id: 11,
    canonical_issue_id: 11,
    read_status: 'unread',
    read_at: null,
    resolution_status: 'resolved_via_comicvine_canonical',
    is_duplicate_identity: false,
    ...overrides,
  }
}

function preview(overrides?: {
  entries?: CBLAdoptionPreviewEntry[]
  summary?: Partial<CBLAdoptionPreview['summary']>
}): CBLAdoptionPreview {
  const entries = overrides?.entries ?? [
    entry({}),
    entry({
      cbl_position: 2,
      cbl_entry_id: 102,
      issue_number: '2',
      adoption_class: 'missing_importable',
      adoption_decision: 'would_create_missing',
      adopted: true,
      resolved_issue_id: null,
      canonical_issue_id: null,
      resolution_status: 'no_owned_issue_for_comicvine_id',
    }),
  ]
  return {
    source: {
      source_list_id: 7,
      source_repository: 'JoshCLWren/CBL-ReadingLists',
      source_path: 'Ultimate.cbl',
      content_hash: 'hash-1',
      revision_sha: 'abcdef1234567890',
    },
    total_positions: entries.length,
    entries,
    summary: {
      reused_existing_count: 1,
      missing_would_create_count: 1,
      excluded_count: 0,
      unresolved_count: 0,
      awaiting_opt_in_count: 0,
      final_adopted_count: 2,
      final_adopted_order: [1, 2],
      reused_existing_positions: [1],
      missing_would_create_positions: [2],
      excluded_positions: [],
      unresolved_positions: [],
      awaiting_opt_in_positions: [],
      ...overrides?.summary,
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
})

async function searchFor(user: ReturnType<typeof userEvent.setup>, term = 'ultimate') {
  mockDiscover.mockResolvedValue([source])
  await user.type(screen.getByLabelText('Search source lists'), term)
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
  })
}

async function selectSource(user: ReturnType<typeof userEvent.setup>, p = preview()) {
  mockPreview.mockResolvedValue(p)
  await user.click(screen.getByRole('button', { name: /Ultimate Universe/ }))
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'Ultimate Universe' })).toBeInTheDocument()
  })
}

async function confirmAdd(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
  await user.click(screen.getByRole('button', { name: 'Add reading order' }))
}

describe('CblBrowserPage', () => {
  it('renders the search form before any search', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'CBL Sources' })).toBeInTheDocument()
    expect(screen.getByLabelText('Search source lists')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument()
    expect(mockDiscover).not.toHaveBeenCalled()
  })

  it('searches and lists matching sources', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    expect(mockDiscover).toHaveBeenCalledWith('ultimate')
    expect(screen.getByText('Ultimate.cbl')).toBeInTheDocument()
    expect(screen.getByText(/JoshCLWren\/CBL-ReadingLists/)).toBeInTheDocument()
  })

  it('hides filesystem mirror paths from source cards (#3365)', async () => {
    const user = userEvent.setup()
    const leaked: CBLSourceListDiscoveryItem = {
      ...source,
      source_path: '/mnt/bigdata/CBL-ReadingLists/Marvel/Ultimate.cbl',
      source_repository: '/mnt/bigdata/CBL-ReadingLists',
    }
    mockDiscover.mockResolvedValue([leaked])
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
    })
    expect(screen.getByText('Marvel/Ultimate.cbl')).toBeInTheDocument()
    expect(screen.getByText('JoshCLWren/CBL-ReadingLists · 4 issues')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('/mnt/bigdata')
  })

  it('shows an empty state when no sources match', async () => {
    const user = userEvent.setup()
    mockDiscover.mockResolvedValue([])
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'nothing')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(screen.getByText('No matching source lists found.')).toBeInTheDocument()
    })
  })

  it('shows an error when discovery fails', async () => {
    const user = userEvent.setup()
    mockDiscover.mockRejectedValue(new Error('Network error'))
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'x')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Network error')
    })
  })

  it('selecting a source shows the preview with the consequence summary', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    expect(mockPreview).toHaveBeenCalledWith(7)
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 1 already in ComicPile · 1 will be added'),
      ).toBeInTheDocument()
    })
    expect(screen.queryByText('abcdef12')).not.toBeInTheDocument()
    expect(screen.getByText('Source details')).toBeInTheDocument()
  })

  it('uses singular grammar for one entry that needs attention', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(
      user,
      preview({
        entries: [
          entry({
            adoption_class: 'ambiguous_unresolved',
            adoption_decision: 'unresolved',
            adopted: false,
            resolved_issue_id: null,
            canonical_issue_id: null,
            resolution_status: 'ambiguous_no_comicvine_id',
          }),
        ],
        summary: {
          reused_existing_count: 0,
          missing_would_create_count: 0,
          excluded_count: 0,
          unresolved_count: 1,
          awaiting_opt_in_count: 0,
          final_adopted_count: 0,
          final_adopted_order: [],
          reused_existing_positions: [],
          missing_would_create_positions: [],
          excluded_positions: [],
          unresolved_positions: [1],
          awaiting_opt_in_positions: [],
        },
      }),
    )
    expect(screen.getByText(/1 entry · 0 already in ComicPile · 0 will be added · 1 needs attention/)).toBeInTheDocument()
    expect(
      screen.getByText('1 entry still needs attention before this source can be added.'),
    ).toBeInTheDocument()
  })

  it('renders a status label for every adoption decision', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(
      user,
      preview({
        entries: [
          entry({ adoption_decision: 'included_existing', read_status: 'read' }),
          entry({
            cbl_position: 2,
            cbl_entry_id: 102,
            adoption_decision: 'included_existing',
            resolution_status: 'resolved_via_title_number_fallback',
          }),
          entry({
            cbl_position: 3,
            cbl_entry_id: 103,
            adoption_class: 'missing_importable',
            adoption_decision: 'would_create_missing',
            adopted: true,
            resolved_issue_id: null,
            canonical_issue_id: null,
            resolution_status: 'no_owned_issue_for_comicvine_id',
          }),
          entry({
            cbl_position: 4,
            cbl_entry_id: 104,
            adoption_class: 'missing_importable',
            adoption_decision: 'awaiting_opt_in',
            adopted: false,
            resolved_issue_id: null,
            canonical_issue_id: null,
            resolution_status: 'no_owned_issue_for_comicvine_id',
          }),
          entry({
            cbl_position: 5,
            cbl_entry_id: 105,
            adoption_decision: 'excluded',
            adopted: false,
          }),
          entry({
            cbl_position: 6,
            cbl_entry_id: 106,
            adoption_class: 'ambiguous_unresolved',
            adoption_decision: 'unresolved',
            adopted: false,
            resolved_issue_id: null,
            canonical_issue_id: null,
            resolution_status: 'ambiguous_no_comicvine_id',
          }),
        ],
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Customize' }))
    expect(screen.getByText('Already in ComicPile · read')).toBeInTheDocument()
    expect(screen.getByText('Already in ComicPile · matched by title')).toBeInTheDocument()
    expect(screen.getByText('Missing · will be added')).toBeInTheDocument()
    expect(screen.getByText('Missing · choose whether to add')).toBeInTheDocument()
    expect(screen.getByText('Excluded')).toBeInTheDocument()
    expect(screen.getByText('Needs identity resolution')).toBeInTheDocument()
    expect(
      screen.getByText(
        'This entry has no ComicVine issue ID, so ComicPile cannot match it to an owned comic.',
      ),
    ).toBeInTheDocument()
  })

  it('confirms before adding and opens the plan', async () => {
    const user = userEvent.setup()
    const committed = { id: 42, name: 'Ultimate Universe' }
    mockCommitNew.mockResolvedValue(committed)
    mockApplyCommitted.mockResolvedValue(undefined)
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
    expect(mockCommitNew).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: 'Add this reading order?' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add reading order' }))
    await waitFor(() => {
      expect(mockCommitNew).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ total_positions: 2 }),
        { series_decisions: {}, entry_decisions: {} },
      )
    })
    await waitFor(() => {
      expect(mockApplyCommitted).toHaveBeenCalled()
      expect(screen.getByTestId('location')).toHaveTextContent('/continuity-plans/42')
    })
  })

  it('cancel on the confirm step creates nothing', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(mockCommitNew).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: 'Add this reading order?' })).not.toBeInTheDocument()
  })

  it('blocks the add when entries need attention', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(
      user,
      preview({
        entries: [
          entry({
            adoption_class: 'ambiguous_unresolved',
            adoption_decision: 'unresolved',
            adopted: false,
            resolved_issue_id: null,
            canonical_issue_id: null,
            resolution_status: 'ambiguous_no_comicvine_id',
          }),
        ],
        summary: {
          reused_existing_count: 0,
          missing_would_create_count: 0,
          excluded_count: 0,
          unresolved_count: 1,
          awaiting_opt_in_count: 0,
          final_adopted_count: 0,
          final_adopted_order: [],
          reused_existing_positions: [],
          missing_would_create_positions: [],
          excluded_positions: [],
          unresolved_positions: [1],
          awaiting_opt_in_positions: [],
        },
      }),
    )
    const addButton = screen.getByRole('button', { name: 'Add this reading order' })
    expect(addButton).toBeDisabled()
    expect(
      screen.getByText(/Some entries need identity resolution before this source can be added/),
    ).toBeInTheDocument()
    expect(mockCommitNew).not.toHaveBeenCalled()
  })

  it('customize excludes a series locally without re-planning (#3482)', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    expect(mockPlan).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Customize' }))
    expect(screen.getByRole('heading', { name: 'Series choices' })).toBeInTheDocument()
    const group = screen.getByRole('group', { name: 'Ultimate Spider-Man series choice' })
    const exclude = within(group).getByRole('button', { name: 'Exclude' })
    expect(exclude).toHaveAttribute('aria-pressed', 'false')
    await user.click(exclude)
    expect(mockPlan).not.toHaveBeenCalled()
    expect(exclude).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 0 already in ComicPile · 0 will be added'),
      ).toBeInTheDocument()
    })
  })

  it('include all and include none set every series decision locally', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await user.click(screen.getByRole('button', { name: 'Customize' }))
    const group = screen.getByRole('group', { name: 'Ultimate Spider-Man series choice' })
    await user.click(screen.getByRole('button', { name: 'Include none' }))
    expect(mockPlan).not.toHaveBeenCalled()
    expect(within(group).getByRole('button', { name: 'Exclude' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(screen.getByRole('button', { name: 'Include all' }))
    expect(within(group).getByRole('button', { name: 'Include' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('per-entry include checkbox uses a unique name and applies locally', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await user.click(screen.getByRole('button', { name: 'Customize' }))
    const owned = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #1' })
    const missing = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #2' })
    expect(owned).toBeChecked()
    expect(missing).toBeChecked()
    await user.click(missing)
    expect(mockPlan).not.toHaveBeenCalled()
    expect(missing).not.toBeChecked()
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 1 already in ComicPile · 0 will be added'),
      ).toBeInTheDocument()
    })
  })

  it('a 409 on commit surfaces the stale-review message and refresh recovers', async () => {
    const user = userEvent.setup()
    const conflict = Object.assign(new Error('Conflict'), {
      isAxiosError: true,
      response: { status: 409, data: { detail: 'changed' } },
    })
    mockCommitNew.mockRejectedValue(conflict)
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await confirmAdd(user)
    await waitFor(() => {
      expect(
        screen.getByText(/This source changed after you reviewed it/),
      ).toBeInTheDocument()
    })
    expect(
      screen.getByRole('button', { name: 'Refresh preview' }),
    ).toBeInTheDocument()
    mockPreview.mockResolvedValue(preview())
    await user.click(screen.getByRole('button', { name: 'Refresh preview' }))
    await waitFor(() => {
      expect(mockPreview).toHaveBeenCalledTimes(2)
    })
  })

  it('recovers a timed-out commit by polling the created plan (#3364)', async () => {
    const user = userEvent.setup()
    const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
      code: 'ECONNABORTED',
    })
    mockCommitNew.mockRejectedValue(timeout)
    mockListPlans.mockResolvedValue([
      {
        id: 88,
        name: 'Ultimate Universe',
        ordering_mode: 'informational',
        lane_count: 1,
        step_count: 2,
        source_paths: ['Ultimate.cbl'],
        updated_at: '2026-10-12T00:00:00Z',
      },
    ])
    const recovered = { id: 88, name: 'Ultimate Universe' }
    mockGetPlan.mockResolvedValue(recovered)
    mockApplyCommitted.mockResolvedValue(undefined)
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await confirmAdd(user)
    await waitFor(() => {
      expect(mockListPlans).toHaveBeenCalled()
      expect(mockGetPlan).toHaveBeenCalledWith(88)
      expect(screen.getByTestId('location')).toHaveTextContent('/continuity-plans/88')
    })
    expect(screen.queryByText(/Network error/)).not.toBeInTheDocument()
  })

  it('a new search resets the selection and decisions', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await user.click(screen.getByRole('button', { name: 'Customize' }))
    const group = screen.getByRole('group', { name: 'Ultimate Spider-Man series choice' })
    await user.click(within(group).getByRole('button', { name: 'Exclude' }))
    mockDiscover.mockResolvedValue([source])
    await user.clear(screen.getByLabelText('Search source lists'))
    await user.type(screen.getByLabelText('Search source lists'), 'other')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(
        screen.queryByRole('heading', { name: 'Ultimate Universe' }),
      ).not.toBeInTheDocument()
    })
    expect(
      screen.queryByRole('heading', { name: 'Series choices' }),
    ).not.toBeInTheDocument()
  })

  it('skipping an unresolved entry unblocks the add locally', async () => {
    const user = userEvent.setup()
    const unresolvedEntry = entry({
      cbl_position: 2,
      cbl_entry_id: 102,
      issue_number: '2',
      adoption_class: 'ambiguous_unresolved',
      adoption_decision: 'unresolved',
      adopted: false,
      resolved_issue_id: null,
      canonical_issue_id: null,
      resolution_status: 'ambiguous_no_comicvine_id',
    })
    const initialPreview = preview({
      entries: [entry({}), unresolvedEntry],
      summary: {
        reused_existing_count: 1,
        missing_would_create_count: 0,
        excluded_count: 0,
        unresolved_count: 1,
        awaiting_opt_in_count: 0,
        final_adopted_count: 1,
        final_adopted_order: [1],
        reused_existing_positions: [1],
        missing_would_create_positions: [],
        excluded_positions: [],
        unresolved_positions: [2],
        awaiting_opt_in_positions: [],
      },
    })
    renderPage()
    await searchFor(user)
    await selectSource(user, initialPreview)
    expect(
      screen.getByRole('button', { name: 'Add this reading order' }),
    ).toBeDisabled()
    expect(
      screen.getByText(/You can skip individual entries under Customize/),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Customize' }))
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    expect(mockPlan).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(screen.getByText('Skipped')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Add this reading order' }),
      ).not.toBeDisabled()
    })
  })
})
