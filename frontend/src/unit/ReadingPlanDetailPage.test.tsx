import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPlanDetailPage from '../pages/ReadingPlanDetailPage'
import { continuityPlansApi, type ReadingPlanReaderView } from '../services/api-continuity-plans'
import { tagsApi } from '../services/api-tags'
import { cast } from '../utils/cast'

vi.mock('../services/api-continuity-plans', async () => {
  const actual = await vi.importActual<typeof import('../services/api-continuity-plans')>(
    '../services/api-continuity-plans',
  )
  return {
    ...actual,
    continuityPlansApi: {
      ...actual.continuityPlansApi,
      getReader: vi.fn(),
    },
  }
})

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    threadIssuesEffective: vi.fn().mockResolvedValue({ thread_id: 1, issues: [] }),
    effectiveForPlan: vi.fn(),
    unassign: vi.fn(),
  },
}))

vi.mock('../components/ReadingPlanAddMaterial', () => ({
  default: () => <div data-testid="add-from-cbl">Add from CBL</div>,
}))

vi.mock('../components/Tags/TagSection', () => ({
  TagSection: () => <div data-testid="reading-plan-tags">Tags</div>,
}))

const mockGetReader = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.getReader)
const mockPlanTags = vi.mocked(tagsApi.effectiveForPlan)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function ReadingListEditorTarget() {
  const { id } = useParams()
  return <div>Reading List editor {id}</div>
}

function renderPage(planId = '12') {
  return render(
    <MemoryRouter initialEntries={[`/continuity-plans/${planId}`]}>
      <Routes>
        <Route path="/continuity-plans/:id" element={<ReadingPlanDetailPage />} />
        <Route path="/continuity-plans/:id/edit" element={<div>Editor</div>} />
        <Route path="/reading-lists/:id" element={<ReadingListEditorTarget />} />
        <Route path="/thread/:id" element={<div>Thread page</div>} />
      </Routes>
    </MemoryRouter>,
    { wrapper: createWrapper() },
  )
}

const blockedIssue = {
  occurrence_id: 'c75',
  issue_id: 75,
  lane_id: 'main',
  display_position: 1,
  issue_number: '75',
  thread_id: 8,
  thread_title: 'Cable',
  status: 'unread',
  availability: 'blocked' as const,
  blockers: [
    {
      issue_id: 95,
      thread_id: 4,
      thread_title: 'X-Men',
      issue_number: '95',
      explanation: 'Blocked by X-Men: #95',
    },
  ],
  source_paths: ['Marvel/Age of Apocalypse.cbl'],
}

const availableIssue = {
  occurrence_id: 'x95',
  issue_id: 95,
  lane_id: 'main',
  display_position: 0,
  issue_number: '95',
  thread_id: 4,
  thread_title: 'X-Men',
  status: 'unread',
  availability: 'available' as const,
  blockers: [],
  source_paths: ['Marvel/Age of Apocalypse.cbl'],
}

const laterIssue = {
  occurrence_id: 'c76',
  issue_id: 76,
  lane_id: 'main',
  display_position: 2,
  issue_number: '76',
  thread_id: 8,
  thread_title: 'Cable',
  status: 'unread',
  availability: 'later' as const,
  blockers: [],
  source_paths: ['Marvel/Age of Apocalypse.cbl'],
}

const readerView: ReadingPlanReaderView = {
    plan_id: 12,
    name: 'Age of Apocalypse',
    ordering_mode: 'informational',
    progress: { total_issues: 3, read_issues: 0 },
    available_now: [availableIssue],
    blocked_next: [blockedIssue],
    lanes: [
      {
        id: 'main',
        name: 'Main',
        order: 0,
        issues: [availableIssue, blockedIssue, laterIssue],
      },
    ],
    sources: [
      {
        id: 1,
        raw_source_path: 'Marvel/Age of Apocalypse.cbl',
        repository: null,
        source_path: null,
        revision_sha: null,
        content_hash: null,
        adopted_at: null,
        recorded_at: '2026-10-12T00:00:00Z',
      },
    ],
    release_sources: [
      {
        source_id: 901,
        thread_id: 4,
        external_identity_id: 77,
        provider_volume_id: '4000-77',
        provider_title: 'X-Men',
        provider_publisher: 'Marvel',
        provider_start_year: 1963,
        provider_issue_count: 12,
        enabled: true,
        last_synced_at: '2026-10-17T05:00:00Z',
      },
    ],
    release_candidates: [
      {
        thread_id: 9,
        thread_title: 'Ultimate Spider-Man',
        mapping_state: 'confirmed',
        external_identity_id: 88,
        provider_volume_id: '60520-1234',
        provider_title: 'Ultimate Spider-Man (2024)',
        provider_publisher: 'Marvel',
        provider_start_year: 2024,
        provider_issue_count: 8,
        mapping_status: 'confirmed',
        enableable: true,
        followed: false,
      },
      {
        thread_id: 10,
        thread_title: 'Unmapped Series',
        mapping_state: 'unmapped',
        external_identity_id: null,
        provider_volume_id: null,
        provider_title: null,
        provider_publisher: null,
        provider_start_year: null,
        provider_issue_count: null,
        mapping_status: null,
        enableable: false,
        followed: false,
      },
    ],
  }

beforeEach(() => {
  vi.clearAllMocks()
  mockGetReader.mockResolvedValue(readerView)
  mockPlanTags.mockResolvedValue({
    target_type: 'ContinuityPlan',
    target_id: 12,
    direct_tags: [],
    effective_tags: [],
  })
})

describe('ReadingPlanDetailPage', () => {
  it('uses readable source names in issue rows and keeps provenance in details', async () => {
    const source = { ...readerView.sources[0], raw_source_path: 'custom-cbl:1000002', source_path: null, display_name: 'Mignolaverse' }
    mockGetReader.mockResolvedValue({ ...readerView, sources: [source], available_now: readerView.available_now.map((issue) => ({ ...issue, source_paths: [source.raw_source_path] })) })
    renderPage()
    expect(await screen.findByText('Mignolaverse')).toBeVisible()
    expect(screen.getByText('Source reading order: Mignolaverse')).toBeVisible()
    expect(screen.queryByText(/custom-cbl:/)).not.toBeInTheDocument()
  })

  it('opens a linked Reading List directly instead of the obsolete plan editor', async () => {
    mockGetReader.mockResolvedValue({
      ...readerView,
      sources: [
        { ...readerView.sources[0], raw_source_path: 'custom-cbl:9999', display_name: null },
        { ...readerView.sources[0], id: 2, raw_source_path: 'custom-cbl:2', display_name: 'Mignolaverse' },
      ],
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit reading order' }))
    expect(screen.getByText('Reading List editor 2')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit plan' })).not.toBeInTheDocument()
  })

  it('does not navigate to an unresolved or foreign Reading List from source paths alone', async () => {
    mockGetReader.mockResolvedValue({
      ...readerView,
      sources: [{ ...readerView.sources[0], raw_source_path: 'custom-cbl:9999', display_name: null }],
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit plan' }))
    expect(screen.getByText('Editor')).toBeInTheDocument()
    expect(screen.queryByText('Reading List editor')).not.toBeInTheDocument()
  })

  it('preserves bracketed prefixes in owned Reading List names', async () => {
    const source = { ...readerView.sources[0], raw_source_path: 'custom-cbl:1000002', source_path: null, display_name: '[Favorites]' }
    mockGetReader.mockResolvedValue({ ...readerView, sources: [source], available_now: readerView.available_now.map((issue) => ({ ...issue, source_paths: [source.raw_source_path] })) })
    renderPage()
    expect(await screen.findByText('Source reading order: [Favorites]')).toBeVisible()
    expect(screen.queryByText('Source reading order: Custom Reading List')).not.toBeInTheDocument()
  })

  it('shows progress, available now, and the actual blocker', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Age of Apocalypse' })).toBeInTheDocument()
    expect(screen.getByTestId('plan-progress')).toHaveTextContent('0%')
    expect(screen.getByText('Informational')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Available now' })).toBeInTheDocument()
    expect(screen.getAllByText('X-Men #95').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'Blocked next' })).toBeInTheDocument()
    expect(within(screen.getByTestId('blocked-next')).getByRole('link', { name: 'Open X-Men issue #95' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Upcoming' })).toBeInTheDocument()
    expect(within(screen.getByTestId('upcoming-material')).queryByText('Cable #76')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 upcoming issues' }))
    expect(within(screen.getByTestId('upcoming-material')).getByText('Cable #76')).toBeInTheDocument()
    expect(screen.getByText('Source reading order')).toBeInTheDocument()
    expect(screen.getByText('CBL-backed')).toBeInTheDocument()
    expect(screen.getByText('Marvel/Age of Apocalypse.cbl')).not.toBeVisible()
    fireEvent.click(screen.getByText('Source details'))
    expect(screen.getByText('Marvel/Age of Apocalypse.cbl')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Continue reading' })).toHaveAttribute('href', '/thread/4')
    expect(screen.getByRole('button', { name: 'Edit plan' })).toBeInTheDocument()
    expect(screen.queryByText(/ContinuityRule/i)).not.toBeInTheDocument()
    // Release following is secondary, hidden until explicitly requested.
    expect(screen.queryByRole('heading', { name: 'New releases' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Manage release tracking' }))
    expect(screen.getByRole('heading', { name: 'New releases' })).toBeInTheDocument()
    const newRelease = within(screen.getByTestId('new-release-source'))
    expect(newRelease.getByText(/X-Men/)).toBeInTheDocument()
    expect(newRelease.getByText('Target thread #4')).toBeInTheDocument()
    expect(newRelease.getByText(/Last sync:/)).toBeInTheDocument()
    expect(
      newRelease.getByRole('button', { name: 'Stop following X-Men' }),
    ).toBeInTheDocument()
  })

  it('offers confirmed release candidates and explains unmapped threads need a mapping', async () => {
    renderPage()

    await screen.findByRole('heading', { name: 'Age of Apocalypse' })
    fireEvent.click(screen.getByRole('button', { name: 'Manage release tracking' }))
    const candidate = within(screen.getByTestId('new-release-candidate'))
    expect(candidate.getByText(/Ultimate Spider-Man \(2024\)/)).toBeInTheDocument()
    expect(
      candidate.getByRole('button', { name: 'Follow Ultimate Spider-Man (2024)' }),
    ).toBeInTheDocument()

    const blocked = within(screen.getByTestId('new-release-blocked-candidate'))
    expect(blocked.getByText(/No ComicVine volume is mapped/)).toBeInTheDocument()
    expect(blocked.queryByRole('button', { name: /^Follow/ })).not.toBeInTheDocument()
    expect(
      blocked.getByText(/Track issues in this thread first, then map its series/),
    ).toBeInTheDocument()
    expect(blocked.queryByRole('link', { name: 'Repair the mapping' })).not.toBeInTheDocument()
  })


  it('keeps Julix-sized strict blockers and release-follow noise out of the initial screen', async () => {
    const blockers = Array.from({ length: 382 }, (_, index) => ({
      issue_id: index + 1000,
      thread_id: index + 2000,
      thread_title: index === 0 ? 'B.P.R.D.: Casualties' : `Extra prerequisite ${index}`,
      issue_number: '1',
      explanation: `Strict order: waiting on requirement ${index}`,
    }))
    mockGetReader.mockResolvedValue({
      ...readerView,
      name: 'Mignolaverse',
      ordering_mode: 'strict_sequential',
      execution_mode: 'option_e',
      progress: { total_issues: 464, read_issues: 82 },
      available_now: [],
      blocked_next: Array.from({ length: 8 }, (_, index) => ({
        ...blockedIssue,
        occurrence_id: `blocked-${index}`,
        issue_id: 75 + index,
        blockers,
      })),
      lanes: [{
        ...readerView.lanes[0],
        issues: Array.from({ length: 464 }, (_, index) => ({
          ...laterIssue,
          occurrence_id: `later-${index}`,
          issue_id: 500 + index,
        })),
      }],
    })
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Mignolaverse' })).toBeInTheDocument()
    expect(screen.getAllByTestId('reading-plan-issue-row')).toHaveLength(3)
    expect(screen.getAllByRole('link', { name: 'Open B.P.R.D.: Casualties issue #1' })).toHaveLength(3)
    expect(screen.queryByText('Extra prerequisite 1 #1')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Follow Ultimate Spider-Man (2024)' })).not.toBeInTheDocument()
    expect(screen.getByText(/This linked Reading List controls reading eligibility/)).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Show 381 other reading requirements' })[0])
    expect(screen.getByRole('link', { name: 'Open Extra prerequisite 1 issue #1' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show 5 more blocked issues' }))
    expect(screen.getAllByTestId('reading-plan-issue-row')).toHaveLength(8)
    expect(screen.queryByText('Cable #76')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show complete reading order (464 issues)' }))
    expect(screen.getAllByTestId('reading-plan-issue-row')).toHaveLength(472)
  })

  it('keeps optional release tracking outside the reading workflow until opened', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Age of Apocalypse' })
    const releaseHeading = screen.getByRole('heading', { name: 'Optional: Track future releases' })
    const availableHeading = screen.getByRole('heading', { name: 'Available now' })
    expect(availableHeading.compareDocumentPosition(releaseHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.queryByTestId('new-release-candidate')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Manage release tracking' }))
    expect(screen.getByTestId('new-release-candidate')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Hide release tracking' }))
    expect(screen.queryByTestId('new-release-candidate')).not.toBeInTheDocument()
  })
  it('rejects an invalid plan id before fetching', () => {
    renderPage('not-a-number')
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid reading plan ID.')
    expect(mockGetReader).not.toHaveBeenCalled()
  })
})
