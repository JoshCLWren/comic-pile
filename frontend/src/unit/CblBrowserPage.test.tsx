import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { PropsWithChildren } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CblBrowserPage from '../pages/CblBrowserPage'
import { cblSourcesApi } from '../services/api-cbl-sources'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { readingGraphApi } from '../services/api-reading-graph'
import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
  CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { cast } from '../utils/cast'
import {
  MISTER_MIRACLE_OVERLAP,
  SECOND_MISTER_MIRACLE_OVERLAP,
  afterContinuingChoice,
  readingGraphPreview,
  withSavedChoice,
  withoutOverlap,
} from './readingGraphFixture'

vi.mock('../services/api-cbl-sources', () => ({
  cblSourcesApi: {
    discover: vi.fn(),
    preview: vi.fn(),
    plan: vi.fn(),
    commitNew: vi.fn(),
  },
}))

vi.mock('../services/api-reading-graph', () => ({
  readingGraphApi: {
    preview: vi.fn(),
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
const mockGraphPreview = cast<ReturnType<typeof vi.fn>>(readingGraphApi.preview)
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
    volume_year: null,
    publication_year: null,
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
  source?: Partial<CBLAdoptionPreview['source']>
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
      ...overrides?.source,
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
  mockGraphPreview.mockResolvedValue(withoutOverlap())
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

async function openChecklist(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Customize' }))
}

async function expandVolume(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
): Promise<void> {
  await user.click(screen.getByRole('button', { name: `Show issues for ${label}` }))
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
    expect(screen.getByText('Ultimate Universe')).toBeInTheDocument()
    expect(screen.getByText(/JoshCLWren\/CBL-ReadingLists/)).toBeInTheDocument()
    // #3939: the raw .cbl path stays out of the default search row.
    expect(screen.queryByText('Ultimate.cbl')).not.toBeInTheDocument()
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
    // #3939: the whole path is provenance now, shown only under "Source details".
    expect(screen.queryByText('Marvel/Ultimate.cbl')).not.toBeInTheDocument()
    expect(screen.getByText('JoshCLWren/CBL-ReadingLists · 4 issues')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('/mnt/bigdata')
  })

  it('shows a reader-friendly title and hides the raw .cbl path (#3939)', async () => {
    const user = userEvent.setup()
    const rawPath =
      'Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl'
    mockDiscover.mockResolvedValue([
      {
        ...source,
        name: '[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)',
        source_path: rawPath,
      },
    ])
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    const row = await screen.findByRole('button', {
      name: /The New Marvel Ultimate Universe 2\.0 \(CBH\)/,
    })
    expect(row).toHaveTextContent('The New Marvel Ultimate Universe 2.0 (CBH)')
    expect(row).not.toHaveTextContent(rawPath)
    expect(row).not.toHaveTextContent('.cbl')
    expect(screen.queryByText(rawPath)).not.toBeInTheDocument()
  })

  it('previews under the reader-friendly title and keeps the path in Source details (#3939)', async () => {
    const user = userEvent.setup()
    const rawPath =
      'Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl'
    const listed: CBLSourceListDiscoveryItem = {
      ...source,
      name: '[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)',
      source_path: rawPath,
    }
    mockDiscover.mockResolvedValue([listed])
    mockPreview.mockResolvedValue(preview({ source: { source_path: rawPath } }))
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await user.click(
      await screen.findByRole('button', { name: /The New Marvel Ultimate Universe 2\.0 \(CBH\)/ }),
    )
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'The New Marvel Ultimate Universe 2.0 (CBH)' }),
      ).toBeInTheDocument()
    })
    // The path is provenance: it survives only inside the collapsed disclosure.
    const details = screen.getByText('Source details').closest('details')
    expect(details).not.toBeNull()
    expect(details).toContainElement(screen.getByText(rawPath))
  })

  it('shows the add button disabled with a reason while the preview loads (#3939)', async () => {
    const user = userEvent.setup()
    let resolvePreview: (value: CBLAdoptionPreview) => void = () => undefined
    mockPreview.mockImplementation(
      () =>
        new Promise<CBLAdoptionPreview>((resolve) => {
          resolvePreview = resolve
        }),
    )
    renderPage()
    await searchFor(user)
    await user.click(screen.getByRole('button', { name: /Ultimate Universe/ }))

    await waitFor(() => {
      expect(screen.getByText('Wait for the preview to finish.')).toBeInTheDocument()
    })
    const addButton = screen.getByRole('button', { name: 'Add this reading order' })
    expect(addButton).toBeDisabled()
    expect(addButton).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('status')).toHaveTextContent('Reconciling source…')
    expect(screen.getByRole('button', { name: 'Customize' })).toBeDisabled()

    await act(async () => {
      resolvePreview(preview())
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Add this reading order' })).not.toBeDisabled()
    })
  })

  it('falls back to a generic title when a source declares no readable title or path', async () => {
    const user = userEvent.setup()
    mockDiscover.mockResolvedValue([
      { ...source, name: '', source_path: '/mnt/bigdata/CBL-ReadingLists' },
    ])
    mockPreview.mockResolvedValue(preview())
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    const row = await screen.findByRole('button', { name: /CBL source/ })
    expect(row).toHaveTextContent('CBL source')
    await user.click(row)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'CBL source' })).toBeInTheDocument()
    })
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
    await openChecklist(user)
    await expandVolume(user, 'Ultimate Spider-Man')
    expect(screen.getByText('Already in ComicPile · read')).toBeInTheDocument()
    expect(screen.getByText('Already in ComicPile · matched by title')).toBeInTheDocument()
    expect(screen.getByText('Missing · will be added')).toBeInTheDocument()
    expect(screen.getByText('Missing · choose whether to add')).toBeInTheDocument()
    expect(screen.getByText('Excluded')).toBeInTheDocument()
    expect(screen.getByText('Needs resolution before commit')).toBeInTheDocument()
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
        { series_decisions: {}, entry_decisions: {}, overlap_decisions: [] },
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
      screen.getByText(/Some entries need resolution before this source can be added/),
    ).toBeInTheDocument()
    expect(mockCommitNew).not.toHaveBeenCalled()
  })

  it('customize excludes a volume locally without re-planning (#3482)', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    expect(mockPlan).not.toHaveBeenCalled()
    await openChecklist(user)
    expect(screen.getByRole('heading', { name: 'Included issues' })).toBeInTheDocument()
    const group = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man series' })
    expect(group).toBeChecked()
    await user.click(group)
    expect(mockPlan).not.toHaveBeenCalled()
    expect(group).not.toBeChecked()
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 0 already in ComicPile · 0 will be added'),
      ).toBeInTheDocument()
    })
  })

  it('include all and include none set every volume decision locally', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await openChecklist(user)
    const group = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man series' })
    await user.click(screen.getByRole('button', { name: 'Include none' }))
    expect(mockPlan).not.toHaveBeenCalled()
    expect(group).not.toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Include all' }))
    expect(group).toBeChecked()
  })

  it('every volume and issue checkbox starts checked on the first add (#4014)', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await openChecklist(user)
    expect(screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man series' })).toBeChecked()
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()
    await expandVolume(user, 'Ultimate Spider-Man')
    expect(screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #1' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #2' })).toBeChecked()
  })

  it('unchecking one issue makes its volume checkbox indeterminate (#4014)', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await openChecklist(user)
    await expandVolume(user, 'Ultimate Spider-Man')
    const group = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man series' })
    const missing = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #2' })
    await user.click(missing)
    expect(group).toBePartiallyChecked()
    expect(screen.getByText('1 of 2 selected')).toBeInTheDocument()
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 1 already in ComicPile · 0 will be added'),
      ).toBeInTheDocument()
    })
    // Re-checking that issue restores the volume's checked state.
    await user.click(missing)
    expect(group).toBeChecked()
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()
  })

  it('re-checking a volume restores the issues the reader unchecked (#4014)', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await openChecklist(user)
    await expandVolume(user, 'Ultimate Spider-Man')
    const group = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man series' })
    await user.click(screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #2' }))
    expect(group).toBePartiallyChecked()
    await user.click(group)
    expect(group).toBeChecked()
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 1 already in ComicPile · 1 will be added'),
      ).toBeInTheDocument()
    })
  })

  it('keeps two same-named volumes in separate groups (#4014)', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(
      user,
      preview({
        entries: [
          entry({ cbl_position: 1, cbl_entry_id: 101, volume_year: 2012 }),
          entry({
            cbl_position: 2,
            cbl_entry_id: 102,
            series_group_id: 'group-2',
            volume_year: 2019,
          }),
        ],
        summary: {
          reused_existing_count: 2,
          missing_would_create_count: 0,
          excluded_count: 0,
          unresolved_count: 0,
          awaiting_opt_in_count: 0,
          final_adopted_count: 2,
          final_adopted_order: [1, 2],
          reused_existing_positions: [1, 2],
          missing_would_create_positions: [],
          excluded_positions: [],
          unresolved_positions: [],
          awaiting_opt_in_positions: [],
        },
      }),
    )
    await openChecklist(user)
    expect(
      screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man (2012) series' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man (2019) series' }),
    ).toBeInTheDocument()
  })

  it('per-entry include checkbox uses a unique name and applies locally', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await openChecklist(user)
    await expandVolume(user, 'Ultimate Spider-Man')
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

  it('unchecking Include on an owned issue excludes it from the committed plan', async () => {
    const user = userEvent.setup()
    mockCommitNew.mockResolvedValue({
      id: 88,
      reused_positions: [],
      created_positions: [2],
      excluded_positions: [1],
      unresolved_positions: [],
    })
    renderPage()
    await searchFor(user)
    await selectSource(user)
    await openChecklist(user)
    await expandVolume(user, 'Ultimate Spider-Man')
    const owned = screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #1' })
    expect(owned).toBeChecked()
    await user.click(owned)
    expect(owned).not.toBeChecked()
    await waitFor(() => {
      expect(
        screen.getByText('2 entries · 0 already in ComicPile · 1 will be added'),
      ).toBeInTheDocument()
    })
    await confirmAdd(user)
    await waitFor(() => {
      expect(mockCommitNew).toHaveBeenCalledTimes(1)
    })
    const [, , choices] = mockCommitNew.mock.calls[0]
    expect(choices.entry_decisions).toEqual({ '101': false })
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
    await openChecklist(user)
    await user.click(screen.getByRole('checkbox', { name: 'Include Ultimate Spider-Man series' }))
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
      screen.queryByRole('heading', { name: 'Included issues' }),
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
    await openChecklist(user)
    await expandVolume(user, 'Ultimate Spider-Man')
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    expect(mockPlan).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(screen.getByText('Skipped')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Add this reading order' }),
      ).not.toBeDisabled()
    })
  })

  it('excluding the series of an unresolved entry unblocks the add (#3542)', async () => {
    const user = userEvent.setup()
    const unresolvedEntry = entry({
      cbl_position: 2,
      cbl_entry_id: 102,
      issue_number: '1',
      series_name: 'Ultimate Hawkeye',
      series_group_id: 'group-2',
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
    expect(screen.getByRole('button', { name: 'Add this reading order' })).toBeDisabled()
    expect(
      screen.getByText('1 entry still needs attention before this source can be added.'),
    ).toBeInTheDocument()

    await openChecklist(user)
    const group = screen.getByRole('checkbox', { name: 'Include Ultimate Hawkeye series' })
    expect(group).toBeChecked()
    await user.click(group)
    expect(mockPlan).not.toHaveBeenCalled()
    await expandVolume(user, 'Ultimate Hawkeye')
    await waitFor(() => {
      expect(screen.getByText('Skipped')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Add this reading order' }),
      ).not.toBeDisabled()
    })
    expect(screen.queryByText(/still needs attention/)).not.toBeInTheDocument()

    // Skip stays available: the reader can put the entry back to unresolved.
    await user.click(screen.getByRole('button', { name: 'Unskip' }))
    await waitFor(() => {
      expect(
        screen.getByText('Needs resolution before commit'),
      ).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Add this reading order' })).toBeDisabled()
    })
  })

  it('skips the reading graph entirely when the source has no real overlap (#4020)', async () => {
    const user = userEvent.setup()
    mockGraphPreview.mockResolvedValue(withoutOverlap())
    renderPage()
    await searchFor(user)
    await selectSource(user)

    await waitFor(() => {
      expect(mockGraphPreview).toHaveBeenCalledTimes(1)
    })
    expect(screen.queryByTestId('reading-graph-summary')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
    expect(
      screen.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Resolve overlapping series' }),
    ).not.toBeInTheDocument()
  })

  it('asks about a real overlap one series at a time, then shows the new graph (#4020)', async () => {
    const user = userEvent.setup()
    mockGraphPreview.mockImplementation(
      async (_listId: number, request: { overlap_choices: Array<{ choice: string }> }) =>
        request.overlap_choices.some((entry) => entry.choice === 'continue_series')
          ? afterContinuingChoice()
          : readingGraphPreview(),
    )
    renderPage()
    await searchFor(user)
    await selectSource(user)

    const summary = await screen.findByTestId('reading-graph-summary')
    expect(summary).toHaveTextContent('Reading graph')
    expect(summary).toHaveTextContent('3 series · 1 rollable · 4 waiting')
    expect(summary).toHaveTextContent('Mister Miracle (1989)')
    expect(summary).toHaveTextContent('Waits for Fourth World #2')
    expect(summary).toHaveTextContent('Needs a decision before saving')

    await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
    expect(
      screen.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Add this reading order?' }),
    ).not.toBeInTheDocument()

    await user.click(
      screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }),
    )
    await waitFor(() => {
      expect(mockGraphPreview).toHaveBeenLastCalledWith(
        7,
        expect.objectContaining({
          overlap_choices: [
            { overlap_id: MISTER_MIRACLE_OVERLAP.overlap_id, choice: 'continue_series' },
          ],
        }),
      )
    })

    await user.click(screen.getByRole('button', { name: 'Use these choices' }))
    // Finishing the questionnaire continues into the add confirmation.
    expect(
      screen.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('reading-graph-summary')).toHaveTextContent(
      'Mister Miracle waits; JLI continues',
    )
    expect(screen.getByTestId('reading-graph-summary')).toHaveTextContent(
      '3 series · 2 rollable · 3 waiting',
    )

    mockCommitNew.mockResolvedValue({ id: 51 })
    mockApplyCommitted.mockResolvedValue(undefined)
    await user.click(screen.getByRole('button', { name: 'Add reading order' }))
    await waitFor(() => {
      expect(mockCommitNew).toHaveBeenCalledTimes(1)
    })
    const [, , choices] = mockCommitNew.mock.calls[0]
    expect(choices.overlap_decisions).toEqual([
      { overlap_id: MISTER_MIRACLE_OVERLAP.overlap_id, choice: 'continue_series' },
    ])
  })

  it('restores a saved series decision without asking again (#4020)', async () => {
    const user = userEvent.setup()
    mockGraphPreview.mockResolvedValue(withSavedChoice('continue_series'))
    renderPage()
    await searchFor(user)
    await selectSource(user)

    const summary = await screen.findByTestId('reading-graph-summary')
    await waitFor(() => {
      expect(summary).toHaveTextContent('Mister Miracle waits; JLI continues')
    })
    expect(summary).not.toHaveTextContent('Needs a decision before saving')
    expect(
      screen.getByRole('button', { name: 'Review series decisions' }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
    expect(
      screen.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Resolve overlapping series' }),
    ).not.toBeInTheDocument()

    mockCommitNew.mockResolvedValue({ id: 52 })
    mockApplyCommitted.mockResolvedValue(undefined)
    await user.click(screen.getByRole('button', { name: 'Add reading order' }))
    await waitFor(() => {
      expect(mockCommitNew).toHaveBeenCalledTimes(1)
    })
    const [, , choices] = mockCommitNew.mock.calls[0]
    expect(choices.overlap_decisions).toEqual([
      { overlap_id: MISTER_MIRACLE_OVERLAP.overlap_id, choice: 'continue_series' },
    ])
  })

  it('asks about same-named volumes separately (#4020)', async () => {
    const user = userEvent.setup()
    mockGraphPreview.mockResolvedValue(
      readingGraphPreview({
        overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
      }),
    )
    renderPage()
    await searchFor(user)
    await selectSource(user)

    await screen.findByTestId('reading-graph-summary')
    await user.click(screen.getByRole('button', { name: 'Resolve 2 series overlaps' }))
    expect(screen.getByText('Overlap 1 of 2')).toBeInTheDocument()
    expect(
      screen.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (1989) waits?',
      }),
    ).toBeInTheDocument()

    await user.click(
      screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }),
    )
    mockGraphPreview.mockResolvedValue(
      readingGraphPreview({
        overlaps: [
          { ...MISTER_MIRACLE_OVERLAP, selected_choice: 'continue_series' },
          SECOND_MISTER_MIRACLE_OVERLAP,
        ],
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Next series' }))
    expect(screen.getByText('Overlap 2 of 2')).toBeInTheDocument()
    expect(
      screen.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (2019) waits?',
      }),
    ).toBeInTheDocument()
  })

  it('keeps the one-decision flow when the reading graph is unavailable (#4020)', async () => {
    const user = userEvent.setup()
    const committed = { id: 42, name: 'Ultimate Universe' }
    mockCommitNew.mockResolvedValue(committed)
    mockApplyCommitted.mockResolvedValue(undefined)
    mockGraphPreview.mockRejectedValue(new Error('Not Found'))
    renderPage()
    await searchFor(user)
    await selectSource(user)

    await waitFor(() => {
      expect(
        screen.getByText(/ComicPile could not load the reading graph/),
      ).toBeInTheDocument()
    })
    const addButton = screen.getByRole('button', { name: 'Add this reading order' })
    expect(addButton).not.toBeDisabled()
    await user.click(addButton)
    expect(
      screen.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add reading order' }))
    await waitFor(() => {
      expect(mockCommitNew).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(mockApplyCommitted).toHaveBeenCalled()
      expect(screen.getByTestId('location')).toHaveTextContent('/continuity-plans/42')
    })
  })

  it('blocks adding when the proposed graph contains a cycle (#4020)', async () => {
    const user = userEvent.setup()
    mockGraphPreview.mockResolvedValue(
      readingGraphPreview({
        cycle_errors: [
          {
            code: 'series_overlap_cycle',
            message: 'Fourth World #2 and Mister Miracle #1 would wait on each other.',
          },
        ],
      }),
    )
    renderPage()
    await searchFor(user)
    await selectSource(user)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Add this reading order' }),
      ).toBeDisabled()
    })
    expect(
      screen.getByText('Fourth World #2 and Mister Miracle #1 would wait on each other.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Resolve the reading-order loop before adding this source.'),
    ).toBeInTheDocument()
  })
})
