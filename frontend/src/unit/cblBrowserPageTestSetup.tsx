import { act, render, screen, waitFor } from '@testing-library/react'
export { act }
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import type { PropsWithChildren } from 'react'
import { beforeEach, vi } from 'vitest'
import CblBrowserPage from '../pages/CblBrowserPage'
import { cblSourcesApi } from '../services/api-cbl-sources'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { readingGraphApi } from '../services/api-reading-graph'
import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
  CBLCatalogBrowsePage,
  CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { cast } from '../utils/cast'
import { withoutOverlap } from './readingGraphFixture'

vi.mock('../services/api-cbl-sources', () => ({
  cblSourcesApi: {
    discover: vi.fn(),
    browse: vi.fn(),
    preview: vi.fn(),
    plan: vi.fn(),
    commitNew: vi.fn(),
    compare: vi.fn(),
    findByComicvineIssue: vi.fn(),
    readingListCandidates: vi.fn(),
    detail: vi.fn().mockResolvedValue({
      id: 7,
      name: 'Ultimate Reading Order',
      source_path: 'Marvel/Ultimate.cbl',
      source_repository: 'JoshCLWren/CBL-ReadingLists',
      source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
      declared_issue_count: 2,
      content_hash: 'hash-1',
      revision_sha: 'abcdef1234567890',
      entries_total: 2,
      entries_offset: 0,
      entries_limit: 200,
      entries: [
        {
          position: 1,
          series_name: 'Ultimate Spider-Man',
          issue_number: '1',
          volume_year: null,
          publication_year: null,
          comicvine_issue_id: '4000-1',
          comicvine_volume_id: '4000-vol-1',
        },
        {
          position: 2,
          series_name: 'Ultimate Spider-Man',
          issue_number: '2',
          volume_year: null,
          publication_year: null,
          comicvine_issue_id: '4000-2',
          comicvine_volume_id: '4000-vol-1',
        },
      ],
    }),
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

export const mockBrowse = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.browse)
export const mockPreview = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.preview)
export const mockPlan = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.plan)
export const mockCommitNew = cast<ReturnType<typeof vi.fn>>(cblSourcesApi.commitNew)
export const mockGraphPreview = cast<ReturnType<typeof vi.fn>>(readingGraphApi.preview)
export const mockListPlans = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.list)
export const mockGetPlan = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.get)
export const mockApplyCommitted = cast<ReturnType<typeof vi.fn>>(applyCommittedReadingPlan)

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})

export function queryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

export function LocationProbe() {
  const location = useLocation()
  return (
    <>
      <p data-testid="location">{location.pathname}</p>
      <p data-testid="location-search">{location.search}</p>
    </>
  )
}

export function HistoryBackProbe() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(-1)}>
      history-back
    </button>
  )
}

export function renderPage(initialEntry = '/cbl-sources') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/cbl-sources"
          element={
            <>
              <CblBrowserPage />
              <LocationProbe />
              <HistoryBackProbe />
            </>
          }
        />
        <Route path="/continuity-plans/:id" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: queryWrapper },
  )
}

export const source: CBLSourceListDiscoveryItem = {
  id: 7,
  name: 'Ultimate Universe',
  source_path: 'Ultimate.cbl',
  source_repository: 'JoshCLWren/CBL-ReadingLists',
  declared_issue_count: 4,
  content_hash: 'hash-1',
  revision_sha: 'abcdef1234567890',
}

export function browsePage(overrides: Partial<CBLCatalogBrowsePage> = {}): CBLCatalogBrowsePage {
  return {
    scope: 'folder',
    folder: '',
    query: null,
    breadcrumbs: [{ name: 'All CBLs', path: '' }],
    folders: [],
    items: [],
    page: 1,
    page_size: 50,
    total: 0,
    total_pages: 0,
    has_next: false,
    has_previous: false,
    ...overrides,
  }
}

export function searchPage(term = 'ultimate', items = [source]): CBLCatalogBrowsePage {
  return browsePage({
    scope: 'search',
    query: term,
    breadcrumbs: [{ name: 'All CBLs', path: '' }],
    items,
    total: items.length,
    total_pages: items.length > 0 ? 1 : 0,
  })
}

export function entry(overrides: Partial<CBLAdoptionPreviewEntry>): CBLAdoptionPreviewEntry {
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

export function preview(overrides?: {
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
  mockBrowse.mockResolvedValue(browsePage())
})

export async function searchFor(user: ReturnType<typeof userEvent.setup>, term = 'ultimate') {
  mockBrowse.mockResolvedValue(searchPage(term))
  await user.type(screen.getByLabelText('Search source lists'), term)
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
  })
}

export async function selectSource(user: ReturnType<typeof userEvent.setup>, p = preview()) {
  mockPreview.mockResolvedValue(p)
  await user.click(screen.getByRole('button', { name: /Ultimate Universe/ }))
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'Ultimate Universe' })).toBeInTheDocument()
  })
}

export async function confirmAdd(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Add this reading order' }))
  await user.click(screen.getByRole('button', { name: 'Add reading order' }))
}

export async function openChecklist(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Customize' }))
}

export async function expandVolume(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
): Promise<void> {
  await user.click(screen.getByRole('button', { name: `Show issues for ${label}` }))
}
export type { CBLSourceListDiscoveryItem, CBLAdoptionPreview } from '../services/api-cbl-sources'
